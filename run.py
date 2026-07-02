#!/usr/bin/env python3
"""
Backport Agent Leaderboard — OpenShift runner.

Works with any repo — driven entirely by evals/<repo>/config.yaml.

Usage:
  python3 run.py --config evals/crate/config.yaml            # launch all enabled tools
  python3 run.py --config evals/crate/config.yaml --tool raw-claude
  python3 run.py --config evals/crate/config.yaml --tool amalgamator
  python3 run.py --config evals/crate/config.yaml --collect  # collect results → JSON
  python3 run.py --config evals/crate/config.yaml --push-results  # push to leaderboard pod
"""

import argparse, csv, json, os, re, random, subprocess, tempfile, textwrap, time
from datetime import datetime, timezone
from pathlib import Path

import yaml  # pip install pyyaml

REPO_ROOT  = Path(__file__).parent
LOCAL_REPO = None   # resolved in main() from config or default path


# ═══════════════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════════════

def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    if "csv" in cfg.get("dataset", {}):
        cfg_dir = Path(config_path).parent
        cfg["dataset"]["csv"] = str((cfg_dir / cfg["dataset"]["csv"]).resolve())
    return cfg

def repo_slug(cfg: dict) -> str:
    """cri-o/cri-o → crio, django/django → django, crate/crate → crate"""
    return re.sub(r"[^a-z0-9]", "", cfg["repo"].split("/")[-1].lower())[:10]

def get_lang(cfg: dict) -> str:
    return cfg.get("lang", "java")

def get_clone_url(cfg: dict) -> str:
    return cfg.get("clone_url", f"https://github.com/{cfg['repo']}.git")


# ═══════════════════════════════════════════════════════════════════════════
# Dataset
# ═══════════════════════════════════════════════════════════════════════════

def load_cases(cfg: dict) -> list[dict]:
    ds   = cfg["dataset"]
    repo = cfg["repo"]

    if ds.get("commits"):
        return [{"orig_sha": c["orig"], "backport_sha": c["backport"]} for c in ds["commits"]]

    with open(ds["csv"]) as f:
        rows = [r for r in csv.DictReader(f) if r["repo"] == repo]

    if ds.get("classification"):
        rows = [r for r in rows if r["Classification"] == ds["classification"]]

    if ds.get("limit"):
        random.seed(ds.get("seed", 42))
        rows = random.sample(rows, min(int(ds["limit"]), len(rows)))

    return [{"orig_sha": r["Original Commit"], "backport_sha": r["Backport Commit"],
             "classification": r["Classification"]} for r in rows]


# ═══════════════════════════════════════════════════════════════════════════
# Git helpers (run against a local clone for metadata only)
# ═══════════════════════════════════════════════════════════════════════════

def git(args, cwd=None):
    cwd = cwd or LOCAL_REPO
    if not cwd or not Path(cwd).exists():
        raise RuntimeError(
            f"Local repo clone not found at {cwd}.\n"
            f"Set 'local_clone' in config.yaml or clone the repo to that path."
        )
    return subprocess.run(["git"] + args, capture_output=True, text=True, cwd=str(cwd))

def ensure_sha(sha):
    if git(["cat-file", "-t", sha]).returncode == 0:
        return True
    return git(["fetch", "--depth=50", "origin", sha]).returncode == 0

def get_parent(sha):
    r = git(["rev-parse", f"{sha}^"])
    return r.stdout.strip() if r.returncode == 0 else None

def get_test_identifier(sha: str, language: str) -> str | None:
    """Return test name/class for the given commit, language-aware.

    Java   → *Test.java class name (e.g. ShardUpsertExecutorTest)
    Go     → Test* function name from diff (e.g. TestCreateContainer)
    Python → dotted test module (e.g. auth.test_basic) or class name
    """
    r     = git(["show", "--name-only", "--pretty=format:", sha])
    files = [l for l in r.stdout.strip().splitlines() if l.strip()]

    if language == "java":
        tests = [f.split("/")[-1].replace(".java", "") for f in files if "Test.java" in f]
        return tests[0] if tests else None

    elif language == "go":
        test_files = [f for f in files if f.endswith("_test.go")]
        if not test_files:
            return None
        diff_r = git(["show", sha])
        fns    = re.findall(r"^\+func (Test\w+)", diff_r.stdout, re.MULTILINE)
        if fns:
            return fns[0]
        # Fallback: derive a Test* name from the file name
        name = test_files[0].split("/")[-1].replace("_test.go", "")
        return "Test" + "".join(w.title() for w in name.split("_"))

    elif language == "python":
        test_files = [f for f in files if re.search(r"test.*\.py$", f.split("/")[-1])]
        if not test_files:
            # Fallback: derive module from the tests/ directory path
            # e.g. django/contrib/auth/tests/urls.py → contrib.auth.tests
            for f in files:
                parts = f.split("/")
                for i, p in enumerate(parts):
                    if p in ("tests", "test"):
                        # Skip top-level package name (e.g. "django")
                        before = parts[1:i] if len(parts) > 1 else parts[:i]
                        return ".".join(before + [p]) if before else p
            return None
        diff_r  = git(["show", sha])
        classes = re.findall(r"^\+class (Test\w+)", diff_r.stdout, re.MULTILINE)
        if classes:
            return classes[0]
        # Convert path to dotted module: tests/auth/test_basic.py → auth.test_basic
        tf    = test_files[0]
        parts = tf.replace(".py", "").split("/")
        if parts and parts[0] in ("tests", "test"):
            parts = parts[1:]
        return ".".join(p for p in parts if p)

    return None

