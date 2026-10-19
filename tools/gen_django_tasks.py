#!/usr/bin/env python3
"""Generate Harbor tasks for the django/django rows of backports.csv.

Per row:  original fix commit (on main or a newer branch)  ->  human backport
commit (on a release branch).
  target  = backport^   (the exact pre-backport state of the release branch)
  golden  = diff backport^..backport   (the real human backport)
  source  = original fix commit

Leak-proofing: same scheme as gen_crate_tasks.py -- the container does NOT
clone the full repo. It fetches only the fix commit and the target commit
(shallow, by SHA), so the human backport commit -- a child of target -- is
not in the container's object store, and the remote is removed afterwards.

Fetch depths are EXACT, computed from a full local clone: both histories
bottom out at the merge-base of fix and target. This matters because
Amalgamator's phase 0 runs `git merge-base source target` (auto_bug_fix/
run_bug_fix.py) and raises on an empty result -- the expat orphan-branch
incident -- so the two fetched histories must connect inside the container.
Measured cost: <= 8s / 85MB for the deepest slice in this family.

Two container profiles by era:
  py2 -- Django 1.1/1.4/1.5/1.8 targets. Python 2.7 interpreter prebuilt in
        the python:2.7.18-slim stage and copied onto ubuntu:24.04 (compiling
        2.7 from source blew past Harbor's ~10 min environment timeout, and
        the buster base's apt repos are archived). The interpreter's
        _hashlib needs libssl1.1/libcrypto1.1, copied in from the same
        stage. Unversioned `python`/`pip` resolve to 2.7; `python3`/`pip3`
        stay ubuntu's 3.12, which the adapter's amalgamator install needs.
  py3 -- Django 2.2/3.2/4.0 targets (the newest interpreter all three
        support). Python 3.9.13 prebuilt in the python:3.9.13-slim-bullseye
        stage, copied onto ubuntu:24.04; the image's unversioned
        python3/pip/pip3 symlinks are dropped so `python3`/`pip3` keep
        resolving to ubuntu's 3.12 for the adapter. The suite is always
        invoked as `python3.9`. Pinned to the exact 3.9.13 patchlevel and
        the bullseye base for era fidelity: later 3.9 patchlevels break
        these 2022-era suites (3.9.14+ html.parser malformed-tag changes,
        3.9.17+ urlsplit IPv6 hardening that a pre-4.2 URLValidator calls
        unguarded), and the plain 3.9-slim tag now tracks Debian trixie,
        whose OpenSSL 3.5 ubuntu:24.04 can't load (bullseye's OpenSSL 1.1
        libs are copied in, same trick as py2).

Test gate: the project's own runner over the full suite -- never
module-scoped. Newer branches use the repo's ready-made sqlite settings
module (`--settings=test_sqlite`): the sqlite settings define no CACHES
(LocMemCache default) and the runner only includes GeoDjango tests when the
settings use spatial backends, so this minimal container exercises
everything that is runnable on sqlite. Django 1.1.X predates
tests/test_sqlite.py entirely, so that task instead uses an image-provided
settings module (dj11settings.py, just DATABASE_ENGINE) -- the invocation
1.1's own docs/internals/contributing.txt prescribes.

Era sqlite: the interpreter's _sqlite3 otherwise resolves libsqlite3.so.0
against ubuntu:24.04's 3.45, which normalizes PRAGMA table_info's
declared-type column to canonical case (INTEGER/TEXT) -- the 1.8/2.2/3.2/
4.0 targets' inspectdb tests temporarily swap in a plain lowercase-keyed
data_types_reverse dict and then miss. Both profiles ship their python
stage's own libsqlite3.so.0 in /opt/era-sqlite, and the test command runs
the suite with LD_LIBRARY_PATH pointing there. Scoped to the suite: the
adapter's ubuntu python3.12 keeps the system libsqlite3.

Non-root suite execution: modern-era Django asserts that
readonly/unreadable paths raise PermissionError
(file_uploads.DirectoryCreationTests.test_readonly_root,
template_tests.FileSystemLoaderTests.test_permissions_error), which is
never true when the container runs as root. The py3 test command chowns
the root-built worktree and runs the suite as an unprivileged djangotests
user. The 1.8 target has the same shape on the py2 side --
view_tests' test_template_loader_postmortem_notreadable chmod-000s a
template and expects the debug view to report it unreadable -- so its
spec sets nonroot=True and the py2 Dockerfile grows the same useradd
(the 1.1/1.4/1.5 suites pass as root, verified).

tzdata-legacy (py2 only): since Ubuntu 23.10 the legacy zone names live
in a separate tzdata-legacy package; base tzdata has America/New_York
but NOT US/Eastern. The 1.4/1.8 tzinfo tests set TZ=US/Eastern
(tests/regressiontests/utils/tzinfo.py, a 2012 test for #16899), and on
24.04 time.tzset() yields an empty tzname and tz=UTC there. The py2
Dockerfile apt-installs tzdata-legacy to restore the 2012-era zone
table.

Internet drift (1.4 only): modeltests/validation/tests.py (deprecated
URLValidator verify_exists, removed in 1.5) expects
https://www.example.com/ to be a broken link -- true in 2012, 200 today
-- while the same module's test_correct_url_value_passes fetches
http://www.google.com/ and must SUCCEED, so the suite cannot run
offline. The 1.4 test commands pin www.example.com to 127.0.0.2
(unroutable loopback, instant ECONNREFUSED) in /etc/hosts at test time:
docker regenerates /etc/hosts on container start, so baking it into the
image does not survive.

Tree-level repairs (TREE_FIXES): a pin's suite can carry a known
upstream bug unrelated to the task's fix -- one that no environment
knob can paper over because it lives in the tree itself. The 1.5.x pins
before 2013-09-18 are the case in point: #21118, a plain
unittest.TestCase creating a User that is never rolled back, leaking a
row into every later module (contrib.formtools' wizard tests count
users). For those, the generator embeds upstream's own later fix
(extracted verbatim from this repo) as a build-time commit on the
target branch -- test-file-only, disjoint from the fix/golden pair, and
shared verbatim by the oracle and the agent, so both start from the
same repaired tree.

tblib: Django's parallel runner pickles exc_info between workers, so
without tblib the first failing test crashes the whole run ("cannot pickle
'traceback' object") -- and modern tblib (3.x) changes exception pickling
in a way that fails test_runner's own pickling-detection tests. The py3
deps pin the era-correct tblib==1.7.0.

py2 compileall (py2 only): CPython 2's fp-based compilation (script
execution and import) honors a PEP 263 cookie on line 2 only when line 1
is a comment or blank; a one-line docstring before it silently suppresses
the declaration. tests/regressiontests/utils/jslex.py (every 1.4+ target)
has exactly that shape and dies on import from a fresh checkout with
"Non-ASCII character ... but no encoding declared" -- on any py2
patchlevel (verified on 2.7.13 and 2.7.18, stock and in-image). String-
based compilation (py_compile/compileall) reads the first two lines
positionally and is unaffected, and py2 imports prefer a mtime-valid .pyc
over reparsing source, so the py2 test command compileall's the tree
before running the suite. This also mirrors the only state these
2012-2015 suites ever ran in: long-lived py2 checkouts always carried
.pyc files.

Suite dependency gates: the 1.8 target's runtests.py hard-exits before
any test unless `from django.test import mock` succeeds (py2: the
standalone mock package), and its USE_TZ machinery needs pytz -- the 18x
spec pins mock==2.0.0 + pytz==2018.4 (the 1.8.19 era). The 2.2 target's
tests/admin_inlines/tests.py imports selenium.common.exceptions
unconditionally at module level, so the 22x spec adds selenium==3.141.0
(the selenium-tagged tests themselves still skip without a browser).

Usage: gen_django_tasks.py [--repo PATH] [--csv PATH] [--out DIR] [--only SHA8]
"""
import argparse, csv, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = ROOT.parent / "benchmark-repos" / "django"
DEFAULT_CSV = ROOT.parent / "backport-agent-leaderboard" / "dataset" / "backports.csv"

