# Backport Agent Leaderboard

Evaluates automated backporting tools — **Raw Claude** (single-shot LLM) and **Amalgamator** (multi-phase pipeline) — against a curated dataset of known-good backports from open-source projects.

Each case runs in an OpenShift pod that clones the repo, runs the tool, applies the patch, builds the code, and runs the targeted tests. Results are saved to ConfigMaps and displayed on a live Gradio leaderboard.

---

## What gets measured

| Metric | Description |
|--------|-------------|
| **Apply Rate** | Did the agent produce a patch that applied cleanly? |
| **Test Pass Rate** | Did the target test pass after applying the patch? |
| **Semantic Equivalence** | Does the agent's patch match the ground-truth backport commit exactly? |
| **Baseline Test** | Did the test pass *before* patching? (distinguishes pre-existing failures from regressions) |
| **Cost / Tokens / Latency** | API spend and runtime per case |

## Repos under evaluation

| Repo | Language | Build/test | Eval config |
|------|----------|------------|-------------|
| `crate/crate` | Java | Maven | [`evals/crate/`](evals/crate/) |
| `cri-o/cri-o` | Go | `go build ./...` | [`evals/cri-o/`](evals/cri-o/) |
| `django/django` | Python | `runtests.py` | [`evals/django/`](evals/django/) |

---

## Flow at a glance

```
1. oc login                         → authenticate to your OpenShift cluster
2. oc apply -f infra/rbac.yaml      → one-time: pod permissions, service accounts
3. create secrets & ConfigMaps      → Vertex AI creds, Raw Claude script, Amalgamator source
4. podman build + push images       → one container image per repo (JDK / Go / Python base)
5. python3 run.py --config ...      → launch all jobs for a repo
6. oc get pods | grep <repo>        → watch pods run in parallel (~30 min raw, ~90 min amal)
7. python3 run.py --config ... --collect → pull results from ConfigMaps → JSON
8. leaderboard auto-updates         → deployed Gradio app reads ConfigMaps live
```

---

## Prerequisites

- **OpenShift cluster** with `oc` CLI (`oc login` working)
- **Podman** to build and push container images
- **Python 3.10+** with `pyyaml` (`pip install pyyaml`)
- **Vertex AI credentials** — GCP service account with Vertex AI access (`gcloud auth application-default login`)
- **Local git clones** of the repos you want to evaluate (used to extract test metadata)

---

## Step 1 — One-time cluster setup

```bash
# Create the namespace
oc new-project backport-agent-leaderboard

# Give pods permission to write results to ConfigMaps
oc apply -f infra/rbac.yaml

# Upload GCP credentials for Vertex AI (Claude API)
oc create secret generic gcloud-adc \
  --from-file=application_default_credentials.json=$HOME/.config/gcloud/application_default_credentials.json

# Upload the Raw Claude script (used by all repos)
oc create configmap raw-claude-script \
  --from-file=generic_claude_backport.py=evals/crate/scripts/generic_claude_backport.py

# Upload the Amalgamator pipeline source (tar from your local Amalgamator clone)
tar czf /tmp/amalgamator.tar.gz \
  -C /path/to/amalgamator auto_bug_fix/ auto_code_gen/ common/ pyproject.toml uv.lock
oc create configmap amalgamator-src --from-file=amalgamator.tar.gz=/tmp/amalgamator.tar.gz
```

See [`infra/README.md`](infra/README.md) for full details on each step.

---

## Step 2 — Build and push images

Each repo needs its own container image with the right language toolchain:

```bash
# crate/crate (Java / Maven)
podman build --platform linux/amd64 \
  -t quay.io/<your-org>/crate-eval:latest \
  -f evals/crate/Containerfile evals/crate/
podman push quay.io/<your-org>/crate-eval:latest

# cri-o/cri-o (Go)
podman build --platform linux/amd64 \
  -t quay.io/<your-org>/crio-eval:latest \
  -f evals/cri-o/Containerfile evals/cri-o/
podman push quay.io/<your-org>/crio-eval:latest

# django/django (Python)
podman build --platform linux/amd64 \
  -t quay.io/<your-org>/django-eval:latest \
  -f evals/django/Containerfile evals/django/
podman push quay.io/<your-org>/django-eval:latest
```

