# Results & leaderboard

Completed runs are curated here: each `runs/<timestamp>/` directory is a full harbor job
output — result, verifier logs, and the complete agent artifacts (every model call, the
candidate patch, the phase tracker). Fresh runs land in `jobs/` (gitignored) and get copied
in when curated.

## Leaderboard

| Pipeline | Model (endpoint) | Attempted | Passed | Pass rate |
|---|---|---:|---:|---:|
| Amalgamator | GLM 5.3 (`openai/rits/zai-org/glm-5-3` via EnMaaS) | 3 / 31 | 2 | 67% |

Runs to date (details below):

| Task | Tier | Reward | Wall time | Model calls | Tokens | Run log |
|---|---|---|---|---|---|---|
| `expat-cve-2025-59375-c10s` | Medium | **1.0** | 2h20m | 605 | ~55.7M | [`runs/2026-10-15__15-13-28`](runs/2026-10-15__15-13-28/) |
| `expat-cve-2025-59375-c9s` | Hard | **1.0** | 2h33m | 611 | ~43.1M | [`runs/2026-10-15__18-50-25`](runs/2026-10-15__18-50-25/) |
| `expat-cve-2025-59375-c8s` | Extreme | 0.0 | 3h21m | — | ~76M/attempt | [`runs/2026-10-16__19-46-49`](runs/2026-10-16__19-46-49/) (attempt 4) |

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

### `expat-cve-2025-59375-c8s` — GLM 5.3, reward 0.0 (2026-10-16, attempt 4 of 4)

**Not a model failure — a task/harness failure.** The model solved the backport in every
attempt; the evaluation plumbing discarded the solution every time.

What happened (identical in all 4 attempts, 3h21m–5h each, all-GLM):

1. Cherry-pick is structurally impossible here (17-file conflict — the 2.2.5 tree predates
   the upstream fix's entire accounting machinery), so Phase 4b re-implements the fix from
   scratch. It succeeded **every time**: "SUCCESS" with retries 4/4, 8/10, 6/10 across
   attempts; suite green (368–369 checks); proper dist-git integration (downstream patch,
   spec `Patch20`, release bump, changelog); committed to `target`.
2. Phase 4 verify then **re-runs** the canonical build command (`centpkg sources && prep`)
   on the builddir left behind by the agent's own successful final build. The c8s
   package's `%prep` is **non-idempotent** — the downstream CVE-2023-52425 patch creates
   `testdata/largefiles/*` outside `%setup`'s cleanup — so the re-run fails within
   seconds (verify window: 16–96 s).
3. Escalation → the pipeline emits **no candidate.patch** → the harbor verifier never sees
   the work → `No candidate.patch found … agent did not produce a patch` → reward 0.

The verdict therefore records "agent did not produce a patch" while a committed, tested
backport existed in the container each time. The harbor verifier itself applies patches to
a *fresh* worktree (where the first prep is green), so the work would very likely have
scored 1.0 had it been emitted.

Root causes, and where they live:

- **Task**: the canonical build command is stateful/non-idempotent. A human backporter
  never hits this (fresh clone, prep once). Fix: make the command self-cleaning
  (`rm -rf libexpat-R_2_2_5 && …`).
- **Adapter/harness**: escalation suppresses the deliverable, pre-empting the verifier —
  the benchmark's own judge. Fix: the adapter exports `candidate.patch` from the `target`
  branch after the pipeline exits, regardless of outcome, so the verifier always decides.

Attempts 1–3 (jobs `2026-10-16__05-09-03`, `__10-13-12`, `__14-40-36`) show the same
signature; attempt 4 (`2026-10-16__19-46-49`, trial `__Z6MKiXX`) is curated here. The
retry budget was proven irrelevant (4, 8, and 6 retries used — identical outcome), so
further reruns are on hold until the fixes above land.

## Adding a run

1. `cp -r jobs/<timestamp> results/runs/<timestamp>` once the run is complete and curated.
2. Add a row to the tables above and a short note (what made the run interesting: route,
   phase behavior, failures).
