# cri-o/cri-o — Backport Evaluation

> **Follow the same pattern as [`evals/crate/README.md`](../crate/README.md).**
> This file only calls out what's different for Go / cri-o.

---

## What's different from crate (Java)

| Aspect | crate (Java) | cri-o (Go) |
|--------|-------------|------------|
| Base image | `eclipse-temurin:24-jdk` | `golang:1.22` |
| Build | `./mvnw install -pl {module}` | `make` |
| Test | `./mvnw test -Dtest={test_class}` | `go test -run {test_class} {module}` |
| Test detection | `*Test.java` class name | `Test*` function from `*_test.go` diff |
| Module detection | Maven module from `/src/` path | Go package path (e.g. `./pkg/server/...`) |
| Extra setup | `toolchains.xml` (JDK spoofing) | none needed |

No toolchains.xml — Go has a single binary per version, no JDK version negotiation.

---

## Quick start

Follow steps 1–6 of [`evals/crate/README.md`](../crate/README.md), substituting:

```bash
# Step 2 — Build and push image
cd evals/cri-o/
podman build -t quay.io/<your-org>/crio-backport-test:latest .
podman push quay.io/<your-org>/crio-backport-test:latest

# Step 5 — Run
python3 run.py --config evals/cri-o/config.yaml

# Step 6 — Collect
python3 run.py --config evals/cri-o/config.yaml --collect
```

Update `image:` in `config.yaml` to match your registry path.

---

## System libs in the Containerfile

cri-o uses CGo and requires:
- `libseccomp-dev` — seccomp syscall filtering
- `libgpgme-dev` — GPG signature verification
- `pkg-config` — CGo dependency resolution

These are installed via `apt-get` in the `Containerfile`. If the build fails with
a CGo-related error, check if a new system lib was added to cri-o's dependencies.

---

## Adding a new repo

See the [Adding a new repo](../crate/README.md#adding-a-new-repo) section in the
crate README. For a Go repo:
1. Change `FROM golang:1.22` to match the required Go version
2. Update system packages if the repo has different CGo deps
3. Update `build_command` and `test_command` in `config.yaml`