DIFFICULTY = {"Easy": "easy", "Medium": "medium", "Hard": "hard"}

# Per-(fix, backport) task spec: directory slug, the release branch the
# backport landed on, the container profile, and (py3 only) the suite's
# runtime dependencies with era-appropriate pins.
SPECS = {
    ("9305c0e12d43c4df999c3301a1f0c742264a657e", "92d3430f12171f16f566c9050c40feefb830a4a3"):
        dict(slug="django-password-reset-fix", branch="stable/1.4.x", py="py2", deps=[],
             # 2012 internet reality: the deprecated URLValidator
             # verify_exists tests (removed in 1.5) expect
             # https://www.example.com/ to be a broken link; the host now
             # serves 200. The test command pins it to an unroutable
             # loopback address (see hosts_prelude) so the fetch fails the
             # way it did when this branch was live.
             hosts_pin=True),
    ("93cae5cb2f9a4ef1514cf1a41f714fef08005200", "800828887a0509ad1162d6d407e94d8de7eafc60"):
        dict(slug="django-cve-2022-28346-40x", branch="stable/4.0.x", py="py3",
             deps=["pytz==2022.7.1", "sqlparse==0.4.4", "asgiref==3.5.2", "tblib==1.7.0"]),
    ("628b33a854a9c68ec8a0c51f382f304a0044ec92", "a665ed5179f5bbd3db95ce67286d0192eff041d8"):
        dict(slug="django-cve-2023-24580-32x", branch="stable/3.2.x", py="py3",
             deps=["pytz==2022.7.1", "sqlparse==0.4.4", "asgiref==3.5.2", "tblib==1.7.0"]),
    ("dd0c3f4ee1a30c1a1e6055061c6ba6e58c6b54d1", "26cd48e166ac4d84317c8ee6d63ac52a87e8da99"):
        dict(slug="django-duplicate-filenames-upload-15x", branch="stable/1.5.x", py="py2", deps=[]),
    ("94c5da1d17a6b0d378866c66b605102c19f7988c", "d17974a287a6ea2e361daff88fcc004cbd6835fa"):
        dict(slug="django-cve-2018-7537-18x", branch="stable/1.8.x", py="py2",
             # runtests.py hard-gates on `from django.test import mock` (py2:
             # the standalone mock package), and the suite's USE_TZ machinery
             # needs pytz. Era pins: 1.8.19's April 2018 window.
             deps=["mock==2.0.0", "pytz==2018.4"],
             # view_tests' template-loader postmortem test chmod-000s a
             # template and expects the debug view to report it unreadable --
             # never true as root (same class of failure as the py3
             # PermissionError tests, but without the assertRaises).
             nonroot=True),
    ("93cae5cb2f9a4ef1514cf1a41f714fef08005200", "2c09e68ec911919360d5f8502cefc312f9e03c5d"):
        dict(slug="django-cve-2022-28346-22x", branch="stable/2.2.x", py="py3",
             # selenium: 2.2's tests/admin_inlines/tests.py imports
             # selenium.common.exceptions unconditionally at module level (the
             # lazy-import refactor only landed later), so without it the
             # whole module errors out of the suite even though the
             # selenium-tagged tests themselves skip without a browser.
             deps=["pytz==2022.7.1", "sqlparse==0.4.4", "tblib==1.7.0",
                   "selenium==3.141.0"]),
    ("cbe6d5568f4f5053ed7228ca3c3d0cce77cf9560", "90363e388c61874add3f3557ee654a996ec75d78"):
        dict(slug="django-adminurlfieldwidget-autoescape-15x", branch="stable/1.5.x", py="py2", deps=[],
             # This pin (2013-09-15) predates upstream's #21118 test-
             # isolation fix by three days: the leaking
             # simplelazyobject.py user breaks formtools' user-count
             # assertions in the full-suite order. TREE_FIXES["21118"]
             # repairs the tree with upstream's own fix at build time.
             tree_fix="21118"),
    ("818e70344e7193f6ebc73c82ed574e6ce3c91afc", "408c5c873ce1437c7eee9544ff279ecbad7e150a"):
        dict(slug="django-csrf-security-11x", branch="stable/1.1.X", py="py2", deps=[],
             settings="dj11settings"),
    ("5307ce565fbedb9cc27cbe7c757b41a00438d37c", "c9e3b9949cd55f090591fbdc4a114fcb8368b6d9"):
        dict(slug="django-remoteuser-logout-14x", branch="stable/1.4.x", py="py2", deps=[],
             hosts_pin=True),  # see the password-reset spec's note
}