> **Tip:** Use `--platform linux/amd64` if building on Apple Silicon — OpenShift clusters typically run amd64.

Update each `config.yaml` to point to your image registry:

```yaml
# evals/<repo>/config.yaml
tools:
  raw-claude:
    image: quay.io/<your-org>/crate-eval:latest   # ← update
  amalgamator:
    image: quay.io/<your-org>/crate-eval:latest   # ← update
openshift:
  namespace: backport-agent-leaderboard            # ← update if different
  vertex_project: <your-gcp-project>              # ← your GCP project ID
```

---

## Step 3 — Run the evaluation

```bash
# Launch all tools for all three repos
python3 run.py --config evals/crate/config.yaml
python3 run.py --config evals/cri-o/config.yaml
python3 run.py --config evals/django/config.yaml

# Run only one tool
python3 run.py --config evals/crate/config.yaml --tool raw-claude

# Filter by difficulty
python3 run.py --config evals/crate/config.yaml --classification Easy

# Watch pods run in parallel
oc get pods -n backport-agent-leaderboard | grep crate-

# Check a pod's log
oc logs -n backport-agent-leaderboard <pod-name> --tail=40
```

**Expected runtime (all 9 cases per repo):**
- Raw Claude: ~30 min
- Amalgamator: ~60–90 min

---

## Step 4 — Collect results

```bash
python3 run.py --config evals/crate/config.yaml --collect
python3 run.py --config evals/cri-o/config.yaml --collect
python3 run.py --config evals/django/config.yaml --collect
```

Reads results from OpenShift ConfigMaps (persisted even after pods are cleaned up), writes summary JSON to `results/<repo>/`, and prints a scorecard.

---

## Step 5 — View the leaderboard

The leaderboard reads ConfigMaps directly and auto-refreshes every 60 seconds.

```bash
# Deploy leaderboard to OpenShift (one-time)
podman build --platform linux/amd64 \
  -t quay.io/<your-org>/backport-leaderboard:latest \
  -f infra/leaderboard/Containerfile .
podman push quay.io/<your-org>/backport-leaderboard:latest
oc apply -f infra/leaderboard/leaderboard.yaml

# Get the public URL
oc get route backport-leaderboard -n backport-agent-leaderboard
```

Or run locally:

```bash
pip install gradio pandas
python3 leaderboard/app.py
# Opens at http://localhost:7860
```

See [`infra/leaderboard/README.md`](infra/leaderboard/README.md) for details.

---

## Project structure

```
backport-agent-leaderboard/
│
├── run.py                        # Generic job launcher + result collector
│                                 # reads any evals/<repo>/config.yaml
│
├── evals/                        # One directory per evaluated repo
│   ├── crate/                    # Java/Maven (reference implementation)
│   │   ├── Containerfile         # Pod image (JDK 24, Maven, Python, git, patch)
│   │   ├── config.yaml           # All tunable params
│   │   ├── README.md             # Step-by-step guide
│   │   └── scripts/
│   │       └── generic_claude_backport.py  # Raw Claude single-shot backporter
│   ├── cri-o/                    # Go (same structure)
│   └── django/                   # Python (same structure)
│
├── infra/                        # One-time cluster setup
│   ├── rbac.yaml                 # ServiceAccount + Role + RoleBinding
│   ├── README.md                 # Cluster setup guide
│   └── leaderboard/              # Gradio leaderboard on OpenShift
│       ├── Containerfile
│       ├── leaderboard.yaml      # Deployment + Service + Route
│       └── README.md
│
├── leaderboard/                  # Gradio leaderboard app
│   ├── app.py
│   └── data_loader.py            # Reads results from OpenShift ConfigMaps
│
└── backports.csv                 # Dataset: 27 known-good backports (Easy/Medium/Hard)
```

---

## Adding a new repo

```bash
cp -r evals/crate/ evals/my-new-repo/
```

1. Edit `config.yaml` — update `repo`, `clone_url`, `build_command`, `test_command`, `language`, `image`
2. Edit `Containerfile` — change base image to match the language toolchain
3. Build and push the image
4. Run `python3 run.py --config evals/my-new-repo/config.yaml`

The `run.py` runner is generic — it auto-detects test classes, Maven modules, and Go packages from git metadata. No code changes needed.

See [`evals/crate/README.md`](evals/crate/README.md) for the reference walkthrough.
