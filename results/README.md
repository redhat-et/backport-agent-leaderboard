# Results & leaderboard

Completed runs are curated here: each `runs/<timestamp>/` directory is a full harbor job
output — result, verifier logs, and the complete agent artifacts (every model call, the
candidate patch, the phase tracker). Fresh runs land in `jobs/` (gitignored) and get copied
in when curated.

## Leaderboard

| Pipeline | Model (endpoint) | Attempted | Passed | Pass rate |
|---|---|---:|---:|---:|
| Amalgamator | GLM 5.3 (`openai/rits/zai-org/glm-5-3` via EnMaaS) | 2 / 31 | 2 | 100% |

Runs to date (details below):

| Task | Tier | Reward | Wall time | Model calls | Tokens | Run log |
|---|---|---|---|---|---|---|
| `expat-cve-2025-59375-c10s` | Medium | **1.0** | 2h20m | 605 | ~55.7M | [`runs/2026-10-15__15-13-28`](runs/2026-10-15__15-13-28/) |
| `expat-cve-2025-59375-c9s` | Hard | **1.0** | 2h33m | 611 | ~43.1M | [`runs/2026-10-15__18-50-25`](runs/2026-10-15__18-50-25/) |

## Reading a run directory

```
runs/2026-10-15__15-13-28/expat-cve-2025-59375-c10s__<trial-id>/
├── result.json                     # reward + metrics
├── verifier/reward.txt             # 0 or 1 — the verdict
├── verifier/test-stdout.txt        # gate output (pass/fail evidence)
├── trial.log, job.log              # harbor-level logs
└── artifacts/workspace/amalgamator/runs/case_*/
    ├── run_log.txt                 # full pipeline log — every model call
    ├── phase_4b_log.txt            # run-and-fix loop detail
    ├── candidate.patch             # the pipeline's answer
    ├── dossier.md                  # per-case dossier
    └── <issue>_<ts>.json           # phase tracker: per-phase time, calls, tokens
```

## Run notes

### `expat-cve-2025-59375-c10s` — GLM 5.3, reward 1.0 (2026-10-15)

First end-to-end pass. 2h20m, 605 model calls, ~55.7M tokens. Phase split: semantic triage
~58 min, test port ~16 min, cherry-pick/resolve ~63 min; converged without needing the
run-and-fix loop. Route: added a downstream patch (`expat-2.7.1-CVE-2025-59375.patch`) to
the dist-git spec — the same shape as the human backport. Job `2026-10-15__15-13-28`,
trial `__HtdTU3Z`.

### `expat-cve-2025-59375-c9s` — GLM 5.3, reward 1.0 (2026-10-15)

First full exercise of Phase 4b (run-and-fix). 2h33m, 611 model calls, ~43.1M tokens.
Cherry-pick/resolve ended in escalation (~68 min), after which 4b force-resolved and drove
the tree green in ~40 min. Route: downstream patch
`expat-2.5.0-CVE-2025-59375.patch` — matching the human golden (`2d0719b`). Job
`2026-10-15__18-50-25`, trial `__F7CKvCw`.

## Adding a run

1. `cp -r jobs/<timestamp> results/runs/<timestamp>` once the run is complete and curated.
2. Add a row to the tables above and a short note (what made the run interesting: route,
   phase behavior, failures).
