FROM golang:1.26-bookworm

WORKDIR /workspace

COPY case.yaml /workspace

# yq+jq parse case.yaml; libseccomp-dev is a cgo build dep of cri-o;
# python3+pip3 are needed by the harbor adapter to install amalgamator.
RUN apt-get update && apt-get install -y yq jq libseccomp-dev python3 python3-pip && rm -rf /var/lib/apt/lists/*

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
