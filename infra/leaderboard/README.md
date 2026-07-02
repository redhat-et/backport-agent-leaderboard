# Leaderboard — OpenShift Deployment

This deploys the Gradio leaderboard app to OpenShift so evaluation results are
visible at a public URL without running anything locally.

---

## Architecture

```
eval pods → ConfigMaps → run.py --push-results → leaderboard pod (/results PVC)
                                                         │
                                              Gradio app reads aggregated JSON
                                                         │
                                              OpenShift Route → public HTTPS URL
```

---

## Step 1 — Build and push the leaderboard image

Run from the **repo root** (so `leaderboard/` and `backport_bench/` are in the build context):

```bash
podman build -f infra/leaderboard/Containerfile \
  -t quay.io/<your-org>/backport-leaderboard:latest .

podman push quay.io/<your-org>/backport-leaderboard:latest
```

Update the image reference in `leaderboard.yaml` if your registry path differs.

---

## Step 2 — Deploy to OpenShift

```bash
oc apply -f infra/leaderboard/leaderboard.yaml -n backport-agent-leaderboard
```

This creates:
- **PVC** `leaderboard-results` — 1Gi persistent storage for result JSON files
- **Deployment** `backport-leaderboard` — runs the Gradio app, mounts the PVC at `/results`
- **Service** `backport-leaderboard` — exposes port 7860 inside the cluster
- **Route** `backport-leaderboard` — creates a public HTTPS URL (OpenShift assigns the hostname)

Get the public URL:

```bash
oc get route backport-leaderboard -n backport-agent-leaderboard \
  -o jsonpath='{.spec.host}'
```

---

## Step 3 — Push results after evaluation

After collecting results locally, push them to the leaderboard pod:

```bash
# Collect from ConfigMaps → local JSON
python3 run.py --config evals/crate/config.yaml --collect

# Push to leaderboard pod (aggregates automatically)
python3 run.py --config evals/crate/config.yaml --push-results
```

The leaderboard refreshes immediately — no pod restart needed.

---

## Updating the leaderboard app

If `leaderboard/app.py` or `leaderboard/data_loader.py` changes:

```bash
podman build -f infra/leaderboard/Containerfile -t quay.io/<your-org>/backport-leaderboard:latest .
podman push quay.io/<your-org>/backport-leaderboard:latest
oc rollout restart deployment/backport-leaderboard -n backport-agent-leaderboard
```

---

## Running locally (no OpenShift)

```bash
RESULTS_DIR=results/aggregated python3 leaderboard/app.py
# Open http://localhost:7860
```