def get_module_path(sha: str, language: str) -> str | None:
    """Return Maven module (Java), Go package path (Go), or None (Python)."""
    r     = git(["show", "--name-only", "--pretty=format:", sha])
    files = [l for l in r.stdout.strip().splitlines() if l.strip()]

    if language == "java":
        src = [f for f in files if "/src/" in f]
        return src[0].split("/src/")[0] if src else None

    elif language == "go":
        go_files = [f for f in files if f.endswith(".go") and not f.endswith("_test.go")]
        if not go_files:
            go_files = [f for f in files if f.endswith("_test.go")]
        if go_files:
            pkg_dir = "/".join(go_files[0].split("/")[:-1])
            return f"./{pkg_dir}/..." if pkg_dir else "./..."
        return "./..."

    return None   # Python — no module concept needed

def guess_branch(backport_sha: str, repository: str = "") -> str:
    """Determine the target branch for this backport commit."""
    # crate-specific: release-notes RST filenames encode the branch
    if "crate" in repository:
        r = git(["show", "--name-only", "--pretty=format:", backport_sha])
        for f in r.stdout.strip().splitlines():
            if "release-notes/" in f and ".rst" in f:
                parts = f.split("/")[-1].replace(".rst", "").split(".")
                if len(parts) >= 2:
                    return f"{parts[0]}.{parts[1]}"

    # Generic: find a non-main remote branch that contains this commit
    r = git(["branch", "-r", "--contains", backport_sha])
    for line in r.stdout.strip().splitlines():
        b = line.strip()
        if "->" in b:
            continue
        b = b.replace("origin/", "")
        if b not in ("main", "master", "HEAD"):
            return b

    return "target"


# ═══════════════════════════════════════════════════════════════════════════
# Case preparation
# ═══════════════════════════════════════════════════════════════════════════

def prepare_cases(raw_cases: list[dict], cfg: dict) -> list[dict]:
    language   = get_lang(cfg)
    repository = cfg["repo"]
    build_tmpl = cfg.get("build_command", "")
    test_tmpl  = cfg.get("test_command", "")

    cases = []
    for r in raw_cases:
        orig, backport = r["orig_sha"], r["backport_sha"]
        # Use orig+backport to keep slugs unique when the same orig commit is
        # backported to multiple branches (same orig, different backport SHA).
        slug_id = orig[:8] + backport[:4]

        for sha in [orig, backport]:
            if not ensure_sha(sha):
                print(f"  [SKIP] cannot fetch {sha[:12]}")
                break
        else:
            pre_fix = get_parent(backport)
            if not pre_fix:
                print(f"  [SKIP] cannot get parent of {backport[:12]}")
                continue

            test_id = get_test_identifier(orig, language)
            module  = get_module_path(orig, language)
            branch  = guess_branch(backport, repository)

            fmt = {"module": module or "", "test_class": test_id or ""}
            try:
                build_cmd = build_tmpl.format(**fmt).strip() if build_tmpl else ""
                test_cmd  = test_tmpl.format(**fmt).strip()
            except KeyError as e:
                print(f"  [WARN] unknown template placeholder {e}")
                build_cmd, test_cmd = build_tmpl.strip(), test_tmpl.strip()

            # For Go with no specific test function detected, drop the -run flag
            # so the command runs all tests in the package instead of nothing.
            if language == "go" and not test_id:
                test_cmd = re.sub(r"-run\s*\S*\s*", "", test_cmd).strip()

            print(f"  {slug_id}  [{r.get('classification','?'):7s}]  "
                  f"branch={branch}  module={module}  test={test_id}")
            cases.append({
                "slug":           slug_id,
                "orig_sha":       orig,
                "backport_sha":   backport,
                "pre_fix_sha":    pre_fix,
                "classification": r.get("classification", "Unknown"),
                "target_branch":  branch,
                "module":         module or "",
                "test_class":     test_id,
                "build_cmd":      build_cmd,
                "test_cmd":       test_cmd,
            })
    return cases


# ═══════════════════════════════════════════════════════════════════════════
# Pod script fragments
# ═══════════════════════════════════════════════════════════════════════════

def _toolchains_b64() -> str:
    """Return base64-encoded toolchains.xml content — avoids heredoc indentation issues."""
    import base64
    jdk_home = "/opt/java/openjdk"
    # Include both the exact build-string versions AND the plain x.y.z aliases
    # so Maven matches regardless of whether pom.xml pins the build suffix.
    versions = [
        "21", "21.0.5", "21.0.5+11", "21.0.6", "21.0.6+7",
        "22", "22.0.1", "22.0.1+8", "22.0.2", "22.0.2+9",
        "23", "23.0.1", "23.0.1+11", "23.0.2", "23.0.2+7",
        "24", "24.0.1", "24.0.1+9", "24.0.2", "24.0.2+7",
        "25", "25.0.1", "25.0.1+9", "25.0.3",
    ]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<toolchains>"]
    for v in versions:
        lines.append(
            f'  <toolchain><type>jdk</type><provides><version>{v}</version>'
            f'<vendor>temurin</vendor></provides>'
            f'<configuration><jdkHome>{jdk_home}</jdkHome></configuration></toolchain>'
        )
    lines.append("</toolchains>")
    return base64.b64encode("\n".join(lines).encode()).decode()