FETCH_BLOCK = """\
# Shallow, by-SHA fetch of only the two commits this case needs. The human
# backport ({backport8}) is a child of target and is never fetched, so it is
# not discoverable in the container (no `git log --all`, no remote to fetch
# from once the remote is removed below).
#   source = {orig8}   original fix (on {source_loc})
#   target = {parent8}   pre-backport tip of {branch}
# Depths are exact: both histories bottom out at the fix<->target merge
# base ({mb8}), which Amalgamator's phase-0 `git merge-base source target`
# requires to connect.
RUN git init -q /workspace/django && cd /workspace/django && \\
    git remote add origin https://github.com/django/django.git && \\
    git fetch -q --depth={ds} origin {orig} && git branch source FETCH_HEAD && \\
    git fetch -q --depth={dt} origin {parent} && git branch target FETCH_HEAD && \\
    git checkout -q target && \\
    git remote remove origin
"""

DOCKERFILE_PY2 = """\
# Prebuilt Python 2.7: this target branch's Django is Python-2-only syntax
# (`except ImportError, e:` etc.). Copied in below instead of compiled from
# source -- compiling blew past Harbor's ~10 min environment timeout, and
# python:2.7.18-slim's own base OS (buster) has archived apt repos, so the
# image is ubuntu:24.04 + the prebuilt interpreter.
FROM python:2.7.18-slim AS python

FROM ubuntu:24.04

WORKDIR /workspace

# UTF-8 locale: under the default C locale, Python 2.7's filesystem
# encoding is ascii, and the suite's unicode-filename tests die inside
# os.stat() with UnicodeEncodeError. C.UTF-8 ships with ubuntu (no
# locale-gen needed).
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

COPY case.yaml /workspace

# yq parses case.yaml (tests + solution); python3/pip3 (ubuntu's 3.12) are
# for the harbor adapter's amalgamator install (amalgamator needs >= 3.12).
# tzdata-legacy: the tzinfo tests set TZ=US/Eastern themselves, and since
# 23.10 ubuntu splits the legacy zone names (US/*, ...) out of the main
# tzdata package -- without it glibc silently falls back to UTC with an
# empty tzname and test_16899 fails.
RUN apt-get update && apt-get install -y curl wget git yq python3 python3-pip tzdata-legacy

# Copy in the prebuilt Python 2.7 interpreter. The image's unversioned
# `python`/`pip` resolve to 2.7; `python3`/`pip3` stay ubuntu's 3.12.
COPY --from=python /usr/local /usr/local
# The interpreter's _hashlib (hashlib.sha256/md5, which Django's password
# hashers need) is linked against libssl.so.1.1 / libcrypto.so.1.1, which
# ubuntu:24.04 doesn't ship (it's on OpenSSL 3.x). Grab the matching 1.1
# libs from the same python2 stage's base OS.
COPY --from=python /usr/lib/*/libssl.so.1.1 /usr/lib/*/libcrypto.so.1.1 /usr/lib/
# Era sqlite for the suite (same rationale as the py3 profile's
# /opt/era-sqlite note: ubuntu:24.04's 3.45 normalizes PRAGMA table_info's
# declared types to canonical case, and the 1.8 target's inspectdb tests
# key on the declared casing).
COPY --from=python /usr/lib/*/libsqlite3.so.0 /opt/era-sqlite/
RUN ldconfig && LD_LIBRARY_PATH=/opt/era-sqlite python2.7 -c "import hashlib, sqlite3, ssl; hashlib.sha256('x'); assert sqlite3.sqlite_version_info < (3, 40), sqlite3.sqlite_version; print('python2.7 + hashlib + sqlite3 ' + sqlite3.sqlite_version + ' + ssl OK')"

{deps_block}

{user_block}"""

