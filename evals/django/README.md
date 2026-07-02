# django/django — Backport Evaluation

> **Follow the same pattern as [`evals/crate/README.md`](../crate/README.md).**
> This file only calls out what's different for Python / Django.

---

## What's different from crate (Java)

| Aspect | crate (Java) | django (Python) |
|--------|-------------|-----------------|
| Base image | `eclipse-temurin:24-jdk` | `python:3.12` |
| Build | `./mvnw install -pl {module}` | *(none — Python doesn't compile)* |
| Test | `./mvnw test -Dtest={test_class}` | `python tests/runtests.py {test_class}` |
| Test detection | `*Test.java` class name | dotted module path from `test_*.py` diff |
| Module detection | Maven module from `/src/` path | *(not needed)* |
| Extra setup | `toolchains.xml` | none |

`build_command` is empty in `config.yaml` — the runner skips the build step.

---

## Test class detection for Python

For Python, the runner looks at which `test_*.py` files were changed in the
original fix commit. It then:
1. Tries to find a `class TestFoo` added/changed in the diff
2. Falls back to converting the file path to a dotted module:
   `tests/auth/test_basic.py` → `auth.test_basic`

Django's `runtests.py` accepts either format:
```bash
python tests/runtests.py auth.test_basic          # module
python tests/runtests.py auth.test_basic.TestCase # class
```

---

## Quick start

Follow steps 1–6 of [`evals/crate/README.md`](../crate/README.md), substituting:

```bash
# Step 2 — Build and push image
cd evals/django/
podman build -t quay.io/<your-org>/django-backport-test:latest .
podman push quay.io/<your-org>/django-backport-test:latest

# Step 5 — Run
python3 run.py --config evals/django/config.yaml

# Step 6 — Collect
python3 run.py --config evals/django/config.yaml --collect
```

Update `image:` in `config.yaml` to match your registry path.

---

## Django test dependencies

Django's full test suite needs optional packages (Pillow, numpy, etc.).
These are pre-installed in the `Containerfile` via `pip install`.
If a test fails with `ModuleNotFoundError`, add the missing package to the
`RUN pip install` layer and rebuild the image.

---

## Adding a new repo

See the [Adding a new repo](../crate/README.md#adding-a-new-repo) section in the
crate README. For a Python repo:
1. Change the base image if a different Python version is needed
2. Update `pip install` in the `Containerfile` with the repo's test dependencies
3. Update `test_command` in `config.yaml` to match the repo's test runner
   (`pytest`, `tox`, `python -m unittest`, etc.)
4. Leave `build_command` empty