# Python snippet run inside the pod that saves /tmp/eval_result.json to a ConfigMap.
# Double-braced {{ }} because this string is used inside an f-string.
CONFIGMAP_SAVER = """\
                  python3 << 'PYEOF'
                  import json, os, ssl, urllib.request

                  def _upsert_cm(base, hdrs, ctx, cm_name, data_dict):
                      cm  = {{'apiVersion': 'v1', 'kind': 'ConfigMap',
                              'metadata': {{'name': cm_name, 'namespace': ns}},
                              'data': data_dict}}
                      req = urllib.request.Request(base, json.dumps(cm).encode(), hdrs, method='POST')
                      try:
                          urllib.request.urlopen(req, context=ctx)
                          print('Saved ConfigMap ' + cm_name)
                      except urllib.error.HTTPError as e:
                          if e.code == 409:
                              hdrs2 = dict(hdrs)
                              hdrs2['Content-Type'] = 'application/strategic-merge-patch+json'
                              patch = {{'data': data_dict}}
                              req2  = urllib.request.Request(base + '/' + cm_name, json.dumps(patch).encode(), hdrs2, method='PATCH')
                              urllib.request.urlopen(req2, context=ctx)
                              print('Updated ConfigMap ' + cm_name)
                          else:
                              print('WARNING: HTTP ' + str(e.code))

                  try:
                      data  = json.load(open('/tmp/eval_result.json'))
                      token = open('/var/run/secrets/kubernetes.io/serviceaccount/token').read().strip()
                      ns    = open('/var/run/secrets/kubernetes.io/serviceaccount/namespace').read().strip()
                      ca    = '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
                      slug  = data.get('slug', 'unknown')
                      ctx   = ssl.create_default_context(cafile=ca)
                      base  = 'https://kubernetes.default.svc/api/v1/namespaces/' + ns + '/configmaps'
                      hdrs  = {{'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}}

                      # Save result JSON
                      _upsert_cm(base, hdrs, ctx, '{cm_prefix}-' + slug, {{'result': json.dumps(data)}})

                      # Save full pod log
                      log_path = '/tmp/pod_run.log'
                      log_text = open(log_path).read() if os.path.exists(log_path) else '(no log captured)'
                      log_cm   = 'log-{cm_prefix}-' + slug
                      _upsert_cm(base, hdrs, ctx, log_cm, {{'log': log_text[:900000]}})

                  except Exception as ex:
                      print('WARNING: ConfigMap save failed: ' + str(ex))
                  PYEOF"""

# Python snippet run inside the pod to build the RunResult JSON and save it.
# Variables are exported from bash before this runs.
JSON_BUILDER = """\
                  export APPLY_RESULT TEST_RESULT BASELINE_TEST LATENCY_S \\
                         INPUT_TOKENS OUTPUT_TOKENS COST_USD DIFF_LINES \\
                         SEM_EQ_RESULT SEM_EQ_REASON
                  python3 << 'JSONEOF'
                  import json, os
                  from datetime import datetime, timezone
                  apply      = os.environ.get('APPLY_RESULT', 'FAILED')
                  test       = os.environ.get('TEST_RESULT', 'SKIPPED')
                  diff_lines = int(os.environ.get('DIFF_LINES', 0))
                  sem_eq_env = os.environ.get('SEM_EQ_RESULT', '').strip()
                  if sem_eq_env:
                      sem_eq  = 'PASS' if sem_eq_env == 'PASS' else 'FAIL'
                      sem_why = os.environ.get('SEM_EQ_REASON', '') or None
                  elif apply == 'SUCCESS' and diff_lines == 0:
                      sem_eq  = 'FAIL'
                      sem_why = 'No changes produced (diff_lines=0)'
                  elif apply == 'SUCCESS':
                      sem_eq  = 'PASS'
                      sem_why = None
                  else:
                      sem_eq  = 'FAIL'
                      sem_why = None
                  d = {{
                      'slug':                      '{slug}',
                      'tool_display_name':         '{tool_display_name}',
                      'tool_key':                  '{tool_key}',
                      'repo':                      '{repo}',
                      'original_commit':           '{orig}',
                      'backport_commit':           '{backport}',
                      'classification':            '{difficulty}',
                      'semantic_equivalence':      sem_eq,
                      'semantic_difference_reason': sem_why,
                      'guideline_adherence':       None,
                      'guideline_reason':          None,
                      'test_success':              'PASS' if test == 'PASS' else ('FAIL' if test in ('FAIL','BUILD_FAIL') else None),
                      'baseline_test':             os.environ.get('BASELINE_TEST', 'SKIPPED'),
                      'error_message':             None,
                      'diff_lines':                diff_lines,
                      'test_command':              '{test_cmd}',
                      'time_seconds':              float(os.environ.get('LATENCY_S', 0)),
                      'llm_calls':                 {llm_calls},
                      'cost_usd':                  float(os.environ.get('COST_USD', 0)),
                      'input_tokens':              int(os.environ.get('INPUT_TOKENS', 0)),
                      'output_tokens':             int(os.environ.get('OUTPUT_TOKENS', 0)),
                      'timestamp':                 datetime.now(timezone.utc).isoformat(),
                  }}
                  with open('/tmp/eval_result.json', 'w') as f:
                      json.dump(d, f)
                  print('EVAL_RESULT:', json.dumps(d))
                  JSONEOF"""


# ═══════════════════════════════════════════════════════════════════════════
# Job YAML builders (generic — driven by config)
# ═══════════════════════════════════════════════════════════════════════════

def _java_setup() -> str:
    """Return bash snippet to write toolchains.xml (Java/Maven only).

    Uses base64 to avoid heredoc-inside-YAML indentation issues that corrupt <?xml.
    """
    b64 = _toolchains_b64()
    return f"""\
                  echo "=== Write toolchains.xml ==="
                  echo '{b64}' | base64 -d > /tmp/toolchains.xml
                  echo "toolchains.xml written"
"""


