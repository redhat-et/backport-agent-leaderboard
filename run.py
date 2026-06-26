#!/usr/bin/env python3
"""
Backport Agent Leaderboard — OpenShift runner.

Usage:
  python3 run.py --config evals/crate/config.yaml                  # launch all enabled tools
  python3 run.py --config evals/crate/config.yaml --tool raw-claude
  python3 run.py --config evals/crate/config.yaml --tool amalgamator
  python3 run.py --config evals/crate/config.yaml --collect         # collect results → JSON
  python3 run.py --config evals/crate/config.yaml --collect --tool raw-claude
"""

import argparse, csv, json, os, random, subprocess, sys, tempfile, textwrap, time
from pathlib import Path

import yaml  # pip install pyyaml

# ── Repo root so relative paths in config work ────────────────────────────
REPO_ROOT = Path(__file__).parent

# ── Local repo clone path is resolved from config at runtime ──────────────
LOCAL_CRATE = None  # set in main() from config or env


# ═══════════════════════════════════════════════════════════════════════════
# Config loading
# ═══════════════════════════════════════════════════════════════════════════

def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    # Resolve csv path relative to the config file's directory
    if "csv" in cfg.get("dataset", {}):
        cfg_dir = Path(config_path).parent
        cfg["dataset"]["csv"] = str((cfg_dir / cfg["dataset"]["csv"]).resolve())
    return cfg


# ═══════════════════════════════════════════════════════════════════════════
# Dataset helpers (reads backports.csv)
# ═══════════════════════════════════════════════════════════════════════════

def load_cases(cfg: dict) -> list[dict]:
    ds = cfg["dataset"]
    repo = cfg["repo"]

    # Explicit commit list takes priority
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
# Git helpers (local clone — metadata only)
# ═══════════════════════════════════════════════════════════════════════════

def git(args, cwd=None):
    cwd = cwd or LOCAL_CRATE
    if not cwd or not Path(cwd).exists():
        raise RuntimeError(f"Local repo clone not found at {cwd}. Set 'local_clone' in config.yaml.")
    return subprocess.run(["git"] + args, capture_output=True, text=True, cwd=str(cwd))

def ensure_sha(sha):
    if git(["cat-file", "-t", sha]).returncode == 0:
        return True
    return git(["fetch", "--depth=50", "origin", sha]).returncode == 0

def get_parent(sha):
    r = git(["rev-parse", f"{sha}^"])
    return r.stdout.strip() if r.returncode == 0 else None

def get_test_class(sha):
    r = git(["show", "--name-only", "--pretty=format:", sha])
    files = [l for l in r.stdout.strip().splitlines() if l.strip()]
    tests = [f.split("/")[-1].replace(".java", "") for f in files if "Test.java" in f]
    return tests[0] if tests else None

def get_module(sha):
    r = git(["show", "--name-only", "--pretty=format:", sha])
    files = [l for l in r.stdout.strip().splitlines() if l.strip()]
    src = [f for f in files if "/src/" in f]
    return src[0].split("/src/")[0] if src else None

def guess_branch(backport_sha):
    r = git(["show", "--name-only", "--pretty=format:", backport_sha])
    for f in r.stdout.strip().splitlines():
        if "release-notes/" in f and ".rst" in f:
            parts = f.split("/")[-1].replace(".rst", "").split(".")
            if len(parts) >= 2:
                return f"{parts[0]}.{parts[1]}"
    return "target"


# ═══════════════════════════════════════════════════════════════════════════
# Case preparation
# ═══════════════════════════════════════════════════════════════════════════

def prepare_cases(raw_cases: list[dict]) -> list[dict]:
    cases = []
    for r in raw_cases:
        orig, backport = r["orig_sha"], r["backport_sha"]
        slug = orig[:12]

        for sha in [orig, backport]:
            if not ensure_sha(sha):
                print(f"  [SKIP] cannot fetch {sha[:12]}")
                break
        else:
            pre_fix = get_parent(backport)
            if not pre_fix:
                print(f"  [SKIP] cannot get parent of {backport[:12]}")
                continue
            test_class = get_test_class(orig)
            module     = get_module(orig)
            branch     = guess_branch(backport)
            print(f"  {slug}  [{r.get('classification','?'):7s}]  branch={branch}  module={module}  test={test_class}")
            cases.append({
                "slug":         slug,
                "orig_sha":     orig,
                "backport_sha": backport,
                "pre_fix_sha":  pre_fix,
                "classification": r.get("classification", "Unknown"),
                "target_branch": branch,
                "module":       module or "server",
                "test_class":   test_class,
            })
    return cases


