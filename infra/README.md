# Cluster Setup (One-time)

This is a one-time setup for the OpenShift namespace that runs all evaluations.
Once done, individual evaluations just need:

```bash
python3 run.py --config evals/<repo>/config.yaml
```

---

## Why OpenShift?

Building and testing Java projects (or any compiled language) requires the right
JDK, build tool, and dependency cache — and can take minutes per case. Running
evaluations inside OpenShift pods gives us:

- **Parallelism** — one pod per test case, all running at the same time
- **Isolation** — each pod gets a clean environment; no state leaks between cases
- **Reproducibility** — the exact same container image runs on every machine
- **Result durability** — results are saved to ConfigMaps (Kubernetes objects) before
  pods exit, so they survive pod garbage collection

---

## 1. Log into OpenShift

```bash
# Get your token from the OpenShift web console → top-right menu → "Copy login command"
oc login --token=<token> --server=<server-url>

# Switch to (or create) the namespace
oc project backport-agent-leaderboard
# or, if it doesn't exist yet:
oc new-project backport-agent-leaderboard
```

**Why a dedicated namespace?** Keeping all eval pods, jobs, ConfigMaps, secrets, and
RBAC in one namespace makes cleanup trivial (`oc delete namespace ...` removes
everything) and prevents collisions with other projects.

---

## 2. Apply RBAC

Pods need permission to write their results to ConfigMaps:

```bash
oc apply -f infra/rbac.yaml
```

**Why is RBAC needed?** By default, pods cannot create or modify Kubernetes objects —
not even in their own namespace. The `rbac.yaml` grants a narrow permission:

- `ServiceAccount: eval-result-writer` — an identity that pods run as
- `Role: configmap-writer` — allows only `create`, `update`, `patch` on ConfigMaps
- `RoleBinding` — links the two so pods using the service account get the role

**Why save to ConfigMaps instead of just printing logs?** Pod logs disappear once a
pod is deleted (and OpenShift deletes completed pods automatically after a TTL).
ConfigMaps are persistent cluster objects — results stay available until you delete
them explicitly.

Verify it worked:

```bash
oc get serviceaccount eval-result-writer
oc get role configmap-writer
oc get rolebinding configmap-writer-binding
```

---

## 3. Create the Vertex AI credentials secret

Pods call Claude via Vertex AI (Google Cloud). They need your GCP credentials:

```bash
oc create secret generic gcloud-adc \
  --from-file=application_default_credentials.json=$HOME/.config/gcloud/application_default_credentials.json
```

**Why store credentials as a secret?** Kubernetes Secrets are base64-encoded and kept
separate from pod definitions. They are mounted into pods as files at runtime. This
avoids baking credentials into the container image or config YAML.

**How to refresh:** Credentials expire (typically every 12 hours for user credentials,
longer for service accounts). When they expire, pods will fail with `401 Unauthorized`
from the Vertex AI API. Refresh by re-running the `oc create secret` command above
(delete first if it already exists):

```bash
# Refresh credentials
gcloud auth application-default login   # re-authenticate locally first
oc delete secret gcloud-adc
oc create secret generic gcloud-adc \
  --from-file=application_default_credentials.json=$HOME/.config/gcloud/application_default_credentials.json
```

---

## 4. Upload the Raw Claude script

The Raw Claude evaluator (`generic_claude_backport.py`) is baked into the container
image **and** uploaded as a ConfigMap. This ConfigMap is a fallback and makes updating
the script easy without rebuilding the image:

```bash
oc create configmap raw-claude-script \
  --from-file=generic_claude_backport.py=evals/crate/scripts/generic_claude_backport.py
```

**Why a ConfigMap for a script?** The container image changes infrequently (JDK,
system packages). The Python script may be tweaked often. Storing it as a ConfigMap
lets you update it with one `oc` command and re-run immediately — no rebuild, no push.

Recreate if the script changes:

```bash
oc delete configmap raw-claude-script
oc create configmap raw-claude-script \
  --from-file=generic_claude_backport.py=evals/crate/scripts/generic_claude_backport.py
```

---

## 5. Upload the Amalgamator source

The Amalgamator pipeline is a multi-file Python package. It's tarred up and stored
as a ConfigMap so pods can extract and run it without needing GitHub credentials
inside the pod:

```bash
# From your local Amalgamator source directory (adjust path as needed):
tar czf /tmp/amalgamator.tar.gz \
  auto_bug_fix/ auto_code_gen/ common/ pyproject.toml uv.lock

# Check size — ConfigMaps have a 1 MB limit
du -h /tmp/amalgamator.tar.gz

oc create configmap amalgamator-src \
  --from-file=amalgamator.tar.gz=/tmp/amalgamator.tar.gz
```

**Why tar the source instead of cloning in the pod?** Cloning a private repo inside
a pod requires SSH keys or tokens. Tarballing avoids auth entirely and is faster
(no network call at pod startup).

**Size limit:** Kubernetes ConfigMaps are capped at 1 MB. Exclude large directories
(e.g. `auto_analyze/`) that the evaluation pipeline doesn't use.

Recreate if the Amalgamator source changes:

```bash
# Rebuild the tarball and re-upload
tar czf /tmp/amalgamator.tar.gz auto_bug_fix/ auto_code_gen/ common/ pyproject.toml uv.lock
oc delete configmap amalgamator-src
oc create configmap amalgamator-src --from-file=amalgamator.tar.gz=/tmp/amalgamator.tar.gz
```

---

## Verify everything is in place

```bash
oc get serviceaccount eval-result-writer
oc get secret gcloud-adc
oc get configmap raw-claude-script
oc get configmap amalgamator-src
```

All four must exist before running any evaluation. Once they do, move to the
repo-specific README (e.g. [`evals/crate/README.md`](../evals/crate/README.md)).

---

## Cleanup

To tear down the entire namespace and all resources:

```bash
oc delete namespace backport-agent-leaderboard
```

To clean up just job/pod/result artifacts (keeping the namespace and secrets):

```bash
# Delete all completed jobs
oc delete jobs --all -n backport-agent-leaderboard

# Delete all result ConfigMaps (named crate-raw-* or crate-amal-*)
oc get configmaps -n backport-agent-leaderboard --no-headers | \
  awk '$1 ~ /^crate-/ {print $1}' | \
  xargs -r oc delete configmap -n backport-agent-leaderboard
```