def build_raw_claude_job(case: dict, cfg: dict) -> str:
    oc      = cfg["openshift"]
    tool    = cfg["tools"]["raw-claude"]
    rslug   = repo_slug(cfg)
    language = get_lang(cfg)

    slug       = case["slug"]
    orig       = case["orig_sha"]
    backport   = case["backport_sha"]
    pre_fix    = case["pre_fix_sha"]
    branch     = case["target_branch"]
    difficulty = case["classification"]
    build_cmd  = case["build_cmd"]
    test_cmd   = case["test_cmd"]

    model    = tool["model"]
    image    = tool["image"]
    ns       = oc["namespace"]
    res      = oc["resources"]["raw-claude"]
    timeout  = oc["job_timeout_seconds"]
    vproject = oc["vertex_project"]
    vregion  = oc["vertex_region"]
    clone_url = get_clone_url(cfg)

    cm_prefix  = f"result-raw-{rslug}"
    cm_saver   = CONFIGMAP_SAVER.format(cm_prefix=cm_prefix)
    json_bldr  = JSON_BUILDER.format(
        slug=slug, tool_display_name=tool["display_name"], tool_key="raw-claude",
        repo=cfg["repo"], orig=orig, backport=backport, difficulty=difficulty,
        llm_calls=1, test_cmd=test_cmd,
    )
    java_setup = _java_setup() if language == "java" else ""
    build_step = (f"""\
                  echo "=== Build ==="
                  if {build_cmd}; then
                    echo "Build OK"
                  else
                    TEST_RESULT="BUILD_FAIL"
                  fi
""") if build_cmd else ""

    return textwrap.dedent(f"""\
    apiVersion: batch/v1
    kind: Job
    metadata:
      name: {rslug}-raw-{slug}
    spec:
      backoffLimit: 0
      activeDeadlineSeconds: {timeout}
      ttlSecondsAfterFinished: 86400
      template:
        spec:
          restartPolicy: Never
          serviceAccountName: eval-result-writer
          volumes:
            - name: script-vol
              configMap:
                name: raw-claude-script
            - name: gcloud-creds
              secret:
                secretName: gcloud-adc
          containers:
            - name: eval
              image: {image}
              env:
                - name: GOOGLE_APPLICATION_CREDENTIALS
                  value: /creds/application_default_credentials.json
                - name: CLAUDE_CODE_USE_VERTEX
                  value: "1"
                - name: ANTHROPIC_VERTEX_PROJECT_ID
                  value: {vproject}
                - name: CLOUD_ML_REGION
                  value: {vregion}
                - name: HOME
                  value: /tmp
              volumeMounts:
                - name: script-vol
                  mountPath: /opt/script
                - name: gcloud-creds
                  mountPath: /creds
                  readOnly: true
              command: ["bash", "-c"]
              args:
                - |
                  BASELINE_TEST="SKIPPED"
                  APPLY_RESULT="FAILED"
                  TEST_RESULT="SKIPPED"
                  DIFF_LINES=0
                  COST_USD=0
                  SEM_EQ_RESULT=""
                  SEM_EQ_REASON=""

                  exec > >(tee /tmp/pod_run.log) 2>&1

                  echo "=== Install Python deps ==="
                  pip3 install --break-system-packages -q anthropic[vertex] google-auth 2>&1 | tail -2

{java_setup}
                  echo "=== Clone repo at pre-fix commit ==="
                  git clone --depth=100 {clone_url} /tmp/repo 2>&1 | tail -3
                  cd /tmp/repo
                  git fetch --depth=100 origin {pre_fix} 2>/dev/null || true
                  git checkout {pre_fix} 2>/dev/null || true
                  export PYTHONPATH=/tmp/repo:$PYTHONPATH
                  if [ "{language}" = "python" ]; then
                    echo "=== Install package from source ==="
                    pip3 install --break-system-packages -q -e . 2>&1 | tail -3
                  fi

                  echo "=== Pre-build (install local artifacts for baseline test) ==="
                  PRE_BUILD_OK=true
                  {build_cmd if build_cmd else "true"} || PRE_BUILD_OK=false
                  if $PRE_BUILD_OK; then
                    echo "Pre-build OK"
                  else
                    echo "Pre-build FAILED — baseline test will be skipped"
                    BASELINE_TEST="SKIPPED"
                  fi

                  if $PRE_BUILD_OK; then
                    echo "=== Baseline test (pre-patch) ==="
                    echo "Command: {test_cmd}"
                    if {test_cmd}; then
                      BASELINE_TEST="PASS"
                    else
                      BASELINE_TEST="FAIL"
                    fi
                    echo "BASELINE: $BASELINE_TEST"
                  fi

                  echo "=== Fetch orig commit for Raw Claude context ==="
                  git fetch --depth=5 origin {orig} 2>/dev/null || true

                  echo "=== Run Raw Claude ==="
                  START=$(date +%s)
                  RC_OUTPUT=$(python3 /opt/script/generic_claude_backport.py \\
                    --repo /tmp/repo --orig {orig} --target-sha {pre_fix} \\
                    --target-branch {branch} --model {model} \\
                    --out /tmp/backport.diff 2>&1) || true
                  END=$(date +%s)
                  echo "$RC_OUTPUT"
                  LATENCY_S=$((END - START))
                  INPUT_TOKENS=$(echo "$RC_OUTPUT" | grep -oP 'input: \\K[0-9]+' | tail -1)
                  OUTPUT_TOKENS=$(echo "$RC_OUTPUT" | grep -oP 'output: \\K[0-9]+' | tail -1)
                  COST_USD=$(echo "$RC_OUTPUT" | grep -oP 'COST_USD: \\K[0-9.]+' | tail -1)
                  INPUT_TOKENS=${{INPUT_TOKENS:-0}}
                  OUTPUT_TOKENS=${{OUTPUT_TOKENS:-0}}
                  COST_USD=${{COST_USD:-0}}

                  echo "=== Measure diff size ==="
                  DIFF_LINES=$(wc -l < /tmp/backport.diff 2>/dev/null || echo 0)
                  echo "Diff lines from Claude: $DIFF_LINES"

                  if [ ! -s /tmp/backport.diff ]; then
                    echo "APPLY: FAILED (empty diff)"
                  else
                    echo "" >> /tmp/backport.diff
                    patch -p1 --fuzz=5 < /tmp/backport.diff && APPLY_RESULT="SUCCESS" || true
                    echo "APPLY: $APPLY_RESULT"
                  fi

                  if [ "$APPLY_RESULT" = "SUCCESS" ]; then
                    echo "=== Semantic equivalence (vs ground truth) ==="
                    git fetch --depth=1 origin {backport} 2>/dev/null || true
                    TRUTH_DIFF=$(git diff {pre_fix} {backport} -- 2>/dev/null | grep "^[+-]" | grep -v "^[+-][+-][+-]" || true)
                    AGENT_DIFF=$(git diff {pre_fix} HEAD -- 2>/dev/null | grep "^[+-]" | grep -v "^[+-][+-][+-]" || true)
                    if [ -n "$TRUTH_DIFF" ] && [ "$TRUTH_DIFF" = "$AGENT_DIFF" ]; then
                      SEM_EQ_RESULT="PASS"
                      SEM_EQ_REASON=""
                      echo "Semantic equivalence: PASS (exact match with ground truth)"
                    else
                      SEM_EQ_RESULT="FAIL"
                      T=$(echo "$TRUTH_DIFF" | wc -l || echo 0)
                      A=$(echo "$AGENT_DIFF" | wc -l || echo 0)
                      SEM_EQ_REASON="Patch differs from ground truth (truth=${{T}} lines, agent=${{A}} lines)"
                      echo "Semantic equivalence: FAIL — $SEM_EQ_REASON"
                    fi
{build_step}
                    if [ "$TEST_RESULT" != "BUILD_FAIL" ]; then
                      echo "=== Test ==="
                      echo "Command: {test_cmd}"
                      if {test_cmd}; then
                        TEST_RESULT="PASS"
                      else
                        TEST_RESULT="FAIL"
                      fi
                    fi
                  fi

                  echo "TEST RESULT: $TEST_RESULT"
{json_bldr}
{cm_saver}
              resources:
                requests:
                  memory: "{res['memory']}"
                  cpu: "{res['cpu']}"
                limits:
                  memory: "{res['memory']}"
                  cpu: "{res['cpu']}"
    """)


