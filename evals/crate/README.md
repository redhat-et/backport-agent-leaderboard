# crate/crate — Backport Evaluation

> **This is the reference implementation.** It is intentionally written as a worked
> example for `crate/crate` (Java/Maven) so you can follow the same steps for any
> other repo. To add a new repo, the only things that change are the `Containerfile`
> base image (to match the language/toolchain), the `build_command` and `test_command`
> in `config.yaml`, and the image registry path. Everything else — the runner, the
> OpenShift infra, and the result collection — stays the same. See the
> [Adding a new repo](#adding-a-new-repo) section at the bottom for the exact steps.

This directory contains everything needed to evaluate automated backporting tools
against the `crate/crate` benchmark. It is self-contained: one config file drives
the whole run.

---

## What this evaluation measures

A backport takes a bug fix that was merged on the main branch and applies it to an
older release branch. The process sounds mechanical but often requires adapting the
diff to match different APIs, file structures, or context lines.

For each case in the dataset we:

1. Check out the repo at the commit **just before** the known-good backport was applied
2. Ask the tool to generate a backport diff
3. Apply the diff with `patch -p1`
4. Build the affected Maven module
5. Run the specific test that was changed in the original fix

This gives us two concrete, objective signals per case:

| Metric | What it means |
|--------|---------------|
| **Apply Rate** | Did the diff apply cleanly? (`patch` exit 0) |
| **Test Pass Rate** | Did the targeted test pass after applying? (`mvnw test` exit 0) |
| **Latency** | How long did the tool take? (wall-clock seconds) |
| **Input / Output Tokens** | How much context did the tool consume / produce? |
| **Cost (USD)** | API cost reported by the tool (Amalgamator only) |

The test class is **auto-detected** from the original fix commit: whichever `*Test.java`
file was modified in that commit is the test we run. This keeps the signal directly
tied to the fix, not a hand-picked suite.

---

## Tools evaluated

| Key | Type | How it works |
|-----|------|--------------|
| `raw-claude` | Single-shot LLM | One API call with the original diff as context; Claude writes the adapted diff |
| `amalgamator` | Multi-phase pipeline | Semantic triage → cherry-pick → edit/build/test loop with retries |

---

## Prerequisites

- **OpenShift cluster** with the `backport-agent-leaderboard` namespace (or any namespace
  you set in `config.yaml`)
- **Podman** (or Docker) to build the container image
- **Vertex AI credentials** for Claude API access via Google Cloud
- **Python 3.10+** with `pyyaml` installed locally (`pip install pyyaml`)

Complete the one-time cluster setup in [`infra/README.md`](../../infra/README.md) before
running the evaluation.

---

## Step 1 — Understand the Containerfile

The `Containerfile` defines the **build environment** that runs inside every OpenShift
pod. It needs to contain everything required to clone crate, build it, and run the tool.

```
FROM eclipse-temurin:24-jdk          ← JDK 24 (Temurin) matches crate's build requirements
                                        See repos.md for per-repo toolchain requirements

RUN apt-get install git patch python3 python3-pip curl openssl
                                        ← git: clone crate
                                        ← patch: apply the generated diff
                                        ← python3/pip: run the Raw Claude script + install Vertex AI SDK
                                        ← curl: call the Kubernetes API to save results
                                        ← openssl: Maven SSL tests

ENV HOME=/tmp                           ← OpenShift runs pods as a random non-root UID with
                                           no home directory. Setting HOME=/tmp lets Maven
                                           write ~/.m2 to /tmp/.m2 (always writable).

COPY generic_claude_backport.py /opt/   ← Bake the Raw Claude script into the image so it
                                           doesn't need to be fetched at runtime
```

**Why run in a container at all?** crate's build (Maven + JDK 24) takes ~4 GB of
dependencies and several minutes to compile. Running in OpenShift pods means:
- All cases run in parallel (one pod per case)
- No dependency on the local machine's JDK or Maven setup
- Results are reproducible across machines

---

## Step 2 — Build and push the image

```bash
cd evals/crate/

# Build the image
podman build -t quay.io/<your-org>/crate-eval:latest .

# Push to your registry
# (Quay.io, Docker Hub, or any registry your OpenShift cluster can pull from)
podman push quay.io/<your-org>/crate-eval:latest
```

**Why push to a registry?** OpenShift pods pull the image from a registry at runtime.
The image must be publicly accessible (or the cluster must have pull credentials for it).
You only need to rebuild and push when the `Containerfile` changes.

Update `image:` in `config.yaml` to point to your registry path before running.

---

## Step 3 — One-time cluster setup

Follow [`infra/README.md`](../../infra/README.md). This covers:

- Logging in with `oc login`
- Applying `infra/rbac.yaml` (gives pods permission to save results to ConfigMaps)
- Creating the Vertex AI credentials secret
- Uploading the Raw Claude script and Amalgamator source as ConfigMaps

You only do this once per namespace. After that, skip straight to Step 4.

---

## Step 4 — Configure the evaluation

Open **`config.yaml`**. The fields you'll most likely want to change:

```yaml
# Which repo and dataset to use
repo: crate/crate
dataset:
  csv: ../../backports.csv   # path to the ground-truth CSV (relative to this file)
  limit: null                # null = run all cases | integer = random sample
  classification: null       # null = all tiers | "Easy" | "Medium" | "Hard"

# Which tools to run
tools:
  raw-claude:
    enabled: true
    image: quay.io/<your-org>/crate-eval:latest   # ← update this
  amalgamator:
    enabled: true
    image: quay.io/<your-org>/crate-eval:latest   # ← update this

# OpenShift settings
openshift:
  namespace: backport-agent-leaderboard   # ← update if using a different namespace
  vertex_project: <your-gcp-project>      # ← your GCP project ID
```

Everything else (build command, test command, resource limits, timeout) has sensible
defaults for crate and rarely needs changing.

---

## Step 5 — Run the evaluation

```bash
# From the repo root — launches all enabled tools
python3 run.py --config evals/crate/config.yaml

# Launch one tool at a time
python3 run.py --config evals/crate/config.yaml --tool raw-claude
python3 run.py --config evals/crate/config.yaml --tool amalgamator

# Filter the dataset on the fly without editing config.yaml
python3 run.py --config evals/crate/config.yaml --classification Easy
python3 run.py --config evals/crate/config.yaml --limit 5

# Monitor pods
oc get pods -n backport-agent-leaderboard | grep crate-
oc logs -n backport-agent-leaderboard <pod-name> --tail=30
```

**How it works behind the scenes:**
- `run.py` reads `config.yaml`, queries the local git clone for commit metadata
  (test class, Maven module, target branch), then submits one OpenShift Job per case
- Each pod clones `crate/crate`, runs the tool, applies the diff, builds and tests,
  and saves a JSON result to an OpenShift ConfigMap before exiting
- Results are saved to ConfigMaps (not just pod logs) so they survive pod
  garbage collection — pods are often cleaned up before you collect results

**Expected runtime:**
- Raw Claude: ~30 min for 9 cases (pods run in parallel)
- Amalgamator: ~1–2 hr for 9 cases (pipeline has multiple phases)

---

## Step 6 — Collect results

```bash
# Collect both tools
python3 run.py --config evals/crate/config.yaml --collect

# Collect one tool
python3 run.py --config evals/crate/config.yaml --collect --tool raw-claude
```

This reads results from ConfigMaps (primary) and pod logs (fallback), writes JSON to
`results/crate/`, and prints a scorecard:

```
  Difficulty    N   Apply / Test Pass / Latency / Tokens
  ──────────────────────────────────────────────────────────────────────
  Easy          3   Apply: 1/3 (33%)  Test PASS: 0/3 (0%)   Avg 29s  8691 tok
  Medium        3   Apply: 0/3 (0%)   Test PASS: 0/3 (0%)   Avg 18s  8007 tok
  Hard          3   Apply: 1/3 (33%)  Test PASS: 0/3 (0%)   Avg 22s  7872 tok
  ──────────────────────────────────────────────────────────────────────
  TOTAL         9   Apply: 2/9 (22%)  Test PASS: 0/9 (0%)   Avg 23s  8190 tok
```

Result JSON files are gitignored (`results/crate/` in `.gitignore`).

---

## Adjusting paths

| What | Where to change |
|------|----------------|
| Registry path for the image | `config.yaml` → `tools.<tool>.image` |
| OpenShift namespace | `config.yaml` → `openshift.namespace` |
| GCP project for Vertex AI | `config.yaml` → `openshift.vertex_project` |
| Path to backports.csv | `config.yaml` → `dataset.csv` (relative to this config file) |
| Path to local git clone (for metadata) | `config.yaml` → `local_clone` (defaults to `../benchmark-repos/crate`) |
| Pod memory / CPU | `config.yaml` → `openshift.resources.<tool>` |
| Per-pod timeout | `config.yaml` → `openshift.job_timeout_seconds` |

---

## Adding a new repo

Copy this directory as a template:

```bash
cp -r evals/crate/ evals/grpc-java/
```

Then:
1. Edit `config.yaml` — update `repo`, `build_command`, `test_command`, `image`
2. Edit `Containerfile` — change the base image if the language or toolchain differs
   (e.g. `FROM golang:1.22` for a Go repo, `FROM python:3.12` for a Python repo)
3. Build and push the new image (Step 2)
4. Update `infra/README.md` steps if new secrets are needed
5. Run `python3 run.py --config evals/grpc-java/config.yaml`

The top-level `run.py` is generic — it reads whatever config you point it at and
never needs to change when you add a new repo.
