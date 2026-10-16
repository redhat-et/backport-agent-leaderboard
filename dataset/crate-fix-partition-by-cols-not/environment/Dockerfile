FROM eclipse-temurin:25-jdk

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
# backport (d17ad1df) is a child of target and is never fetched, so it is
# not discoverable in the container (no `git log --all`, no remote to fetch from).
#   source = 422c9d48   original fix on main
#   target = 04864c39   pre-backport tip of the release branch (d17ad1df^)
RUN git init -q /workspace/crate && cd /workspace/crate && \
    git remote add origin https://github.com/crate/crate.git && \
    git fetch -q --depth=50 origin 422c9d48ae8aee46e0e7550e26d8d326cfa6468d && git branch source FETCH_HEAD && \
    git fetch -q --depth=50 origin 04864c3912153029e3a87b5441950a97538c4f42 && git branch target FETCH_HEAD && \
    git checkout -q target && \
    git remote remove origin

# Warm the Maven cache for the target tree so the agent/verifier do not pay
# for dependency downloads (offline-safe resolution + test compilation).
RUN cd /workspace/crate && crate-mvn -q test-compile

RUN mkdir /workspace/workdir
