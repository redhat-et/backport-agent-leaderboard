# Pin to linux/amd64 on every host: the crate-copy-azure module's OpenDAL
# native library ships x86-64 only, so an arm64 host (Apple Silicon docker)
# dies in AzureCopyIntegrationTest with an UnsatisfiedLinkError/NPE. arm64
# machines run the image under Rosetta emulation -- probe-validated
# 2026-10-17: image builds in 7m31s cold, AzureCopyIntegrationTest passes
# 2/2 in 18.2s, whole emulated mvn invocation 54s warm.
FROM --platform=linux/amd64 eclipse-temurin:25-jdk

WORKDIR /workspace

COPY case.yaml /workspace

# yq parses case.yaml; python3+pip3 are for the harbor adapter's amalgamator install.
RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates yq python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN git config --global user.email "amalgamator-bench@redhat.com" && \
    git config --global user.name "Amalgamator Bench"

ENV MAVEN_OPTS="-Xmx4g"

# Container-environment fixes so the UNMODIFIED, FULL suite is green at baseline:
#  * NativesTest.test_runningAsRoot asserts the JVM is NOT root -> build and test
#    as an unprivileged user via crate-mvn (root keeps orchestrating git/amalgamator).
#  * NodeStatsITest.testSysNodesCgroup needs cgroup-v1 cpuacct data; Docker
#    runs cgroup v2 (/proc/self/cgroup = "0::/"). The test's own escape hatch for
#    such CI environments is SHIPPABLE=true, set in crate-mvn below.
# Neither test is excluded or edited; everything else runs.
RUN useradd -m -s /bin/bash builder && \
    git config --global --add safe.directory '*' && \
    printf '%s\n' '#!/bin/bash' 'set -e' \
      'chown -R builder:builder "$PWD" /workspace/crate/.git 2>/dev/null || true' \
      'exec runuser -u builder -- env HOME=/home/builder SHIPPABLE=true MAVEN_OPTS="$MAVEN_OPTS" ./mvnw -B -ntp "$@"' \
      > /usr/local/bin/crate-mvn && chmod +x /usr/local/bin/crate-mvn

# Shallow, by-SHA fetch of only the two commits this case needs. The human
# backport (c0d5e58e) is a child of target and is never fetched, so it is
# not discoverable in the container (no `git log --all`, no remote to fetch from).
#   source = a2f572fc   original fix on main
#   target = f098b9c9   pre-backport tip of the release branch (c0d5e58e^)
RUN git init -q /workspace/crate && cd /workspace/crate && \
    git remote add origin https://github.com/crate/crate.git && \
    git fetch -q --depth=50 origin a2f572fc480380b3c2d17fd3b5e436e759723c19 && git branch source FETCH_HEAD && \
    git fetch -q --depth=50 origin f098b9c95f6de9f771831894f38065c9af777029 && git branch target FETCH_HEAD && \
    git checkout -q target && \
    git remote remove origin

# Warm the Maven cache for the target tree so the agent/verifier do not pay
# for dependency downloads (offline-safe resolution + test compilation).
RUN cd /workspace/crate && crate-mvn -q test-compile

RUN mkdir /workspace/workdir
