"""
data_loader.py — load backport benchmark results.

Two sources (tried in order):
  1. Kubernetes ConfigMaps  — live data from the OpenShift cluster.
  2. JSON files on disk     — local dev fallback (results_dir/*.json).

Scoring definitions
-------------------
patch_applied (Apply)
  PASS = the agent produced a non-empty patch that applied cleanly (patch exit 0).
  FAIL = patch was empty or failed to apply.

semantic_equivalence (Sem.Eq.)
  PASS = the agent's patch is byte-for-byte identical to the ground-truth backport commit.
  FAIL = the patch differs from the ground truth (even if tests pass).

test_success (Test)
  PASS = the repo's unit tests passed AFTER applying the backport.
  FAIL = tests failed (or build failed) after backport.

baseline_test (Baseline)
  PASS = tests passed BEFORE any backport was applied (clean branch).
  FAIL = tests were already broken on the target branch.
"""

import json
import os
import re
import ssl
import urllib.request
from collections import defaultdict
from pathlib import Path

import pandas as pd

# ── Kubernetes helpers ────────────────────────────────────────────────────────

def _k8s_token() -> str | None:
    p = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
    return p.read_text().strip() if p.exists() else None

def _k8s_namespace() -> str:
    p = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
    if p.exists():
        return p.read_text().strip()
    return os.environ.get("NAMESPACE", "backport-agent-leaderboard")

def _k8s_ca() -> str | None:
    p = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    return p if Path(p).exists() else None

def _k8s_ctx():
    ca = _k8s_ca()
    return ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()

def _k8s_base() -> str:
    return f"https://kubernetes.default.svc/api/v1/namespaces/{_k8s_namespace()}/configmaps"

def _k8s_get(path: str) -> dict | None:
    token = _k8s_token()
    if not token:
        return None
    try:
        req = urllib.request.Request(
            _k8s_base() + path,
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, context=_k8s_ctx()) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


# ── Result loader ─────────────────────────────────────────────────────────────

def load_results_from_configmaps() -> list[dict]:
    data = _k8s_get("")
    if not data:
        return []
    results = []
    for item in data.get("items", []):
        name = item["metadata"]["name"]
        if not name.startswith("result-"):
            continue
        raw = item.get("data", {}).get("result")
        if not raw:
            continue
        try:
            results.append(json.loads(raw))
        except Exception:
            continue
    return results


def load_results_from_files(results_dir: Path) -> list[dict]:
    results_dir = Path(results_dir)
    results = []
    for path in sorted(results_dir.glob("*.json")):
        try:
            with open(path) as f:
                results.append(json.load(f))
        except Exception:
            continue
    return results


def load_results(results_dir: Path | None = None) -> tuple[list[dict], str]:
    cm = load_results_from_configmaps()
    if cm:
        return cm, "ConfigMaps (live)"
    if results_dir:
        files = load_results_from_files(results_dir)
        if files:
            return files, "files (local)"
    return [], "no data"


# ── Log fetcher ───────────────────────────────────────────────────────────────

_REPO_SLUG = {
    "crate/crate":   "crate",
    "cri-o/cri-o":   "crio",
    "django/django":  "django",
}

def _repo_slug(repo: str) -> str:
    if repo in _REPO_SLUG:
        return _REPO_SLUG[repo]
    return re.sub(r"[^a-z0-9]", "", repo.split("/")[-1].lower())[:10]

def _log_cm_name(slug: str, tool_key: str, repo: str) -> str:
    short = "raw" if tool_key == "raw-claude" else "amal"
    return f"log-result-{short}-{_repo_slug(repo)}-{slug}"

def fetch_log(slug: str, tool_key: str, repo: str) -> str:
    cm_name = _log_cm_name(slug, tool_key, repo)
    data = _k8s_get(f"/{cm_name}")
    if not data:
        return f"(log ConfigMap '{cm_name}' not found or not running in cluster)"
    return data.get("data", {}).get("log", "(empty log)")


def extract_log_section(log: str, section: str) -> str:
    """Extract a named section from the pod log (between === markers)."""
    pattern = rf"=== {re.escape(section)} ===(.*?)(?====|$)"
    m = re.search(pattern, log, re.DOTALL)
    return m.group(1).strip() if m else f"(section '{section}' not found in log)"


# ── Labels ────────────────────────────────────────────────────────────────────

_TOOL_LABELS = {
    "raw-claude":  "Raw Claude (Opus 4.6)",
    "amalgamator": "Amalgamator / Opus 4.6",
}

_REPO_SHORT = {
    "crate/crate":   "crate",
    "cri-o/cri-o":   "cri-o",
    "django/django":  "django",
}

def _tool_label(key: str) -> str:
    return _TOOL_LABELS.get(key, key)


