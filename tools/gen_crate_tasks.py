#!/usr/bin/env python3
"""Generate Harbor tasks for the crate/crate rows of backports.csv.

Per row:  original fix commit (on main)  ->  human backport commit (on a release branch).
  target  = backport^   (the exact pre-backport state of the release branch)
  golden  = diff backport^..backport   (the real human backport)
  source  = original fix commit

Leak-proofing: the container does NOT clone the full repo. It fetches only the
original commit and the target commit (shallow), by SHA, so the human backport
commit -- a child of target -- is not in the container's object store.

Usage: gen_crate_tasks.py [--repo PATH] [--csv PATH] [--out DIR] [--only SHA8]
"""
import argparse, csv, re, subprocess, textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = ROOT.parent / "benchmark-repos" / "crate"
DEFAULT_CSV = ROOT.parent / "backport-agent-leaderboard" / "backports.csv"

DIFFICULTY = {"Easy": "easy", "Medium": "medium", "Hard": "hard"}


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True,
                          capture_output=True, text=True).stdout


def slugify(subject):
    words = re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-").split("-")
    words = words[:6]
    while words and words[-1] in {"of", "the", "in", "on", "to", "a", "an", "for", "and", "from", "with"}:
        words.pop()
    return "-".join(words)


DOCKERFILE = """\
FROM eclipse-temurin:25-jdk

WORKDIR /workspace

COPY case.yaml /workspace

# yq parses case.yaml; python3+pip3 are for the harbor adapter's amalgamator install.
RUN apt-get update && apt-get install -y --no-install-recommends \\
      git curl ca-certificates yq python3 python3-pip \\
    && rm -rf /var/lib/apt/lists/*

RUN git config --global user.email "amalgamator-bench@redhat.com" && \\
    git config --global user.name "Amalgamator Bench"

ENV MAVEN_OPTS="-Xmx4g"

# Container-environment fixes so the UNMODIFIED, FULL suite is green at baseline:
#  * NativesTest.test_runningAsRoot asserts the JVM is NOT root -> build and test
#    as an unprivileged user via crate-mvn (root keeps orchestrating git/amalgamator).
#  * NodeStatsITest.testSysNodesCgroup needs cgroup-v1 cpuacct data; Docker
#    runs cgroup v2 (/proc/self/cgroup = "0::/"). The test's own escape hatch for
#    such CI environments is SHIPPABLE=true, set in crate-mvn below.
# Neither test is excluded or edited; everything else runs.
RUN useradd -m -s /bin/bash builder && \\
    git config --global --add safe.directory '*' && \\
    printf '%s\\n' '#!/bin/bash' 'set -e' \\
      'chown -R builder:builder "$PWD" /workspace/crate/.git 2>/dev/null || true' \\
      'exec runuser -u builder -- env HOME=/home/builder SHIPPABLE=true MAVEN_OPTS="$MAVEN_OPTS" ./mvnw -B -ntp "$@"' \\
      > /usr/local/bin/crate-mvn && chmod +x /usr/local/bin/crate-mvn

# Shallow, by-SHA fetch of only the two commits this case needs. The human
# backport ({backport8}) is a child of target and is never fetched, so it is
# not discoverable in the container (no `git log --all`, no remote to fetch from).
#   source = {orig8}   original fix on main
#   target = {parent8}   pre-backport tip of the release branch ({backport8}^)
RUN git init -q /workspace/crate && cd /workspace/crate && \\
    git remote add origin https://github.com/crate/crate.git && \\
    git fetch -q --depth=50 origin {orig} && git branch source FETCH_HEAD && \\
    git fetch -q --depth=50 origin {parent} && git branch target FETCH_HEAD && \\
    git checkout -q target && \\
    git remote remove origin

# Warm the Maven cache for the target tree so the agent/verifier do not pay
# for dependency downloads (offline-safe resolution + test compilation).
RUN cd /workspace/crate && crate-mvn -q test-compile

RUN mkdir /workspace/workdir
"""

CASE = """\
issue_id: "{slug}"
bug_description: >
  Backport the fix "{subject}" (commit {orig8}, branch 'source') onto branch
  'target' so that the project builds and its complete test suite passes.

repository:
  source_path: /workspace/crate
  workdir: /workspace/workdir

branches:
  source: source
  target: target

fix:
  commit: "{orig}"

build:
  # Whole-project compile including all test sources (fast structural gate).
  command: "crate-mvn test-compile"
  # Full unit-test suite across every module (the pass/fail gate).
  test_command: "crate-mvn test"

model: "openai/your-model-here"
api_base: "https://your-endpoint.com/v1"

advanced:
  context_length: 200000
  command_timeout: 3600
  max_build_test_retries: 4
"""