def build_amalgamator_job(case: dict, cfg: dict) -> str:
    oc      = cfg["openshift"]
    tool    = cfg["tools"]["amalgamator"]
    rslug   = repo_slug(cfg)
    language = get_lang(cfg)

    slug       = case["slug"]
    orig       = case["orig_sha"]
    backport   = case["backport_sha"]
    pre_fix    = case["pre_fix_sha"]
    branch     = case["target_branch"]
    difficulty = case["classification"]
    build_cmd  = case["build_cmd"]
    test_cmd   = case["test_cmd"]

    model    = tool["model"]
    image    = tool["image"]
    ns       = oc["namespace"]
    res      = oc["resources"]["amalgamator"]
    timeout  = oc["job_timeout_seconds"]
    vproject = oc["vertex_project"]
    vregion  = oc["vertex_region"]
    clone_url = get_clone_url(cfg)
    source_branch = cfg.get("source_branch", "master")
    issue_id = f"{rslug}-{slug}"

    cm_prefix = f"result-amal-{rslug}"
    cm_saver  = CONFIGMAP_SAVER.format(cm_prefix=cm_prefix)
    json_bldr = JSON_BUILDER.format(
        slug=slug, tool_display_name=tool["display_name"], tool_key="amalgamator",
        repo=cfg["repo"], orig=orig, backport=backport, difficulty=difficulty,
        llm_calls="None", test_cmd=test_cmd,
    )
    java_setup = _java_setup() if language == "java" else ""

    return textwrap.dedent(f"""\
    apiVersion: batch/v1
    kind: Job
    metadata:
      name: {rslug}-amal-{slug}
    spec:
      backoffLimit: 0
      activeDeadlineSeconds: {timeout}
      ttlSecondsAfterFinished: 86400
      template:
        spec:
          restartPolicy: Never
          serviceAccountName: eval-result-writer
          volumes:
            - name: gcloud-creds
              secret:
                secretName: gcloud-adc
            - name: amalgamator-src
              configMap:
                name: amalgamator-src
          containers:
            - name: eval
              image: {image}
              env:
                - name: GOOGLE_APPLICATION_CREDENTIALS
                  value: /creds/application_default_credentials.json
                - name: CLAUDE_CODE_USE_VERTEX
                  value: "1"
                - name: ANTHROPIC_VERTEX_PROJECT_ID
                  value: {vproject}
                - name: CLOUD_ML_REGION
                  value: {vregion}
                - name: HOME
                  value: /tmp
                - name: UV_CACHE_DIR
                  value: /tmp/.uv-cache
                - name: UV_DATA_DIR
                  value: /tmp/.uv-data
              volumeMounts:
                - name: gcloud-creds
                  mountPath: /creds
                  readOnly: true
                - name: amalgamator-src
                  mountPath: /opt/amalgamator-src
              command: ["bash", "-c"]
              args:
                - |
                  BASELINE_TEST="SKIPPED"
                  PIPELINE_RESULT="FAILED"
                  TEST_RESULT="FAIL"
                  LATENCY_S=0
                  INPUT_TOKENS=0
                  OUTPUT_TOKENS=0
                  COST_USD=0
                  DIFF_LINES=0
                  SEM_EQ_RESULT=""
                  SEM_EQ_REASON=""

                  exec > >(tee /tmp/pod_run.log) 2>&1

                  echo "=== Install uv ==="
                  curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/tmp/uv-bin sh
                  export PATH="/tmp/uv-bin:$PATH"

{java_setup}
                  echo "=== Set git identity ==="
                  git config --global user.email "eval-bot@backport-bench.local"
                  git config --global user.name "Eval Bot"

                  echo "=== Clone repo ==="
                  git clone {clone_url} /tmp/repo 2>&1 | tail -3
                  cd /tmp/repo
                  git fetch origin {pre_fix} 2>/dev/null || true
                  git fetch origin {orig} 2>/dev/null || true
                  git checkout --detach {pre_fix}
                  git branch target-backport {pre_fix}
                  export PYTHONPATH=/tmp/repo:$PYTHONPATH
                  if [ "{language}" = "python" ]; then
                    echo "=== Install package from source ==="
                    pip3 install --break-system-packages -q -e . 2>&1 | tail -3
                  fi

                  echo "=== Pre-build (install local artifacts for baseline test) ==="
                  PRE_BUILD_OK=true
                  {build_cmd if build_cmd else "true"} || PRE_BUILD_OK=false
                  if $PRE_BUILD_OK; then
                    echo "Pre-build OK"
                  else
                    echo "Pre-build FAILED — baseline test will be skipped"
                    BASELINE_TEST="SKIPPED"
                  fi

                  if $PRE_BUILD_OK; then
                    echo "=== Baseline test (pre-patch) ==="
                    echo "Command: {test_cmd}"
                    if {test_cmd}; then
                      BASELINE_TEST="PASS"
                    else
                      BASELINE_TEST="FAIL"
                    fi
                    echo "BASELINE: $BASELINE_TEST"
                  fi

                  echo "=== Extract Amalgamator ==="
                  mkdir -p /tmp/amalgamator
                  tar xzf /opt/amalgamator-src/amalgamator.tar.gz -C /tmp/amalgamator 2>/dev/null || true

                  echo "=== Write pipeline config ==="
                  cat > /tmp/pipeline-config.yaml <<'PIPELINECFG'
                  issue_id: "{issue_id}"
                  bug_description: "Benchmark: backport {slug} to {branch}. Difficulty: {difficulty}."
                  repository:
                    source_path: "/tmp/repo"
                    workdir: "/tmp/pipeline-workdir"
                  branches:
                    source: "origin/{source_branch}"
                    target: "target-backport"
                  fix:
                    commit: "{orig}"
                  build:
                    command: "{build_cmd}"
                    test_command: "{test_cmd}"
                  model: "{model}"
                  advanced:
                    max_resolution_retries: 2
                    max_build_test_retries: 0
                  PIPELINECFG

                  echo "=== Run Amalgamator pipeline ==="
                  cd /tmp/amalgamator
                  PIPE_START=$(date +%s)
                  PIPE_OUTPUT=$(uv run python -m auto_bug_fix.run_bug_fix /tmp/pipeline-config.yaml 2>&1)
                  PIPE_EXIT=$?
                  PIPE_END=$(date +%s)
                  echo "$PIPE_OUTPUT"
                  LATENCY_S=$((PIPE_END - PIPE_START))

                  TOTAL_LINE=$(echo "$PIPE_OUTPUT" | grep -E "^\\s+TOTAL\\s+" | tail -1)
                  INPUT_TOKENS=$(echo "$PIPE_OUTPUT" | grep -oP 'tokens=\\K[0-9]+(?=/)' | paste -sd+ | bc 2>/dev/null || echo 0)
                  OUTPUT_TOKENS=$(echo "$PIPE_OUTPUT" | grep -oP 'tokens=[0-9]+/\\K[0-9]+' | paste -sd+ | bc 2>/dev/null || echo 0)
                  COST_USD=$(echo "$TOTAL_LINE" | grep -oP '\\$\\s*\\K[0-9.]+' | tail -1)
                  INPUT_TOKENS=${{INPUT_TOKENS:-0}}
                  OUTPUT_TOKENS=${{OUTPUT_TOKENS:-0}}
                  COST_USD=${{COST_USD:-0}}

                  if [ $PIPE_EXIT -eq 0 ]; then
                    PIPELINE_RESULT="SUCCESS"
                  fi

                  echo "=== Measure diff size ==="
                  AMAL_WORKDIR="/tmp/pipeline-workdir/{issue_id}"
                  if [ -d "$AMAL_WORKDIR/.git" ]; then
                    # Count lines changed by all commits the pipeline added on top of
                    # the initial state (first/root commit of the workdir = pre-fix baseline)
                    FIRST_COMMIT=$(cd "$AMAL_WORKDIR" && git rev-list --max-parents=0 HEAD 2>/dev/null | head -1)
                    if [ -n "$FIRST_COMMIT" ]; then
                      DIFF_LINES=$(cd "$AMAL_WORKDIR" && git diff "$FIRST_COMMIT" HEAD -- 2>/dev/null | grep -c "^[+-]" || echo 0)
                    else
                      DIFF_LINES=$(cd "$AMAL_WORKDIR" && git show HEAD -- 2>/dev/null | grep -c "^[+-]" || echo 0)
                    fi
                  else
                    DIFF_LINES=0
                  fi
                  echo "DIFF_LINES: $DIFF_LINES"

                  echo "=== Semantic equivalence (vs ground truth) ==="
                  cd /tmp/repo
                  git fetch --depth=1 origin {backport} 2>/dev/null || true
                  TRUTH_DIFF=$(git diff {pre_fix} {backport} -- 2>/dev/null | grep "^[+-]" | grep -v "^[+-][+-][+-]" || true)
                  if [ -d "$AMAL_WORKDIR/.git" ]; then
                    FIRST_COMMIT=$(cd "$AMAL_WORKDIR" && git rev-list --max-parents=0 HEAD 2>/dev/null | head -1)
                    AGENT_DIFF=$(cd "$AMAL_WORKDIR" && git diff "$FIRST_COMMIT" HEAD -- 2>/dev/null | grep "^[+-]" | grep -v "^[+-][+-][+-]" || true)
                  else
                    AGENT_DIFF=""
                  fi
                  if [ -n "$TRUTH_DIFF" ] && [ "$TRUTH_DIFF" = "$AGENT_DIFF" ]; then
                    SEM_EQ_RESULT="PASS"
                    SEM_EQ_REASON=""
                    echo "Semantic equivalence: PASS (exact match with ground truth)"
                  else
                    # Fallback: check Amalgamator's own gate if it declared equivalence
                    AMAL_GATE=$(echo "$PIPE_OUTPUT" | grep -oP 'semantic_equivalence=\K\w+' | tail -1 || true)
                    if [ "$AMAL_GATE" = "matched" ]; then
                      SEM_EQ_RESULT="PASS"
                      SEM_EQ_REASON="Amalgamator gate: matched"
                      echo "Semantic equivalence: PASS (Amalgamator gate)"
                    else
                      SEM_EQ_RESULT="FAIL"
                      T=$(echo "$TRUTH_DIFF" | wc -l || echo 0)
                      A=$(echo "$AGENT_DIFF" | wc -l || echo 0)
                      SEM_EQ_REASON="Patch differs from ground truth (truth=${{T}} lines, agent=${{A}} lines)"
                      echo "Semantic equivalence: FAIL — $SEM_EQ_REASON"
                    fi
                  fi

                  echo "=== Post-pipeline test ==="
                  echo "Command: {test_cmd}"
                  if [ -d "$AMAL_WORKDIR" ]; then
                    cd "$AMAL_WORKDIR"
                  else
                    cd /tmp/repo
                  fi
                  if {test_cmd}; then
                    TEST_RESULT="PASS"
                  else
                    TEST_RESULT="FAIL"
                  fi
                  APPLY_RESULT=$PIPELINE_RESULT
                  echo "PIPELINE: $PIPELINE_RESULT  TEST: $TEST_RESULT"
{json_bldr}
{cm_saver}
              resources:
                requests:
                  memory: "{res['memory']}"
                  cpu: "{res['cpu']}"
                limits:
                  memory: "{res['memory']}"
                  cpu: "{res['cpu']}"
    """)