# Only the 1.8 target's py2 Dockerfile interpolates this: its suite includes
# view_tests' template-loader postmortem test, which chmod-000s a template
# and expects the debug view to report it unreadable -- never true as root.
# (The py3 profile always creates this user; same mechanism, different
# failing tests.)
USER_BLOCK_PY2 = """\\
# The suite runs as this unprivileged user (the test command chowns the
# worktree and drops to it via runuser), for the same reason as the py3
# profile: a test asserts a chmod-000'd file stays unreadable, which is
# never true as root.
RUN useradd -m djangotests
"""

DOCKERFILE_PY3 = """\
# Prebuilt Python 3.9: the newest interpreter every modern-era target branch
# in this family supports (Django 2.2, 3.2 and 4.0 all support 3.9). Copied
# onto ubuntu:24.04 rather than FROM python:3.9-slim so the adapter's
# amalgamator install keeps using ubuntu's python3.12. Pinned to the exact
# 3.9.13-slim-bullseye tag for era fidelity on both axes:
#   - patchlevel: 3.9.13 (June 2022) is the last release before the changes
#     that break these 2022-era suites -- 3.9.14+ reworked html.parser's
#     handling of malformed tags (utils_tests test_strip_tags, test_utils
#     test_parsing_errors), and 3.9.17+ hardened urlsplit() to raise
#     ValueError on invalid bracketed IPv6 hosts, which a pre-4.2
#     URLValidator calls unguarded (validators tests).
#   - bullseye base: the plain python:3.9-slim tag now tracks Debian trixie,
#     whose libcrypto.so.3 (OpenSSL 3.5) ubuntu:24.04 (OpenSSL 3.0) cannot
#     load -- `import ssl`, and with it `pip install`, fails with "version
#     OPENSSL_3.3.0 not found". Bullseye's OpenSSL 1.1 libs are copied in
#     below (same trick as the py2 profile).
FROM python:3.9.13-slim-bullseye AS python

FROM ubuntu:24.04

WORKDIR /workspace

# UTF-8 locale (see the py2 profile's note for the failure mode; python3.9
# would coerce the C locale itself via PEP 538, but be explicit).
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

COPY case.yaml /workspace

# yq parses case.yaml (tests + solution); python3/pip3 (ubuntu's 3.12) are
# for the harbor adapter's amalgamator install (amalgamator needs >= 3.12).
RUN apt-get update && apt-get install -y curl wget git yq python3 python3-pip

# Copy in the prebuilt Python 3.9 interpreter, then drop the image's
# unversioned python3/pip/pip3 so `python3`/`pip3` keep resolving to
# ubuntu's 3.12 for the adapter. The suite is always invoked as python3.9
# (bare `python` still resolves to 3.9).
COPY --from=python /usr/local /usr/local
# Runtime libs this interpreter needs that ubuntu:24.04 doesn't ship:
# OpenSSL 1.1 for _hashlib/_ssl (see the FROM note), libffi 7 for _ctypes
# (Django's own test/runner.py imports it; ubuntu is on libffi 8), and era
# sqlite for the suite: _sqlite3 would otherwise resolve libsqlite3.so.0
# against ubuntu:24.04's 3.45, which normalizes PRAGMA table_info's
# declared-type column to canonical case (INTEGER/TEXT) -- these targets'
# inspectdb tests swap in a plain lowercase-keyed data_types_reverse dict
# and then miss. The suite runs with LD_LIBRARY_PATH=/opt/era-sqlite (see
# the test command); scoped there so the adapter's ubuntu python3.12 keeps
# the system libsqlite3.
COPY --from=python /usr/lib/*/libssl.so.1.1 /usr/lib/*/libcrypto.so.1.1 /usr/lib/*/libffi.so.7 /usr/lib/
COPY --from=python /usr/lib/*/libsqlite3.so.0 /opt/era-sqlite/
RUN rm -f /usr/local/bin/python3 /usr/local/bin/pip /usr/local/bin/pip3 && \\
    ldconfig && LD_LIBRARY_PATH=/opt/era-sqlite python3.9 -c "import ctypes, hashlib, ssl, sqlite3; hashlib.sha256(b'x'); assert sqlite3.sqlite_version_info < (3, 38), sqlite3.sqlite_version; print('python3.9 + ctypes + hashlib + ssl + sqlite3 ' + sqlite3.sqlite_version + ' OK')"

# Test-suite runtime dependencies for this Django version ({deps}).
RUN python3.9 -m pip install --no-cache-dir {deps}

# The suite runs as this unprivileged user (the test command chowns the
# worktree and drops to it via runuser): modern-era Django includes tests
# that assert readonly/unreadable paths raise PermissionError
# (file_uploads.DirectoryCreationTests.test_readonly_root,
# template_tests.FileSystemLoaderTests.test_permissions_error), which never
# happens when the whole container runs as root.
RUN useradd -m djangotests
"""