TASK_TOML = """\
schema_version = "1.3"
artifacts = ["/workspace/workdir", "/workspace/amalgamator/runs", "/workspace/case.yaml"]

[task]
name = "redhat-et/{slug}"
authors = [{{ name = "Surya Prakash Pathak", email = "supathak@redhat.com" }}]

[metadata]
difficulty = "{difficulty}"
difficulty_explanation = \"\"\"
{difficulty_cap} crate/crate backport ({reason}).
Original fix {orig8} on main -> human backport {backport8}. Golden = the real
human backport diff. Verification = full test-compile + full `./mvnw test`.
\"\"\"
category = "programming"

[verifier]
timeout_sec = 18000.0

[agent]
timeout_sec = 18000.0

[environment]
network_mode = "public"
build_timeout_sec = 3600.0
"""

SOLVE = """\
#!/bin/bash
# Oracle: apply the real human backport (golden.patch = diff backport^..backport)
# to a fresh worktree at target, exactly where Amalgamator would build its own.
set -e

case_file="/workspace/case.yaml"
source_path=$(yq -r '.repository.source_path' "$case_file")
workdir=$(yq -r '.repository.workdir' "$case_file")
issue_id=$(yq -r '.issue_id' "$case_file")
target_branch=$(yq -r '.branches.target' "$case_file")

sanitized_target=$(echo "$target_branch" | sed -e 's#^origin/##' -e 's#/#_#g')
repo_dir="$workdir/${issue_id}_${sanitized_target}"

mkdir -p "$workdir"
cd "$source_path"
git worktree add -b "amalgamator-oracle-${sanitized_target}" "$repo_dir" "$target_branch"

cd "$repo_dir"
git apply /solution/golden.patch
git add -A
git commit -q -m "Oracle: human backport {backport8}"
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(DEFAULT_REPO))
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--out", default=str(ROOT / "dataset"))
    ap.add_argument("--only")
    a = ap.parse_args()

    template_test = (ROOT / "dataset" / "django-password-reset-fix" / "tests" / "test.sh").read_text()
    rows = [r for r in csv.DictReader(open(a.csv)) if r["repo"] == "crate/crate"]
    for r in rows:
        orig, back = r["Original Commit"], r["Backport Commit"]
        if a.only and not orig.startswith(a.only):
            continue
        parent = git(a.repo, "rev-parse", back + "^").strip()
        subject = git(a.repo, "log", "-1", "--format=%s", orig).strip()
        slug = "crate-" + slugify(subject)
        d = Path(a.out) / slug
        (d / "environment").mkdir(parents=True, exist_ok=True)
        (d / "solution").mkdir(exist_ok=True)
        (d / "tests").mkdir(exist_ok=True)
        f = dict(slug=slug, subject=subject.replace('"', "'"), orig=orig, orig8=orig[:8],
                 backport8=back[:8], parent=parent, parent8=parent[:8],
                 difficulty=DIFFICULTY[r["Classification"]],
                 difficulty_cap=r["Classification"], reason=r["Reason"])
        (d / "environment" / "Dockerfile").write_text(DOCKERFILE.format(**f))
        (d / "environment" / "case.yaml").write_text(CASE.format(**f))
        (d / "task.toml").write_text(TASK_TOML.format(**f))
        (d / "instruction.md").write_text(
            CASE.split("bug_description: >\n")[1].split("\nrepository:")[0].format(**f).replace("\n  ", " ").strip() + "\n")
        (d / "solution" / "solve.sh").write_text(SOLVE.replace("{backport8}", f["backport8"]))
        (d / "solution" / "solve.sh").chmod(0o755)
        patch = git(a.repo, "diff", "--binary", parent, back)
        (d / "solution" / "golden.patch").write_text(patch)
        (d / "tests" / "test.sh").write_text(template_test)
        (d / "tests" / "test.sh").chmod(0o755)
        print(f"{slug:55s} {r['Classification']:6s} target={parent[:8]} golden={len(patch.splitlines())} lines")


if __name__ == "__main__":
    main()