# ═══════════════════════════════════════════════════════════════════════════
# Job launcher
# ═══════════════════════════════════════════════════════════════════════════

def oc_run(args):
    return subprocess.run(["oc"] + args, capture_output=True, text=True)

def launch_job(job_yaml: str, namespace: str) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(job_yaml)
        tmp = f.name
    job_name = [l.split("name:")[-1].strip() for l in job_yaml.splitlines() if "  name:" in l][0]
    oc_run(["delete", "job", job_name, "-n", namespace, "--ignore-not-found"])
    r = oc_run(["apply", "-n", namespace, "-f", tmp])
    os.unlink(tmp)
    return r.returncode == 0


# ═══════════════════════════════════════════════════════════════════════════
# Result collection
# ═══════════════════════════════════════════════════════════════════════════

def collect(cfg: dict, tool: str, out_dir: Path):
    ns        = cfg["openshift"]["namespace"]
    rslug_val = repo_slug(cfg)
    tool_short = "raw" if tool == "raw-claude" else "amal"
    cm_prefix  = f"result-{tool_short}-{rslug_val}"
    pod_prefix = f"{rslug_val}-{tool_short}-"

    results, seen = [], set()

    # 1. ConfigMaps (persist after pod GC)
    cms = oc_run(["get", "configmaps", "-n", ns, "--no-headers",
                  "-o", "custom-columns=NAME:.metadata.name"]).stdout.strip().splitlines()
    for cm in cms:
        cm = cm.strip()
        if not cm.startswith(cm_prefix + "-"):
            continue
        raw = oc_run(["get", "configmap", cm, "-n", ns,
                      "-o", "jsonpath={.data.result}"]).stdout.strip()
        try:
            data = json.loads(raw)
            data["source"] = "configmap"
            results.append(data)
            seen.add(data["slug"])
        except Exception:
            pass

    # 2. Fallback: pod logs (pods not yet GC'd)
    pods = oc_run(["get", "pods", "-n", ns, "--no-headers",
                   "-o", "custom-columns=NAME:.metadata.name"]).stdout.strip().splitlines()
    for pod in pods:
        pod = pod.strip()
        if not pod.startswith(pod_prefix):
            continue
        logs = oc_run(["logs", "-n", ns, pod]).stdout
        for line in logs.splitlines():
            if line.startswith("EVAL_RESULT: "):
                try:
                    data = json.loads(line[len("EVAL_RESULT: "):])
                    if data["slug"] not in seen:
                        data["source"] = "pod_log"
                        results.append(data)
                        seen.add(data["slug"])
                except Exception:
                    pass

    if not results:
        print(f"  No results found for {tool} (ConfigMap prefix: {cm_prefix}-*)")
        return

    # Write summary JSON (our format)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / f"{tool.replace('-', '_')}.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ {len(results)} results → {summary_path}\n")

    # Write individual RunResult-format files (Richard's leaderboard format)
    owner, repo_name = cfg["repo"].split("/", 1)
    for r in results:
        orig_short    = r.get("original_commit", r["slug"])[:8]
        back_short    = r.get("backport_commit", "unknown")[:8]
        tool_key      = r.get("tool_key", tool)
        fname         = f"{tool_key}__{owner}__{repo_name}__{orig_short}__{back_short}.json"
        run_result_path = out_dir / fname
        with open(run_result_path, "w") as f:
            json.dump(r, f, indent=2)

    print_scorecard(results, tool)


