FROM golang:1.26-bookworm

WORKDIR /workspace

COPY case.yaml /workspace

# yq+jq parse case.yaml; libseccomp-dev is a cgo build dep of cri-o;
# python3+pip3 are needed by the harbor adapter to install amalgamator.
RUN apt-get update && apt-get install -y yq jq libseccomp-dev python3 python3-pip && rm -rf /var/lib/apt/lists/*

# Force the containers/storage graph driver to vfs: the default (overlay) is
# refused on this overlayfs-backed filesystem only AFTER leaving a partial
# <graphroot>/overlay directory behind, which poisons every later GetStore()
# probe with a fatal prior-driver-state error.  The 2026-09-05 reference run
# worked around this by writing the same file from inside the container;
# baking it into the image makes that unnecessary.
RUN mkdir -p /etc/containers && \
    printf '[storage]\ndriver = "vfs"\nrunroot = "/run/containers/storage"\ngraphroot = "/var/lib/containers/storage"\n' \
      > /etc/containers/storage.conf

RUN git clone https://github.com/cri-o/cri-o.git /workspace/project

RUN git config --global user.email "amalgamator-bench@redhat.com" && \
    git config --global user.name "Amalgamator Bench"

# Target = release-1.36 pinned at 6e902ee2a (tip on 2026-09-05, the exact
# base the reference backport run used). No official human backport of
# PR #9907 exists on release-1.36, so this task's golden is the previously
# produced amalgamator run of 2026-09-05 (see solution/golden.patch).
RUN cd /workspace/project && \
    git branch target 6e902ee2a

RUN mkdir /workspace/workdir