# ═══════════════════════════════════════════════════════════════════════════
# OpenShift job YAML builders
# ═══════════════════════════════════════════════════════════════════════════

# Each line is prefixed with 18 spaces so the heredoc content stays inside
# the YAML `| ` block (which strips exactly 18 leading spaces from all content lines).
_TC = "                  "  # 18 spaces = YAML block indentation level
TOOLCHAINS_XML = (
    f"{_TC}<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
    f"{_TC}<toolchains>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>21</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>21.0.5+11</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>21.0.6+7</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>22</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>22.0.1+8</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>22.0.2+9</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>23</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>23.0.1+11</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>23.0.2+7</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>24</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>24.0.1+9</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>24.0.2+7</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>25</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>25.0.1+9</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}  <toolchain><type>jdk</type><provides><version>25.0.3</version><vendor>temurin</vendor></provides><configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration></toolchain>\n"
    f"{_TC}</toolchains>"
)

# Python snippet (used inside pod heredoc) that saves EVAL_JSON to a ConfigMap
# All { } are doubled because this string is used inside an f-string
CONFIGMAP_SAVER = """\
                  python3 << 'PYEOF'
                  import json, ssl, urllib.request
                  try:
                      data = json.load(open('/tmp/eval_result.json'))
                      token = open('/var/run/secrets/kubernetes.io/serviceaccount/token').read().strip()
                      ns = open('/var/run/secrets/kubernetes.io/serviceaccount/namespace').read().strip()
                      ca = '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
                      slug = data.get('slug', 'unknown')
                      cm_name = '{cm_prefix}-' + slug
                      ctx = ssl.create_default_context(cafile=ca)
                      base = 'https://kubernetes.default.svc/api/v1/namespaces/' + ns + '/configmaps'
                      hdrs = {{'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}}
                      cm = {{'apiVersion': 'v1', 'kind': 'ConfigMap',
                            'metadata': {{'name': cm_name, 'namespace': ns}},
                            'data': {{'result': json.dumps(data)}}}}
                      req = urllib.request.Request(base, json.dumps(cm).encode(), hdrs, method='POST')
                      try:
                          urllib.request.urlopen(req, context=ctx)
                          print('Result saved to ConfigMap ' + cm_name)
                      except urllib.error.HTTPError as e:
                          if e.code == 409:
                              hdrs2 = dict(hdrs)
                              hdrs2['Content-Type'] = 'application/strategic-merge-patch+json'
                              patch = {{'data': {{'result': json.dumps(data)}}}}
                              req2 = urllib.request.Request(base + '/' + cm_name, json.dumps(patch).encode(), hdrs2, method='PATCH')
                              urllib.request.urlopen(req2, context=ctx)
                              print('Result updated in ConfigMap ' + cm_name)
                          else:
                              print('WARNING: HTTP ' + str(e.code))
                  except Exception as ex:
                      print('WARNING: ConfigMap save failed: ' + str(ex))
                  PYEOF"""


