# Amalgamator Tasks

Harbor dataset of bug-fix **backport** tasks for benchmarking [Amalgamator](https://github.com/amalgamator-ai/amalgamator) — or any agent that can drive a git repository plus a shell build/test command.

Each task is one real backport: a fix commit on the source branch, a `target` branch pinned to the state right before the human backport, the human backport itself as the golden solution, and an independent verifier that applies the candidate patch to a fresh worktree and runs the project's own build and tests. See the repo [README](../README.md) for how to run it and how to add tasks.

## Inventory

31 tasks total — all built, oracle-validated (31/31 golden patches score 1), and evaluated with GLM (31/31, see the repo [README](../README.md) Results section for the scoreboard and log locations).

### django/django (9)

| # | Task directory | Tier | Fix commit | Golden backport | Status |
|---|----------------|------|------------|-----------------|--------|
| 1 | `django-password-reset-fix` | Easy | `9305c0e12d43` | `92d3430f1217` (human) | available |
| 2 | `django-cve-2022-28346-40x` | Easy | `93cae5cb2f9a` | `800828887a05` (human) | available |
| 3 | `django-cve-2023-24580-32x` | Easy | `628b33a854a9` | `a665ed5179f5` (human) | available |
| 4 | `django-duplicate-filenames-upload-15x` | Medium | `dd0c3f4ee1a3` | `26cd48e166ac` (human) | available |
| 5 | `django-cve-2018-7537-18x` | Medium | `94c5da1d17a6` | `d17974a287a6` (human) | available |
| 6 | `django-cve-2022-28346-22x` | Medium | `93cae5cb2f9a` | `2c09e68ec911` (human) | available |
| 7 | `django-adminurlfieldwidget-autoescape-15x` | Hard | `cbe6d5568f4f` | `90363e388c61` (human) | available |
| 8 | `django-csrf-security-11x` | Hard | `818e70344e71` | `408c5c873ce1` (human) | available |
| 9 | `django-remoteuser-logout-14x` | Hard | `5307ce565fbe` | `c9e3b9949cd5` (human) | available |

Rows 2 and 6 backport the *same* fix to different branches — deliberately kept as a pair to compare how target-branch drift changes difficulty at fixed fix complexity.

### crate/crate (9)

| # | Task directory | Tier | Fix commit | Golden backport | Status |
|---|----------------|------|------------|-----------------|--------|
| 1 | `crate-return-0-instead-of-null` | Easy | `3247cc6e48a2` | `1974dab17d6a` (human) | available |
| 2 | `crate-ensure-that-joingraph-adds-only-edges` | Easy | `4f42b38d70b1` | `c08290ccf452` (human) | available |
| 3 | `crate-account-for-direct-buffers-when-constructing` | Easy | `834640ed7b3f` | `2c1210da4dc9` (human) | available |
| 4 | `crate-fix-memory-based-pause-resume` | Medium | `a2f572fc4803` | `c0d5e58eb817` (human) | available |
| 5 | `crate-fix-replication-from-translog-for-integral` | Medium | `43de35c74ab4` | `b90a7a24c6d9` (human) | available |
| 6 | `crate-fix-error-handling-on-insert` | Medium | `f110187717d7` | `ee82e9c66ddd` (human) | available |
| 7 | `crate-preserve-detailedquery-in-collect-on-prune` | Hard | `a9199b9f781a` | `729957bc6228` (human) | available |
| 8 | `crate-fix-a-race-condition-swallowing-pgwire` | Hard | `5afcf36990a9` | `8998913dfc61` (human) | available |
| 9 | `crate-fix-partition-by-cols-not` | Hard | `422c9d48ae8a` | `d17ad1dfa72d` (human) | available |

### cri-o/cri-o (10)

Same fix backported to multiple release branches where available, so target-branch drift can be compared at fixed fix complexity (the `-1-31`/`-1-32` and `-1-30`/`-1-31` pairs).

| # | Task directory | Tier | Fix commit | Golden backport | Status |
|---|----------------|------|------------|-----------------|--------|
| 1 | `crio-coco-imageserver-release-1-36` | Hard | `d92e5f4456` | amalgamator reference run, 2026-09-05 | available |
| 2 | `crio-fix-deadlock-when-the-container-is-release-1-30` | Easy | `1e751b490b2f` | human backport on release-1.30 | available |
| 3 | `crio-fix-deadlock-when-the-container-is-release-1-31` | Medium | `1e751b490b2f` | human backport on release-1.31 | available |
| 4 | `crio-hack-build-rpms-sh-update-release-1-29` | Easy | `8d3a11eef066` | human backport on release-1.29 | available |
| 5 | `crio-highperformancehooks-fix-irq-smp-affinity-race-release-1-31` | Hard | `3dce7d856a21` | human backport on release-1.31 | available |
| 6 | `crio-ocpbugs-62150-server-ignore-etc-passwd-release-1-31` | Easy | `9d7aa99d0def` | human backport on release-1.31 | available |
| 7 | `crio-runtimehandlerhooks-save-whether-irq-balance-enable-release-1-31` | Medium | `f725059649bd` | human backport on release-1.31 | available |
| 8 | `crio-runtimehandlerhooks-save-whether-irq-balance-enable-release-1-32` | Hard | `f725059649bd` | human backport on release-1.32 | available |
| 9 | `crio-server-run-post-stop-hooks-before-release-1-31` | Medium | `8f893226bc9a` | human backport on release-1.31 | available |
| 10 | `crio-server-run-post-stop-hooks-before-release-1-32` | Hard | `8f893226bc9a` | human backport on release-1.32 | available |

### rpms/expat — CentOS Stream dist-git (3)

One CVE backported at three different drift distances: the same upstream fix (libexpat PR #1034, CVE-2025-59375 — expat's parser could be made to allocate unbounded dynamic memory) lands on three CentOS Stream package branches that carry expat 2.2.5, 2.5.0 and 2.7.1 respectively. Fix complexity is held constant; only the target drift varies. The baselines are Tomas Tomecek's exercise branches (`cNs-backport-test`) at gitlab.com/TomasTomecek/expat.

These tasks are structurally different from the rest of the dataset: the repo is a **dist-git** checkout (spec + lookaside `sources` + downstream patches), the fix arrives in `fix.patch` mode (the upstream diff ingested against a vendored upstream tree, orphan branch `upstream-base`, because the fix is not a commit in the dist-git repo), and a solution is an RPM packaging change — a downstream patch wired into `expat.spec`, or a version update — verified by a full package build (`centpkg local`, whose `%check` runs the complete `make check` suite).

| # | Task directory | Tier | Target | Golden (human downstream commit) | Status |
|---|----------------|------|--------|----------------------------------|--------|
| 1 | `expat-cve-2025-59375-c10s` | Medium | c10s, expat 2.7.1 | `eef65ac` — update to expat 2.7.3 | available |
| 2 | `expat-cve-2025-59375-c9s` | Hard | c9s, expat 2.5.0 (+7 patches) | `2d0719b` — downstream patch (+1483 lines) | available |
| 3 | `expat-cve-2025-59375-c8s` | Extreme | c8s, expat 2.2.5 (+20 patches) | `ac83027` — rebase to 2.5.0 with the fix | available |

## Tiering

Tiers are assigned from diff-similarity metrics measured between each upstream fix and its human backport — text similarity of the two diffs, file overlap, and size ratio:

- **Easy** — the backport is a near-identical re-apply (similarity ≳ 0.9, full file overlap).
- **Medium** — partial overlap; needs real conflict resolution or partial re-implementation (similarity ≈ 0.6–0.9).
- **Hard** — substantial re-implementation or API adaptation between branches (similarity ≲ 0.6, or the surrounding API changed shape).

The cri-o suite spans tiers by release-branch drift: the same fix appears at two drift distances (e.g. `-1-31` Medium / `-1-32` Hard pairs), and `crio-coco-imageserver-release-1-36` is Hard by construction: a 39-file feature backport (PR #9907, CoCO image-server support) that requires adapting a mainline API to the older release-1.36 codebase.

The expat suite is tiered by **target-branch drift** rather than diff similarity — the fix is identical across the three tasks:

- **Medium** (c10s) — expat 2.7.1 is close to the tree the fix was written against; the difficulty is the dist-git expression (version update with lookaside hashes, or a near-direct patch), not the adaptation.
- **Hard** (c9s) — expat 2.5.0 with a 7-patch stack: the fix must be genuinely re-expressed (~1500-line downstream patch in the human golden).
- **Extreme** (c8s) — expat 2.2.5 with a 20-patch stack, five versions of drift: the fix's code does not exist in recognizable form, so the solution is a rebase (the human golden rebases 2.2.5 → 2.5.0 and carries the fix on top) or a full version update — complete package surgery either way.

## Honesty notes

- `crio-coco-imageserver-release-1-36` has **no human backport** upstream on release-1.36; its golden is a previously human-verified amalgamator run. It validates task wiring and the difficulty, but it is not an independent human gold — unlike every django/crate task, whose goldens are the actual human backport commits.
- Every task gates on the repository's **full build and full test commands** — no module scoping. Each task's container is provisioned so the unpatched `target` baseline passes the full suite (verified per task), so any post-backport failure is attributable to the backport rather than environmental noise.
- The expat goldens are the **actual downstream package commits** for this CVE on the CentOS Stream branches (mirrored in gitlab.com/TomasTomecek/expat), not reconstructions. Two of them are not plain code patches: the c10s golden is a version update (the fix rides inside the expat 2.7.3 tarball), and the c8s golden bundles a rebase (2.2.5 → 2.5.0) with the fix — because that is what the humans actually did.
- The expat tasks provide the fix in **`fix.patch` mode**: the upstream diff of libexpat PR #1034, ingested against a vendored upstream source tree (orphan branch `upstream-base`). The fix is not a commit in the dist-git repo, which mirrors how a packager actually receives an upstream fix. The task repos are cloned `--single-branch`, so the post-fix branches (including a prior AI attempt at the c9s task in the upstream exercise repo) are not present locally; an agent with network access could still fetch them from the public remote, the same way it could look up any public repo's future — a known limitation of every public-repo benchmark.
- The c8s task builds against **vault.centos.org** — CentOS Stream 8 is EOL and its live mirrors are gone; the container repoints dnf at the vault.
