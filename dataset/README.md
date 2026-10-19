# The dataset

One directory per task, kept **flat** (Harbor scans only the immediate children of the `-p`
directory). Family grouping is encoded in the directory-name prefix. The raw case list —
including rows not yet built — is [`backports.csv`](backports.csv); this file is the
human-readable inventory.

Target: **31 cases** across four families. tensorflow rows in the CSV are excluded
(build-cost). 22 are built today; 9 are pending.

| Family | Tasks | Easy | Medium | Hard | Extreme | Built |
|---|---|---:|---:|---:|---:|---:|
| django/django | 9 | 3 | 3 | 3 | – | 9 |
| crate/crate | 9 | 3 | 3 | 3 | – | 9 |
| cri-o/cri-o | 10 | 3 | 3 | 4 | – | 1 |
| rpms/expat (CentOS Stream) | 3 | – | 1 | 1 | 1 | 3 |
| **Total** | **31** | 9 | 10 | 11 | 1 | **22** |

Every case is a **real, human-verified backport**: `source` = the original fix, `target` =
the branch pinned just before the human backport, golden = the human backport's diff.
Difficulty tiers come from diff-similarity metrics between fix and backport (text
similarity, file overlap, size ratio): **Easy** ≈ near-identical re-apply, **Medium** ≈
partial overlap needing real conflict resolution, **Hard** ≈ substantial re-implementation.
The expat suite instead holds the fix constant (CVE-2025-59375) and varies **target drift**.

## Per-family gates

Full build + complete test suite, never module-scoped. If a container can't run the full
suite, that's a container defect to fix — not a reason to scope down.

| Family | Source → target | Build | Test |
|---|---|---|---|
| django | fix on `main` → release branch (`stable/1.1.X` … `stable/4.0.x`) at `backport^` | — (pure Python; era interpreter built in-image) | the era interpreter (py2.7 / py3.9) runs the complete `runtests.py` suite, with in-image era-fidelity repairs: era sqlite, py2 compileall pre-pass, tzdata-legacy, non-root suite where tests require it, /etc/hosts pin for 1.4's live-URL tests — see `tools/gen_django_tasks.py` |
| crate | fix on `main` → release branch at `backport^` | `crate-mvn test-compile` (all modules) | `crate-mvn test` — full suite, 10,294 tests |
| cri-o | fix on `main` → release branch | full-tree `go build` (vendor mode; only bats/e2e dirs excluded) | full-tree `go test -short -count=1` |
| expat | upstream patch vs vendored tree (`upstream-base`) → dist-git branch pre-backport | `centpkg sources && prep` | `centpkg local` — full RPM build incl. `%check` = complete `make check` |

## Inventory

### django/django (9) — all built via `tools/gen_django_tasks.py`

| Task directory | Tier | Fix | Golden (human) | Status |
|---|---|---|---|---|
| `django-password-reset-fix` | Easy | `9305c0e12d43` | `92d3430f1217` | available |
| `django-cve-2022-28346-40x` | Easy | `93cae5cb2f9a` | `800828887a05` | available |
| `django-cve-2023-24580-32x` | Easy | `628b33a854a9` | `a665ed5179f5` | available |
| `django-duplicate-filenames-upload-15x` | Medium | `dd0c3f4ee1a3` | `26cd48e166ac` | available |
| `django-cve-2018-7537-18x` | Medium | `94c5da1d17a6` | `d17974a287a6` | available |
| `django-cve-2022-28346-22x` | Medium | `93cae5cb2f9a` | `2c09e68ec911` | available |
| `django-adminurlfieldwidget-autoescape-15x` | Hard | `cbe6d5568f4f` | `90363e388c61` | available |
| `django-csrf-security-11x` | Hard | `818e70344e71` | `408c5c873ce1` | available |
| `django-remoteuser-logout-14x` | Hard | `5307ce565fbe` | `c9e3b9949cd5` | available |

`django-cve-2022-28346-40x` and `-22x` backport the *same* fix to different branches
(4.0 vs 2.2) — a deliberate pair to isolate target-drift difficulty at fixed fix
complexity. Targets span `stable/1.1.X` … `stable/4.0.x`, one interpreter per era
(py2.7 for 1.1–1.8, py3.9 for 2.2–4.0); the pre-2013-09-18 1.5.x pin carries
upstream's own #21118 test-isolation fixlet (see the generator's TREE_FIXES).

### crate/crate (9) — all built via `tools/gen_crate_tasks.py`