DOCKERFILE_TAIL = """\
{settings_block}
# Amalgamator (and solve.sh) need a git identity to commit cherry-picks.
RUN git config --global user.email "amalgamator-bench@redhat.com" && \\
    git config --global user.name "Amalgamator Bench"

{fetch_block}
{tree_fix_block}RUN mkdir /tmp/amalgamator-django
"""

# Tree-level repairs for pins whose suite carries a known upstream bug
# UNRELATED to the task's fix/golden pair: applied at image build as a
# commit on the target branch, so the oracle (solve.sh) and the agent
# (Amalgamator) both build their worktrees from the same repaired tree.
# Keyed by the upstream ticket. The patch bytes are extracted verbatim
# from the local repo (diff fixcommit^..fixcommit) at generation time --
# never hand-transcribed; git apply is strict about context lines.
TREE_FIXES = {
    # django #21118: at 1.5.x pins before 2013-09-18,
    # tests/regressiontests/utils/simplelazyobject.py ran
    # test_pickle_py2_regression inside a plain unittest.TestCase, whose
    # User.objects.create_user() is never rolled back -- the row leaks
    # into every later module in the full-suite order, and
    # contrib.formtools' wizard tests count users (3 where they created
    # 2), so the full gate can never pass at those pins. Upstream fix:
    # 72f7932cfbe ("Fixed #21118 -- Isolated a test that uses the
    # database"), backport of 4f40b97d97. Only the pre-2013-09-18 1.5.x
    # pins need it: the 1.4 pins predate the pickling test entirely,
    # later 1.5.x pins ship the fix, and 1.8+ moved these tests.
    "21118": dict(
        patch_name="tree-fix-21118.patch",
        fix_commit="72f7932cfbe079f5063a2f1b4c09b520d99f5e42",
        commit_subject="Isolated a test that uses the database (refs #21118)",
    ),
}