def print_scorecard(results: list[dict], tool: str):
    def row(label, subset):
        if not subset:
            return
        n = len(subset)
        # Support both old keys and new RunResult keys
        applied = sum(1 for r in subset if r.get("semantic_equivalence") == "PASS"
                      or r.get("apply") == "SUCCESS")
        passed  = sum(1 for r in subset if r.get("test_success") == "PASS"
                      or r.get("test") == "PASS")
        baseline_ok = sum(1 for r in subset if r.get("baseline_test") == "PASS")
        lat     = sum(r.get("time_seconds", r.get("latency_s", 0)) for r in subset) / n
        tok     = sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in subset) / n
        cost    = sum(r.get("cost_usd", 0) for r in subset) / n
        base_str = f"  Baseline: {baseline_ok}/{n}" if any(r.get("baseline_test") for r in subset) else ""
        cost_str = f"  ${cost:.3f}" if cost > 0 else ""
        print(f"  {label:8s}  {n:3d} cases"
              f"  Apply/Pipeline: {applied}/{n} ({100*applied//n}%)"
              f"  Test PASS: {passed}/{n} ({100*passed//n}%)"
              f"{base_str}"
              f"  Avg {lat:.0f}s  {tok:.0f} tok{cost_str}")

    print(f"  {'Difficulty':8s}  {'N':>3}  Apply/Pipeline / Test Pass / Baseline / Latency / Tokens")
    print("  " + "─" * 80)
    for diff in ["Easy", "Medium", "Hard"]:
        row(diff, [r for r in results if r.get("classification", r.get("difficulty")) == diff])
    print("  " + "─" * 80)
    row("TOTAL", results)