# ── Scoring ───────────────────────────────────────────────────────────────────

def _apply_rate(results: list[dict]) -> float | None:
    """Fraction of cases where the patch applied cleanly (patch exit 0)."""
    if not results:
        return None
    def applied(r):
        # New field: patch_applied. Fall back to semantic_equivalence for old results.
        pa = r.get("patch_applied")
        if pa is not None:
            return pa == "PASS"
        return r.get("semantic_equivalence") == "PASS"
    return round(sum(1 for r in results if applied(r)) / len(results), 4)

def _full_pass_rate(results: list[dict]) -> float | None:
    """Fraction where patch applied AND tests passed AND baseline was clean."""
    if not results:
        return None
    def ok(r):
        pa = r.get("patch_applied")
        applied = (pa == "PASS") if pa is not None else (r.get("semantic_equivalence") == "PASS")
        return (applied
                and r.get("test_success") == "PASS"
                and r.get("baseline_test") == "PASS")
    return round(sum(1 for r in results if ok(r)) / len(results), 4)

def _sem_eq_rate(results: list[dict]) -> float | None:
    """Fraction where agent patch exactly matches ground-truth backport commit."""
    if not results:
        return None
    return round(sum(1 for r in results if r.get("semantic_equivalence") == "PASS") / len(results), 4)

def _fmt(v: float | None, pending: bool = False) -> str:
    if v is None:
        return "⏳" if pending else "—"
    return f"{v:.1%}"


# ── DataFrame builders ────────────────────────────────────────────────────────

def build_leaderboard_df(results: list[dict], all_cases_count: int = 0) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()

    groups: dict[tuple, list] = defaultdict(list)
    for r in results:
        key = (r.get("tool_key", "unknown"), r.get("repo", "unknown"))
        groups[key].append(r)

    # Collect which (tool, repo) combos have data
    tool_repo_data: dict[str, dict] = defaultdict(lambda: {"repos": {}, "all": []})
    for (tool_key, repo), rows in groups.items():
        label = _tool_label(tool_key)
        short = _REPO_SHORT.get(repo, repo)
        tool_repo_data[label]["repos"][short] = {
            "apply": _apply_rate(rows),
            "full":  _full_pass_rate(rows),
            "n":     len(rows),
        }
        tool_repo_data[label]["all"].extend(rows)

    repos_seen = sorted({_REPO_SHORT.get(r.get("repo", ""), r.get("repo", "")) for r in results})

    rows_out = []
    for label, data in tool_repo_data.items():
        row = {
            "Tool":           label,
            "Apply Rate":     _fmt(_apply_rate(data["all"])),
            "Full Pass Rate": _fmt(_full_pass_rate(data["all"])),
        }
        for repo_short in repos_seen:
            rd = data["repos"].get(repo_short)
            if rd is None:
                row[repo_short] = "⏳"   # still running
            else:
                apply = _fmt(rd["apply"])
                full  = _fmt(rd["full"])
                row[repo_short] = f"{apply} / {full}"
        rows_out.append(row)

    df = pd.DataFrame(rows_out)
    df = df.sort_values("Apply Rate", ascending=False).reset_index(drop=True)
    return df


def build_runs_df(results: list[dict]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()

    rows = []
    for r in results:
        tool_key = r.get("tool_key", "unknown")
        slug     = r.get("slug", "")
        repo     = r.get("repo", "")
        # patch_applied is the new explicit field; fall back to sem_eq for old results
        pa = r.get("patch_applied") or (
            "PASS" if r.get("semantic_equivalence") == "PASS" else "FAIL"
        )
        rows.append({
            "Tool":         _tool_label(tool_key),
            "Repo":         repo,
            "Slug":         slug,
            "Difficulty":   r.get("classification", ""),
            "Applied":      pa,
            "Sem.Eq.":      r.get("semantic_equivalence", ""),
            "Reason":       r.get("semantic_difference_reason") or "",
            "Test":         r.get("test_success", ""),
            "Baseline":     r.get("baseline_test", ""),
            "Diff Lines":   r.get("diff_lines", 0),
            "Cost $":       round(r.get("cost_usd", 0), 4),
            "Secs":         int(r.get("time_seconds", 0)),
            # hidden — used by log viewer
            "_slug":        slug,
            "_tool_key":    tool_key,
            "_repo":        repo,
            "_test_cmd":    r.get("test_command", ""),
        })

    df = pd.DataFrame(rows)
    diff_order = {"Easy": 0, "Medium": 1, "Hard": 2}
    df["_diff_ord"] = df["Difficulty"].map(diff_order).fillna(9)
    df = df.sort_values(["Tool", "Repo", "_diff_ord"]).drop(columns=["_diff_ord"])
    return df.reset_index(drop=True)