| Task directory | Tier | Fix | Golden (human) |
|---|---|---|---|
| `crate-return-0-instead-of-null` | Easy | `3247cc6e48a2` | `1974dab17d6a` |
| `crate-ensure-that-joingraph-adds-only-edges` | Easy | `4f42b38d70b1` | `c08290ccf452` |
| `crate-account-for-direct-buffers-when-constructing` | Easy | `834640ed7b3f` | `2c1210da4dc9` |
| `crate-fix-memory-based-pause-resume` | Medium | `a2f572fc4803` | `c0d5e58eb817` |
| `crate-fix-error-handling-on-insert` | Medium | `f110187717d7` | `ee82e9c66ddd` |
| `crate-fix-replication-from-translog-for-integral` | Medium | `43de35c74ab4` | `b90a7a24c6d9` |
| `crate-fix-a-race-condition-swallowing-pgwire` | Hard | `5afcf36990a9` | `8998913dfc61` |
| `crate-preserve-detailedquery-in-collect-on-prune` | Hard | `a9199b9f781a` | `729957bc6228` |
| `crate-fix-partition-by-cols-not` | Hard | `422c9d48ae8a` | `d17ad1dfa72d` |

### cri-o/cri-o (10)

| Task directory | Tier | Fix | Golden | Status |
|---|---|---|---|---|
| `crio-coco-imageserver-release-1-36` | Hard | `d92e5f44…` | CoCo 1.36 imageserver fix | available |
| — | Easy | `1e751b490b` | `818fbcadf1dd` (human) | planned |
| — | Easy | `9d7aa99d0d` | `da5b9878135a` (human) | planned |
| — | Easy | `8d3a11eef0` | `2078d1e5c0e` (human) | planned |
| — | Medium | `1e751b490b` | `103e03f8abc` (human) | planned |
| — | Medium | `f725059649` | `16864a7b964` (human) | planned |
| — | Medium | `8f893226bc` | `469b85cece5` (human) | planned |
| — | Hard | `3dce7d856a` | `a64143a74b4` (human) | planned |
| — | Hard | `f725059649` | `ef8420347c3` (human) | planned |
| — | Hard | `8f893226bc` | `e01b6e570b0` (human) | planned |

Three fixes appear twice each (different target branches) — deliberate pairs, as in django.

### rpms/expat (3) — CVE-2025-59375 at three levels of target drift

| Task directory | Tier | Base | Golden (human) | Route |
|---|---|---|---|---|
| `expat-cve-2025-59375-c10s` | Medium | expat 2.7.1 (Stream 10) | `eef65ac` | version bump |
| `expat-cve-2025-59375-c9s` | Hard | expat 2.5.0 (Stream 9) | `2d0719b` | downstream patch |
| `expat-cve-2025-59375-c8s` | Extreme | expat 2.2.5 (Stream 8) | `ac83027` | rebase-bundled |

The same upstream fix ([libexpat PR #1034](https://github.com/libexpat/libexpat/pull/1034)),
backported onto CentOS Stream dist-git branches of increasing drift. Pins and golden commits
per task are recorded in each task's `provenance.yaml` (outside the image).

## Prompt policy

`bug_description` is written at CVE-ticket level: affected package/version, a one-line bug
class, where the fix patch lives, the target branch, and the pass bar. **No** solution
routes, no exact commands, no fix internals — an over-scaffolded prompt measures
instruction-following, not backporting skill. Real-world provenance goes in
`provenance.yaml` outside the image, because `case.yaml` is copied into the container and
readable by the agent under test.

## Known gaps (tracked)

- expat: origin remote still present in the Dockerfiles (points at the exercise repo with
  finished fixes) — `git remote remove origin` hardening pending.
- expat c8s: `%prep` is non-idempotent (the downstream CVE-2023-52425 patch creates
  `testdata/largefiles/*` outside `%setup`'s cleanup), so the canonical build command is
  stateful — re-running it on an already-prepped tree fails. A human backporter never
  hits this; agents that end with a successful build do. Cost us 4 reward-0 runs before
  diagnosis — see [`results/README.md`](../results/README.md). Fix pending: self-cleaning
  build command (`rm -rf <builddir> && …`).
- cri-o CoCo 1.36: golden is an amalgamator-produced patch, not a human backport.
- crate: `AzureCopyIntegrationTest` (OpenDAL native lib, x64-only) fails under arm64 Docker —
  environment decision pending (amd64 emulation vs x86 host).