# ═══════════════════════════════════════════════════════════════════════════
# Push results to leaderboard pod
# ═══════════════════════════════════════════════════════════════════════════

def push_results(cfg: dict, results_dir: Path):
    ns = cfg["openshift"]["namespace"]
    pods = oc_run(["get", "pods", "-n", ns, "-l", "app=backport-leaderboard",
                   "--no-headers", "-o", "custom-columns=NAME:.metadata.name"]).stdout.strip()
    if not pods:
        print("ERROR: No leaderboard pod found.")
        print("Deploy with: oc apply -f infra/leaderboard/leaderboard.yaml")
        return

    pod = pods.splitlines()[0].strip()
    print(f"Pushing {results_dir} → {pod}:/results/ …")
    r = subprocess.run(["oc", "cp", str(results_dir), f"{pod}:/results/", "-n", ns])
    if r.returncode == 0:
        print(f"✓ Results pushed. Open the leaderboard Route to see updated scores.")
        # Trigger aggregation in the pod
        subprocess.run(["oc", "exec", pod, "-n", ns, "--",
                        "python3", "-c",
                        "import sys; sys.path.insert(0,'/app'); "
                        "from backport_bench.results import aggregate_results; "
                        "from pathlib import Path; aggregate_results(Path('/results'))"])
        print("✓ Aggregation complete.")
    else:
        print("✗ Push failed. Check oc cp permissions.")


# ═══════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="Backport Agent Leaderboard — OpenShift runner")
    p.add_argument("--config",        required=True, help="Path to evals/<repo>/config.yaml")
    p.add_argument("--tool",          choices=["raw-claude", "amalgamator"],
                   help="Which tool to run (default: all enabled in config)")
    p.add_argument("--collect",       action="store_true",
                   help="Collect results from ConfigMaps/pod-logs → local JSON")
    p.add_argument("--push-results",  action="store_true",
                   help="Push collected results to the leaderboard pod (needs leaderboard deployed)")
    p.add_argument("--classification", choices=["Easy", "Medium", "Hard"],
                   help="Override dataset classification filter")
    p.add_argument("--limit",         type=int, help="Override dataset limit (random sample)")
    args = p.parse_args()

    cfg = load_config(args.config)

    # Resolve local repo clone path for git metadata
    global LOCAL_REPO
    if cfg.get("local_clone"):
        LOCAL_REPO = Path(cfg["local_clone"]).expanduser().resolve()
    else:
        repo_name  = cfg["repo"].split("/")[-1]
        LOCAL_REPO = (REPO_ROOT.parent / "benchmark-repos" / repo_name).resolve()

    if args.classification:
        cfg["dataset"]["classification"] = args.classification
    if args.limit:
        cfg["dataset"]["limit"] = args.limit

    ns = cfg["openshift"]["namespace"]
    rslug_val = repo_slug(cfg)
    results_dir = REPO_ROOT / "results" / rslug_val

    # ── Push results mode ──────────────────────────────────────────────────
    if args.push_results:
        push_results(cfg, results_dir)
        return

    # ── Collect mode ──────────────────────────────────────────────────────
    if args.collect:
        tools = [args.tool] if args.tool else [t for t, v in cfg["tools"].items() if v.get("enabled")]
        for tool in tools:
            print(f"\n{'='*60}\n  Collecting {tool} results\n{'='*60}")
            collect(cfg, tool, results_dir)
        return

    # ── Launch mode ───────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Preparing cases for {cfg['repo']}")
    print(f"{'='*60}\n")

    raw_cases = load_cases(cfg)
    cases     = prepare_cases(raw_cases, cfg)
    print(f"\n✓ {len(cases)} cases prepared\n")

    tools = [args.tool] if args.tool else [t for t, v in cfg["tools"].items() if v.get("enabled")]

    for tool in tools:
        if tool not in cfg["tools"] or not cfg["tools"][tool].get("enabled"):
            print(f"[SKIP] {tool} is disabled in config")
            continue

        print(f"\n{'='*60}")
        print(f"  Launching {tool} jobs ({len(cases)} cases)")
        print(f"{'='*60}")

        launched = 0
        for i, case in enumerate(cases):
            if not case.get("test_cmd"):
                print(f"  [{i+1:2d}/{len(cases)}] {case['slug']} — SKIP (no test command)")
                continue

            print(f"  [{i+1:2d}/{len(cases)}] {case['slug']} ({case['classification']}) … ",
                  end="", flush=True)
            build_fn = build_raw_claude_job if tool == "raw-claude" else build_amalgamator_job
            job_yaml = build_fn(case, cfg)

            if launch_job(job_yaml, ns):
                launched += 1
                print("✓")
            else:
                print("✗")

        print(f"\n  {launched}/{len(cases)} {tool} jobs launched")
        raw_or_amal = "raw" if tool == "raw-claude" else "amal"
        print(f"  Monitor: oc get pods -n {ns} | grep {rslug_val}-{raw_or_amal}")

    print(f"\n  Collect when done: python3 run.py --config {args.config} --collect\n")


if __name__ == "__main__":
    main()