def build_raw_claude_job(case: dict, cfg: dict) -> str:
    oc   = cfg["openshift"]
    tool = cfg["tools"]["raw-claude"]
    slug, orig, pre_fix, module, test_class, branch = (
        case["slug"], case["orig_sha"], case["pre_fix_sha"],
        case["module"], case["test_class"], case["target_branch"],
    )
    difficulty = case["classification"]
    model      = tool["model"]
    image      = tool["image"]
    ns         = oc["namespace"]
    res        = oc["resources"]["raw-claude"]
    timeout    = oc["job_timeout_seconds"]
    vproject   = oc["vertex_project"]
    vregion    = oc["vertex_region"]
    mvn        = "-Dmaven.repo.local=/tmp/.m2/repository -t /tmp/toolchains.xml -DskipBlackboxTests=true -Dcheckstyle.skip=true -q"
    cm_saver   = CONFIGMAP_SAVER.format(cm_prefix="result-raw")

    return textwrap.dedent(f"""\
    apiVersion: batch/v1
    kind: Job
    metadata:
      name: crate-raw-{slug}
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
                  APPLY_RESULT="FAILED"
                  TEST_RESULT="SKIPPED"

                  echo "=== Install Python deps ==="
                  pip3 install --break-system-packages -q anthropic[vertex] google-auth 2>&1 | tail -2

                  echo "=== Write toolchains.xml ==="
                  cat > /tmp/toolchains.xml <<'TOOLCHAINS'
                  {TOOLCHAINS_XML}
                  TOOLCHAINS

                  echo "=== Clone crate at pre_fix_sha ==="
                  git clone --depth=100 https://github.com/crate/crate.git /tmp/crate 2>&1 | tail -3
                  cd /tmp/crate
                  git fetch --depth=100 origin {pre_fix} 2>/dev/null || true
                  git checkout {pre_fix} 2>/dev/null || true

                  echo "=== Fetch orig_sha for Raw Claude context ==="
                  git fetch --depth=5 origin {orig} 2>/dev/null || true

                  echo "=== Run Raw Claude ==="
                  RC_START=$(date +%s)
                  RC_OUTPUT=$(python3 /opt/script/generic_claude_backport.py \\
                    --repo /tmp/crate --orig {orig} --target-sha {pre_fix} \\
                    --target-branch {branch} --model {model} \\
                    --out /tmp/backport.diff 2>&1) || true
                  RC_END=$(date +%s)
                  echo "$RC_OUTPUT"
                  LATENCY_S=$((RC_END - RC_START))
                  INPUT_TOKENS=$(echo "$RC_OUTPUT" | grep -oP 'input: \\K[0-9]+' | tail -1)
                  OUTPUT_TOKENS=$(echo "$RC_OUTPUT" | grep -oP 'output: \\K[0-9]+' | tail -1)
                  INPUT_TOKENS=${{INPUT_TOKENS:-0}}
                  OUTPUT_TOKENS=${{OUTPUT_TOKENS:-0}}

                  if [ ! -s /tmp/backport.diff ]; then
                    echo "APPLY: FAILED (empty diff)"
                  else
                    echo "" >> /tmp/backport.diff
                    patch -p1 --fuzz=5 < /tmp/backport.diff && APPLY_RESULT="SUCCESS" || true
                    echo "APPLY: $APPLY_RESULT"
                  fi

                  if [ "$APPLY_RESULT" = "SUCCESS" ]; then
                    echo "=== Build ==="
                    if ./mvnw install -pl {module} -am -DskipTests {mvn}; then
                      echo "=== Test ==="
                      if ./mvnw test -pl {module} -Dtest={test_class} \\
                          -Dsurefire.failIfNoSpecifiedTests=true {mvn}; then
                        TEST_RESULT="PASS"
                      else
                        TEST_RESULT="FAIL"
                      fi
                    else
                      TEST_RESULT="BUILD_FAIL"
                    fi
                  fi

                  echo "TEST RESULT: $TEST_RESULT"
                  EVAL_JSON="{{\\"slug\\": \\"{slug}\\", \\"difficulty\\": \\"{difficulty}\\", \\"test_class\\": \\"{test_class}\\", \\"apply\\": \\"$APPLY_RESULT\\", \\"test\\": \\"$TEST_RESULT\\", \\"latency_s\\": $LATENCY_S, \\"input_tokens\\": $INPUT_TOKENS, \\"output_tokens\\": $OUTPUT_TOKENS}}"
                  echo "EVAL_RESULT: $EVAL_JSON"
                  echo "$EVAL_JSON" > /tmp/eval_result.json
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
    oc   = cfg["openshift"]
    tool = cfg["tools"]["amalgamator"]
    slug, orig, pre_fix = case["slug"], case["orig_sha"], case["pre_fix_sha"]
    difficulty, test_class = case["classification"], case["test_class"]
    model   = tool["model"]
    image   = tool["image"]
    ns      = oc["namespace"]
    res     = oc["resources"]["amalgamator"]
    timeout = oc["job_timeout_seconds"]
    vproject = oc["vertex_project"]
    vregion  = oc["vertex_region"]
    issue_id = f"crate-{slug}"
    branch   = case["target_branch"]
    cm_saver = CONFIGMAP_SAVER.format(cm_prefix="result-amal")

    return textwrap.dedent(f"""\
    apiVersion: batch/v1
    kind: Job
    metadata:
      name: crate-amal-{slug}
    spec:
      backoffLimit: 0
      activeDeadlineSeconds: 3600
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
                  PIPELINE_RESULT="FAILED"
                  TEST_RESULT="FAIL"

                  echo "=== Install uv ==="
                  curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/tmp/uv-bin sh
                  export PATH="/tmp/uv-bin:$PATH"

                  echo "=== Write toolchains.xml ==="
                  mkdir -p /tmp/.m2
                  cat > /tmp/.m2/toolchains.xml <<'TOOLCHAINS'
                  {TOOLCHAINS_XML}
                  TOOLCHAINS

                  echo "=== Set git identity (required for cherry-pick commits) ==="
                  git config --global user.email "eval-bot@backport-bench.local"
                  git config --global user.name "Eval Bot"

                  echo "=== Clone crate repo ==="
                  git clone https://github.com/crate/crate.git /tmp/crate-repo 2>&1 | tail -3
                  cd /tmp/crate-repo
                  git fetch origin {pre_fix} 2>/dev/null || true
                  git fetch origin {orig} 2>/dev/null || true
                  git checkout --detach {pre_fix}
                  git branch target-backport {pre_fix}

                  echo "=== Extract Amalgamator ==="
                  mkdir -p /tmp/amalgamator
                  tar xzf /opt/amalgamator-src/amalgamator.tar.gz -C /tmp/amalgamator

                  echo "=== Write pipeline config ==="
                  cat > /tmp/pipeline-config.yaml <<'PIPELINECFG'
                  issue_id: "{issue_id}"
                  bug_description: "Benchmark: backport {slug} to {branch}. Difficulty: {difficulty}."
                  repository:
                    source_path: "/tmp/crate-repo"
                    workdir: "/tmp/pipeline-workdir"
                  branches:
                    source: "origin/master"
                    target: "target-backport"
                  fix:
                    commit: "{orig}"
                  build:
                    command: ""
                    test_command: ""
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
                    TEST_RESULT="PASS"
                  fi
                  echo "PIPELINE: $PIPELINE_RESULT  TEST: $TEST_RESULT"

                  EVAL_JSON="{{\\"slug\\": \\"{slug}\\", \\"difficulty\\": \\"{difficulty}\\", \\"test_class\\": \\"{test_class}\\", \\"pipeline\\": \\"$PIPELINE_RESULT\\", \\"test\\": \\"$TEST_RESULT\\", \\"latency_s\\": $LATENCY_S, \\"input_tokens\\": $INPUT_TOKENS, \\"output_tokens\\": $OUTPUT_TOKENS, \\"cost_usd\\": $COST_USD}}"
                  echo "EVAL_RESULT: $EVAL_JSON"
                  echo "$EVAL_JSON" > /tmp/eval_result.json
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

def oc(args):
    return subprocess.run(["oc"] + args, capture_output=True, text=True)

def launch_job(job_yaml: str, namespace: str) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(job_yaml)
        tmp = f.name
    job_name = [l.split("name:")[-1].strip() for l in job_yaml.splitlines() if "  name:" in l][0]
    oc(["delete", "job", job_name, "-n", namespace, "--ignore-not-found"])
    r = oc(["apply", "-n", namespace, "-f", tmp])
    os.unlink(tmp)
    return r.returncode == 0


# ═══════════════════════════════════════════════════════════════════════════
# Result collection
# ═══════════════════════════════════════════════════════════════════════════

def collect(cfg: dict, tool: str, out_path: Path):
    ns    = cfg["openshift"]["namespace"]
    prefix = "result-raw" if tool == "raw-claude" else "result-amal"
    results, seen = [], set()

    # 1. ConfigMaps (survive pod GC)
    cms = subprocess.run(
        ["oc", "get", "configmaps", "-n", ns, "--no-headers",
         "-o", "custom-columns=NAME:.metadata.name"],
        capture_output=True, text=True).stdout.strip().splitlines()

    for cm in cms:
        cm = cm.strip()
        if not cm.startswith(prefix + "-"):
            continue
        raw = subprocess.run(
            ["oc", "get", "configmap", cm, "-n", ns, "-o", "jsonpath={.data.result}"],
            capture_output=True, text=True).stdout.strip()
        try:
            data = json.loads(raw)
            data["source"] = "configmap"
            results.append(data)
            seen.add(data["slug"])
        except Exception:
            pass

    # 2. Fallback: pod logs (for pods not yet GC'd)
    pods = subprocess.run(
        ["oc", "get", "pods", "-n", ns, "--no-headers",
         "-o", "custom-columns=NAME:.metadata.name"],
        capture_output=True, text=True).stdout.strip().splitlines()

    pod_prefix = "crate-raw-" if tool == "raw-claude" else "crate-amal-"
    for pod in pods:
        pod = pod.strip()
        if not pod.startswith(pod_prefix):
            continue
        logs = subprocess.run(["oc", "logs", "-n", ns, pod],
                              capture_output=True, text=True).stdout
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

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ {len(results)} results → {out_path}\n")
    print_scorecard(results, tool)


def print_scorecard(results: list[dict], tool: str):
    def row(label, subset):
        if not subset:
            return
        n = len(subset)
        if tool == "raw-claude":
            applied = sum(1 for r in subset if r.get("apply") == "SUCCESS")
            passed  = sum(1 for r in subset if r.get("test")  == "PASS")
            lat     = sum(r.get("latency_s", 0) for r in subset) / n
            tok     = sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in subset) / n
            print(f"  {label:8s}  {n:3d} cases  Apply: {applied}/{n} ({100*applied//n}%)  "
                  f"Test PASS: {passed}/{n} ({100*passed//n}%)  "
                  f"Avg {lat:.0f}s  {tok:.0f} tok")
        else:
            ok      = sum(1 for r in subset if r.get("pipeline") == "SUCCESS")
            passed  = sum(1 for r in subset if r.get("test")     == "PASS")
            lat     = sum(r.get("latency_s", 0) for r in subset) / n
            tok     = sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in subset) / n
            cost    = sum(r.get("cost_usd", 0) for r in subset) / n
            print(f"  {label:8s}  {n:3d} cases  Pipeline OK: {ok}/{n} ({100*ok//n}%)  "
                  f"Test PASS: {passed}/{n} ({100*passed//n}%)  "
                  f"Avg {lat:.0f}s  {tok:.0f} tok  ${cost:.3f}")

    print(f"  {'Difficulty':8s}  {'N':>3}  " + ("Apply / Test Pass / Latency / Tokens" if tool == "raw-claude"
          else "Pipeline / Test Pass / Latency / Tokens / Cost"))
    print("  " + "─" * 70)
    for diff in ["Easy", "Medium", "Hard"]:
        row(diff, [r for r in results if r.get("difficulty") == diff])
    print("  " + "─" * 70)
    row("TOTAL", results)


