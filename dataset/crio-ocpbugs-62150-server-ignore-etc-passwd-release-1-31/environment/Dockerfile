# Era toolchain: the minor matches the target pin's own go.mod (go 1.22).
FROM golang:1.22-bookworm

WORKDIR /workspace

COPY case.yaml /workspace

# yq parses case.yaml; python3+pip3 are for the harbor adapter's amalgamator
# install; libseccomp-dev is cri-o's cgo dependency.  conmon/runc/crun are
# the OCI runtime stack cri-o's unit tests validate against (1.29/1.30
# default to runc, 1.31+ to crun; conmon is checked by pkg/config specs in
# every era -- the test framework only grew self-shims for these in 1.32).
# Debian puts runc in /usr/sbin, but the 1.29/1.30 reload tests hardcode
# /usr/bin/runc, so bridge the two.
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates yq jq libseccomp-dev python3 python3-pip \
      conmon runc crun \
    && { [ -e /usr/bin/runc ] || ln -s "$(command -v runc)" /usr/bin/runc; } \
    && rm -rf /var/lib/apt/lists/*

# Force the containers/storage graph driver to vfs.  The default (overlay)
# is refused on this overlayfs-backed filesystem, but only AFTER the
# overlay driver's Init() has already created <graphroot>/overlay -- and
# any later process then treats that directory as prior driver state,
# which is fatal by design (storage's ScanPriorDrivers: silently switching
# drivers would make the daemon's images disappear).  vfs is fully
# supported here and keeps every GetStore() probe deterministic.
RUN mkdir -p /etc/containers && \
    printf '[storage]\ndriver = "vfs"\nrunroot = "/run/containers/storage"\ngraphroot = "/var/lib/containers/storage"\n' \
      > /etc/containers/storage.conf

RUN git config --global user.email "amalgamator-bench@redhat.com" && \
    git config --global user.name "Amalgamator Bench"

# Shallow, by-SHA fetch of only the two commits this case needs. The human
# backport (da5b9878) is a child of target and is never fetched, so it is
# not discoverable in the container (no `git log --all`, no remote to fetch
# from). The depths are computed from the full local clone at generation
# time so the fork point (merge-base of fix and target) is carried on both
# sides -- `git merge-base source target`, `git log` and `git blame` work;
# no commit newer than the two fetched SHAs exists in the object store.
#   source = 9d7aa99d   original fix (on main)
#   target = e0b87e51   pre-backport tip of release-1.31 (da5b9878^)
RUN git init -q /workspace/crio && cd /workspace/crio && \
    git remote add origin https://github.com/cri-o/cri-o.git && \
    git fetch -q --depth=823 origin 9d7aa99d0defb26213d45164e1309649c3bf18ec && git branch source FETCH_HEAD && \
    git fetch -q --depth=105 origin e0b87e516a79fc51fd57886ccd4bcd769edb9bfa && git branch target FETCH_HEAD && \
    git checkout -q target && \
    git remote remove origin

# Pre-existing, fix-unrelated test failures at this pin are
# repaired in the target tree itself (committed, so both the
# baseline and any backported tree run the full suite
# deterministically).  Test-infra only -- ports of upstream
# environment guards; see the treefix commit for details.
COPY treefix.patch /tmp/treefix.patch
RUN cd /workspace/crio && git apply /tmp/treefix.patch && \
    git add -A && \
    git commit -q -m 'Adapt unit tests to an unprivileged container environment' \
               -m 'Ports of upstream test-environment guards; no production code is changed.' && \
    rm /tmp/treefix.patch

# Baseline validation + Go build-cache warm-up with the EXACT gate command
# from case.yaml, so the agent and the verifier start from a tree that is
# known to compile with this era toolchain.
RUN cd /workspace/crio && GOTOOLCHAIN=local go build -mod=vendor -tags "containers_image_ostree_stub containers_image_openpgp exclude_graphdriver_btrfs exclude_graphdriver_devicemapper seccomp" $(GOTOOLCHAIN=local go list -mod=vendor -tags "containers_image_ostree_stub containers_image_openpgp exclude_graphdriver_btrfs exclude_graphdriver_devicemapper seccomp" ./... | grep -v /test | grep -v nsmgr/test)

RUN mkdir /workspace/workdir
