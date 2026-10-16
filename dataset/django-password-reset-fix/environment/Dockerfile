# Prebuilt Python 2.7 (Django 1.4.x's framework code, e.g.
# `except ImportError, e:` in django/conf/__init__.py, is Python-2-only --
# not just this fix's test-runner print statement). Copied in below instead
# of compiled from source: compiling from source blew past Harbor's
# environment-start timeout (~10 min).
FROM python:2.7.18-slim AS python2

FROM ubuntu:24.04

WORKDIR /workspace

COPY case.yaml /workspace

RUN apt-get update && apt-get install -y curl wget git yq

# Everything above this stays the same for each task, everything below will change

# Install python - this step will vary by rep
RUN apt-get install -y python3 python3-pip

# Ubuntu 24.04 dropped python2 from its repos entirely. Copy in the
# prebuilt interpreter from the python2 stage above (see comment at top of
# file) instead of compiling from source.
COPY --from=python2 /usr/local /usr/local
# The interpreter's _hashlib (and hence hashlib.sha256/md5/etc, which
# Django's own password hashers need) is linked against libssl.so.1.1 /
# libcrypto.so.1.1, which ubuntu:24.04 doesn't ship (it's on OpenSSL 3.x).
# Grab the matching 1.1 libs from the same python2 stage's base OS.
COPY --from=python2 /usr/lib/*/libssl.so.1.1 /usr/lib/*/libcrypto.so.1.1 /usr/lib/
RUN ldconfig && python2.7 -c "import hashlib; hashlib.sha256('x'); print('python2.7 + hashlib OK')"

# Clone the django repo
RUN git clone https://github.com/django/django.git /workspace/django

# Amalgamator (and solve.sh) need a git identity to commit cherry-picks.
RUN git config --global user.email "amalgamator-bench@redhat.com" && \
    git config --global user.name "Amalgamator Bench"

# The original target branch for this case, stable/1.4.x, no longer exists on
# django/django (it was deleted years ago after EOL). The known-good backport
# commit (92d3430f) is still reachable in history via later 1.4.x tags, so we
# recreate "target" as a local branch pointing at that backport commit's
# parent -- i.e. the exact pre-fix state the backport commit was applied to.
# This mirrors how the real benchmark harness (backport-agent-leaderboard)
# derives its target branch: always backport_sha^, never a branch name.
RUN cd /workspace/django && \
    git branch target 92d3430f12171f16f566c9050c40feefb830a4a3^

# Make the working directory
RUN mkdir /tmp/amalgamator-django