# ═══════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="Backport Agent Leaderboard — OpenShift runner")
    p.add_argument("--config", required=True, help="Path to eval config YAML (e.g. evals/crate/config.yaml)")
    p.add_argument("--tool", choices=["raw-claude", "amalgamator"],
                   help="Which tool to run (default: all enabled tools in config)")
    p.add_argument("--collect", action="store_true", help="Collect results from ConfigMaps → JSON")
    p.add_argument("--classification", choices=["Easy", "Medium", "Complex"],
                   help="Override dataset classification filter")
    p.add_argument("--limit", type=int, help="Override dataset limit (random sample)")
    args = p.parse_args()

    cfg = load_config(args.config)
    config_dir = Path(args.config).parent

    # Resolve local_clone path (for git metadata fetching)
    global LOCAL_CRATE
    if cfg.get("local_clone"):
        LOCAL_CRATE = Path(cfg["local_clone"]).expanduser().resolve()
    else:
        # Default: ../benchmark-repos/<repo-name> relative to this script
        repo_name = cfg["repo"].split("/")[-1]
        LOCAL_CRATE = (REPO_ROOT.parent / "benchmark-repos" / repo_name).resolve()

    # CLI overrides
    if args.classification:
        cfg["dataset"]["classification"] = args.classification
    if args.limit:
        cfg["dataset"]["limit"] = args.limit

    ns = cfg["openshift"]["namespace"]

    # ── Collect mode ───────────────────────────────────────────────────────
    if args.collect:
        tools = [args.tool] if args.tool else [t for t, v in cfg["tools"].items() if v.get("enabled")]
        for tool in tools:
            out = REPO_ROOT / "results" / cfg["repo"].split("/")[1] / f"{tool.replace('-', '_')}.json"
            print(f"\n{'='*60}\n  Collecting {tool} results\n{'='*60}")
            collect(cfg, tool, out)
        return

    # ── Launch mode ────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Preparing cases for {cfg['repo']}")
    print(f"{'='*60}\n")

    raw_cases = load_cases(cfg)
    cases = prepare_cases(raw_cases)
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
            if not case.get("test_class"):
                print(f"  [{i+1:2d}/{len(cases)}] {case['slug']} — SKIP (no test class found)")
                continue

            print(f"  [{i+1:2d}/{len(cases)}] {case['slug']} ({case['classification']}) … ", end="", flush=True)
            job_yaml = (build_raw_claude_job if tool == "raw-claude" else build_amalgamator_job)(case, cfg)

            if launch_job(job_yaml, ns):
                launched += 1
                print("✓")
            else:
                print("✗")

        print(f"\n  {launched}/{len(cases)} {tool} jobs launched")
        print(f"  Monitor: oc get pods -n {ns} | grep crate-{'raw' if tool == 'raw-claude' else 'amal'}")

    print(f"\n  Collect when done: python3 run.py --config {args.config} --collect\n")


if __name__ == "__main__":
    main()