TREE_FIX_BLOCK = """\
# Pre-existing suite bug at this pin, unrelated to the task's fix (see
# the generator's TREE_FIXES note): repaired here with upstream's own
# fix, committed onto target so the oracle and the agent start from the
# exact same tree.
COPY {patch_name} /tmp/
RUN cd /workspace/django && git apply /tmp/{patch_name} && \\
    git add -A && git commit -q -m "{commit_subject}" && \\
    rm /tmp/{patch_name}
"""

# Only the Django 1.1.X task needs an image-provided settings module: that
# branch predates tests/test_sqlite.py (the ready-made sqlite settings module
# every newer target branch ships). SETTINGS_BLOCK_11X goes into the
# Dockerfile; SETTINGS_11X is the module it copies in.
SETTINGS_BLOCK_11X = """\
# Django 1.1.X predates tests/test_sqlite.py, so the image provides the
# era-correct equivalent: 1.1's own docs/internals/contributing.txt says the
# runner needs a settings module only for DATABASE_ENGINE, and sqlite3 runs
# the test database in memory. Picked up via PYTHONPATH=/workspace.
COPY dj11settings.py /workspace/
"""

SETTINGS_11X = """\
# Minimal test settings for Django 1.1 (this branch predates
# tests/test_sqlite.py). Per this branch's own
# docs/internals/contributing.txt, the unit tests need a settings module
# "but only for database connection info, with the DATABASE_ENGINE setting",
# and with sqlite3 "a temporary database will be created in memory when
# running the tests." The runner overrides everything else it needs
# (ALWAYS_INSTALLED_APPS, ROOT_URLCONF, ...) itself.
DATABASE_ENGINE = 'sqlite3'

# The global_settings default is ''; a non-empty key for the few tests that
# sign or hash with it.
SECRET_KEY = 'django-tests-secret-key'
"""

# The suite invocation, embedded as build.test_command in case.yaml and
# eval'd by tests/test.sh from the worktree root. Both forms point the
# interpreter's _sqlite3 at the era-correct libsqlite3 in /opt/era-sqlite
# (see the Dockerfiles); the py3 form additionally drops to the
# unprivileged djangotests user for the PermissionError-asserting tests,
# after chowning the root-created worktree (Amalgamator/solve.sh build
# worktrees as root).
#
# The py2 form starts with a compileall pass because of a CPython 2
# tokenizer quirk: fp-based compilation (script execution and import)
# honors a PEP 263 cookie on line 2 only when line 1 is a comment or
# blank -- a one-line docstring before it silently suppresses the
# declaration. tests/regressiontests/utils/jslex.py (present in every
# 1.4+ target: `"""Tests for jslex."""` line 1, `# encoding: utf-8` line
# 2, non-ASCII test data line 26) therefore dies on import with
# "Non-ASCII character ... but no encoding declared" from a fresh
# checkout, on every py2 patchlevel (verified on 2.7.13 and 2.7.18,
# image and stock). String-based compilation (py_compile/compileall)
# reads the first two lines positionally and has no such quirk, and py2
# imports prefer a mtime-valid .pyc over reparsing the source -- so
# pre-compiling the tree both fixes the import and restores the only
# state these 2012-2015 suites ever actually ran in (long-lived py2
# checkouts always carried .pyc files). The nonroot form carries the
# same prefix when the task is py2 (the 1.8 target needs both the
# compileall and the unprivileged user; py3 nonroot commands never do
# and stay byte-identical to their oracle-validated form).
TEST_CMD_ROOT = (
    "{hosts_prelude}{python} -m compileall -q django tests && cd tests && "
    "env LD_LIBRARY_PATH=/opt/era-sqlite PYTHONPATH={pypath} "
    "{python} runtests.py --settings={settings}"
)

TEST_CMD_NONROOT = (
    "{compileall}chown -R djangotests . && cd tests && "
    "runuser -u djangotests -- env HOME=/home/djangotests "
    "LD_LIBRARY_PATH=/opt/era-sqlite PYTHONPATH={pypath} "
    "{python} runtests.py --settings={settings}"
)

