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
# backport (729957bc) is a child of target and is never fetched, so it is
# not discoverable in the container (no `git log --all`, no remote to fetch from).
#   source = a9199b9f   original fix on main
#   target = 7ef00008   pre-backport tip of the release branch (729957bc^)
RUN git init -q /workspace/crate && cd /workspace/crate && \
    git remote add origin https://github.com/crate/crate.git && \
    git fetch -q --depth=50 origin a9199b9f781a9db3a49c1a8341e6837d63ed7980 && git branch source FETCH_HEAD && \
    git fetch -q --depth=50 origin 7ef00008ecc56d1ac7570a8b9eb684935d1ac9a2 && git branch target FETCH_HEAD && \
    git checkout -q target && \
    git remote remove origin

# Warm the Maven cache for the target tree so the agent/verifier do not pay
# for dependency downloads (offline-safe resolution + test compilation).
RUN cd /workspace/crate && crate-mvn -q test-compile

RUN mkdir /workspace/workdir
