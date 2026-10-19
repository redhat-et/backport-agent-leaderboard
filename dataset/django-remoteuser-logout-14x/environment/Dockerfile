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




# Amalgamator (and solve.sh) need a git identity to commit cherry-picks.
RUN git config --global user.email "amalgamator-bench@redhat.com" && \
    git config --global user.name "Amalgamator Bench"

# Shallow, by-SHA fetch of only the two commits this case needs. The human
# backport (c9e3b994) is a child of target and is never fetched, so it is
# not discoverable in the container (no `git log --all`, no remote to fetch
# from once the remote is removed below).
#   source = 5307ce56   original fix (on main)
#   target = 30042d47   pre-backport tip of stable/1.4.x
# Depths are exact: both histories bottom out at the fix<->target merge
# base (658ca67d), which Amalgamator's phase-0 `git merge-base source target`
# requires to connect.
RUN git init -q /workspace/django && cd /workspace/django && \
    git remote add origin https://github.com/django/django.git && \
    git fetch -q --depth=6756 origin 5307ce565fbedb9cc27cbe7c757b41a00438d37c && git branch source FETCH_HEAD && \
    git fetch -q --depth=314 origin 30042d475bf084c6723c6217a21598d9247a9c41 && git branch target FETCH_HEAD && \
    git checkout -q target && \
    git remote remove origin

RUN mkdir /tmp/amalgamator-django