CASE = """\
issue_id: "{slug}"
bug_description: >
  Backport the fix "{subject}" (commit {orig8}, branch 'source') onto branch
  'target' so that the project's complete test suite passes.

repository:
  source_path: /workspace/django
  workdir: /tmp/amalgamator-django

branches:
  source: source
  target: target

fix:
  commit: "{orig}"

build:
  # Django is pure Python: there is no build step, the test runner imports
  # and byte-compiles the tree.
  command: ""
  # The project's own runner over the complete suite -- never module-scoped.
  # GIS tests are only included by the runner when the settings use spatial
  # backends (sqlite never does), and with no CACHES defined the cache tests
  # run on LocMemCache. LD_LIBRARY_PATH points the interpreter's _sqlite3
  # at the era-correct libsqlite3 shipped in /opt/era-sqlite (modern sqlite
  # normalizes PRAGMA type casing and breaks the inspectdb tests; see the
  # Dockerfile). On py2 the command first compileall's the tree: py2's
  # import path ignores a PEP 263 cookie on line 2 when line 1 is a
  # docstring, which otherwise kills the jslex.py import on a fresh
  # checkout (string-based compilation and the .pyc it leaves behind are
  # unaffected). On py3 profiles and the 1.8 target the suite runs as the
  # unprivileged djangotests user (tests assert unreadable files stay
  # unreadable, which never happens as root), after chowning the root-built
  # worktree. The 1.4 commands prepend an /etc/hosts pin (www.example.com
  # -> 127.0.0.2): its deprecated verify_exists tests expect that host to
  # be a broken link (true in 2012, 200 today) while a sibling test
  # fetches google.com and must succeed, so the suite can't run offline
  # -- the pin restores the 2012 answer without touching the network.
  # PYTHONPATH: runtests.py imports `django` from the repo root,
  # one level up from tests/ -- plus, on 1.1.X only, /workspace, where the
  # image-provided settings module lives (that branch predates
  # tests/test_sqlite.py).
  test_command: "{test_command}"

model: "openai/your-model-here"
api_base: "https://your-endpoint.com/v1"

advanced:
  context_length: 200000
  command_timeout: 3600
  max_build_test_retries: 5
"""

TASK_TOML = """\
schema_version = "1.3"
# /tmp/amalgamator-django: the patched worktree (final repo state after the
#   agent's backport, whatever it ends up looking like).
# /workspace/amalgamator/runs: Amalgamator's own run archive -- tracker
#   JSONs, per-phase logs, the candidate diff, dossier.md. Harbor's own
#   trial.log truncates long command output, so this is where the full
#   per-phase record lives.
artifacts = ["/tmp/amalgamator-django", "/workspace/amalgamator/runs", "/workspace/case.yaml"]

[task]
name = "redhat-et/{slug}"
authors = [{{ name = "Surya Prakash Pathak", email = "supathak@redhat.com" }}]

[metadata]
difficulty = "{difficulty}"
difficulty_explanation = \"\"\"
{difficulty_cap} django/django backport ({reason}).
Original fix {orig8} on {source_loc} -> human backport {backport8} to {branch}.
Golden = the real human backport diff. Verification = the project's complete
test suite via `runtests.py --settings={settings}` on {python}.
\"\"\"
category = "programming"

[verifier]
timeout_sec = 3600.0

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
# Per run_bug_fix.py: worktree_path = $workdir/${issue_id}_${sanitized_target}
# where sanitized_target strips "origin/" and replaces "/" with "_" -- must
# match tests/test.sh exactly.
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


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True,
                          capture_output=True, text=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(DEFAULT_REPO))
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--out", default=str(ROOT / "dataset"))
    ap.add_argument("--only")
    a = ap.parse_args()

    template_test = (ROOT / "dataset" / "django-password-reset-fix" / "tests" / "test.sh").read_text()
    rows = [r for r in csv.DictReader(open(a.csv)) if r["repo"] == "django/django"]
    for r in rows:
        orig, back = r["Original Commit"], r["Backport Commit"]
        if a.only and not orig.startswith(a.only):
            continue
        spec = SPECS[(orig, back)]
        parent = git(a.repo, "rev-parse", back + "^").strip()
        mb = git(a.repo, "merge-base", orig, parent)
        ds = int(git(a.repo, "rev-list", "--count", f"{mb}..{orig}")) + 1
        dt = int(git(a.repo, "rev-list", "--count", f"{mb}..{parent}")) + 1
        subject = git(a.repo, "log", "-1", "--format=%s", orig).strip()
        m = re.match(r"\[([\d.]+[xX])\]\s*", subject)
        source_loc = f"stable/{m.group(1)}" if m else "main"
        python = "python2.7" if spec["py"] == "py2" else "python3.9"
        f = dict(slug=spec["slug"], subject=subject.replace('"', "'"),
                 orig=orig, orig8=orig[:8], backport8=back[:8], parent=parent,
                 parent8=parent[:8], mb8=mb[:8], ds=ds, dt=dt, branch=spec["branch"],
                 source_loc=source_loc, python=python,
                 difficulty=DIFFICULTY[r["Classification"]],
                 difficulty_cap=r["Classification"], reason=r["Reason"],
                 deps=" ".join(spec["deps"]),
                 settings=spec.get("settings", "test_sqlite"),
                 pypath="..:/workspace" if "settings" in spec else "..",
                 settings_block=SETTINGS_BLOCK_11X if "settings" in spec else "")
        # 1.4 only: pin www.example.com to an unroutable loopback address so
        # the deprecated verify_exists tests see the broken link they were
        # written for. Done at test time (not baked into the image) because
        # docker/podman regenerate /etc/hosts on container start; guarded so
        # repeated runs (the agent iterates build+test) don't duplicate it.
        f["hosts_prelude"] = (
            "grep -q www.example.com /etc/hosts || "
            "echo '127.0.0.2 www.example.com' >> /etc/hosts; "
            if spec.get("hosts_pin") else "")
        # The compileall prefix rides along on the nonroot form too when the
        # nonroot task is py2 (1.8: jslex quirk + the postmortem test both
        # apply). Py3 never needs it, and its commands are already
        # oracle-validated, so they stay byte-identical.
        f["compileall"] = (f"{f['python']} -m compileall -q django tests && "
                           if spec["py"] == "py2" else "")
        f["test_command"] = (TEST_CMD_NONROOT if spec["py"] == "py3"
                             or spec.get("nonroot")
                             else TEST_CMD_ROOT).format(**f)
        # Only the py2 Dockerfile interpolates this (py3 always has deps and
        # hardcodes its install RUN); empty for py2 specs with no suite
        # dependencies -- a bare `pip install` with no args errors out.
        f["deps_block"] = "" if not spec["deps"] else (
            "# Test-suite runtime dependencies for this Django version"
            f" ({f['deps']}).\n"
            "RUN python2.7 -m pip install --no-cache-dir " + f["deps"])
        # 1.8 only (py2): the non-root suite needs the djangotests user in
        # the py2 image too (py3 creates it unconditionally).
        f["user_block"] = (USER_BLOCK_PY2 if spec.get("nonroot")
                           and spec["py"] == "py2" else "")
        # Tree-level repair (see TREE_FIXES): interpolated into the
        # Dockerfile tail and committed onto target at image build. The
        # patch bytes come from the local repo, verbatim.
        tree_fix = TREE_FIXES.get(spec.get("tree_fix"))
        f["tree_fix_block"] = (TREE_FIX_BLOCK.format(**tree_fix)
                               if tree_fix else "")
        d = Path(a.out) / spec["slug"]
        (d / "environment").mkdir(parents=True, exist_ok=True)
        (d / "solution").mkdir(exist_ok=True)
        (d / "tests").mkdir(exist_ok=True)
        # Drop stale tree-fix patches from earlier generator versions so
        # removing a spec's tree_fix can't leave an orphaned COPY source.
        for old in (d / "environment").glob("tree-fix-*.patch"):
            old.unlink()
        if tree_fix:
            # NOT via git(): its .strip() would eat trailing whitespace-only
            # context lines -- same reason as the golden patch below.
            fix_patch = subprocess.run(
                ["git", "-C", str(a.repo), "diff", "--binary",
                 tree_fix["fix_commit"] + "^", tree_fix["fix_commit"]],
                check=True, capture_output=True, text=True).stdout
            (d / "environment" / tree_fix["patch_name"]).write_text(fix_patch)
        head = (DOCKERFILE_PY2 if spec["py"] == "py2" else DOCKERFILE_PY3).format(**f)
        (d / "environment" / "Dockerfile").write_text(
            head + DOCKERFILE_TAIL.format(fetch_block=FETCH_BLOCK.format(**f), **f))
        if "settings" in spec:
            (d / "environment" / (spec["settings"] + ".py")).write_text(SETTINGS_11X)
        (d / "environment" / "case.yaml").write_text(CASE.format(**f))
        (d / "task.toml").write_text(TASK_TOML.format(**f))
        (d / "instruction.md").write_text(
            CASE.split("bug_description: >\n")[1].split("\nrepository:")[0].format(**f).replace("\n  ", " ").strip() + "\n")
        (d / "solution" / "solve.sh").write_text(SOLVE.replace("{backport8}", f["backport8"]))
        (d / "solution" / "solve.sh").chmod(0o755)
        # NOT via git(): its .strip() eats trailing whitespace-only context
        # lines (blank lines at the end of the diffed files), truncating the
        # hunk and making `git apply` reject the patch. Write git's exact
        # bytes -- git diff output always ends with a newline.
        patch = subprocess.run(["git", "-C", str(a.repo), "diff", "--binary", parent, back],
                               check=True, capture_output=True, text=True).stdout
        (d / "solution" / "golden.patch").write_text(patch)
        (d / "tests" / "test.sh").write_text(template_test)
        (d / "tests" / "test.sh").chmod(0o755)
        print(f"{spec['slug']:45s} {r['Classification']:6s} py={spec['py']} "
              f"ds={ds:5d} dt={dt:4d} golden={len(patch.splitlines())} lines")


if __name__ == "__main__":
    main()
