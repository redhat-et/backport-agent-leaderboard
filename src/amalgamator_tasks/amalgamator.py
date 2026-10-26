import os
from pathlib import Path

import yaml

from harbor.agents.installed.base import BaseInstalledAgent, with_prompt_template
from harbor.agents.model_connection import ModelConnectionSpec
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

_CASE_YAML_PATH = "/workspace/case.yaml"
_AMALGAMATOR_INSTALL_DIR = "/workspace/amalgamator"
_AMALGAMATOR_REPO_URL = "https://github.com/amalgamator-ai/amalgamator.git"
# The model-agnostic work (PRs #29-#32) is merged into `main`: LiteLLM
# dispatch, the shared agent runner, and the named-profile registry all live
# there now. The legacy inline `model`/`api_base` fields this adapter writes
# are still supported on main for exactly this kind of caller.
_AMALGAMATOR_BRANCH = "main"

class Amalgamator(BaseInstalledAgent):

    # Without this, `BaseAgent.model_connection` short-circuits to an empty
    # ResolvedModelConnection() (api_key=None, base_url=None) no matter what
    # is exported in the shell running `harbor run` -- see
    # harbor/agents/base.py's `model_connection` property. Declaring the spec
    # (even with all defaults) makes it actually resolve the provider's
    # standard env vars (e.g. OPENAI_API_KEY, ANTHROPIC_API_KEY) based on the
    # `provider/model` prefix in --model.
    MODEL_CONNECTION = ModelConnectionSpec()

    @staticmethod
    def name() -> str:
       return "amalgamator"

    def __init__(self, *args, context_length: int | None = None, command_timeout: int | None = None, max_build_test_retries: int | None = None, **kwargs):
        super().__init__(*args, context_length=context_length, command_timeout=command_timeout, max_build_test_retries=max_build_test_retries, **kwargs)
        self._context_length = context_length
        self._command_timeout = command_timeout
        self._max_build_test_retries = max_build_test_retries
   
    async def install(self, environment: BaseEnvironment):
        """Install the agent in the given environment."""
        # LOCAL-EVAL OVERRIDE (uncommitted, eval-only; working copy backed up
        # at /tmp/amalgamator.py.working-bak-20261018): when
        # AMALGAMATOR_DEEPEN_SHALLOW is exported on the host as
        # "<repo_path> <remote_url> <depth>", deepen the task repo's shallow
        # clone in place so amalgamator's Phase 0 `git merge-base source
        # target` can find the common ancestor (the crate Dockerfiles fetch
        # source/target at --depth=50, but main and the release branches
        # diverge 197-912 commits back, so the merge base is absent and the
        # pipeline dies in <1s). Fetch is by URL with NO refspec and
        # --no-tags: no refs are created, no tags are auto-followed, and
        # --deepen only walks BACKWARD from existing shallow boundaries --
        # the human backport (target's child) stays unfetchable, so this is
        # leak-safe (validated: backport absent from the object store
        # afterwards). NOT this form: `git remote add` + `git fetch
        # <remote> --deepen` -- the default refspec fetches all branch tips
        # and auto-follows tags, which leaks the golden backport via
        # refs/tags/* (found 2026-10-18).
        deepen_spec = os.environ.get("AMALGAMATOR_DEEPEN_SHALLOW")
        if deepen_spec:
            parts = deepen_spec.split()
            if len(parts) != 3:
                raise ValueError(
                    "AMALGAMATOR_DEEPEN_SHALLOW must be '<repo_path> <remote_url> <depth>'"
                )
            repo_path, remote_url, depth = parts
            deepen_command = (
                f"cd {repo_path} && "
                f"git fetch --no-tags --deepen={depth} {remote_url} && "
                "git merge-base source target && echo 'deepen ok: merge-base present'"
            )
            await self.exec_as_root(
                environment=environment,
                command=deepen_command,
            )
        # ... and when AMALGAMATOR_LOCAL_TARBALL is exported on the host (a
        # HOST PATH to a .tar.gz holding the top-level contents of an
        # amalgamator checkout, no .git), upload that tarball into the
        # container and install it instead of cloning GitHub main. Used to
        # eval UNPUSHED amalgamator changes (the frozen-baseline fix)
        # without touching the remote. Not set = normal GitHub clone,
        # byte-identical to the backed-up behavior.
        local_tarball = os.environ.get("AMALGAMATOR_LOCAL_TARBALL")
        if local_tarball:
            await environment.upload_file(
                Path(local_tarball), "/tmp/amalgamator-local.tar.gz"
            )
            python_probe = (
                'PY="$(command -v python3.12 || command -v python3)"'
            )
            # Extract with python's tarfile module, NOT /usr/bin/tar: GNU tar
            # 1.35's extraction syscalls (the *at()/flag combinations it uses)
            # return ENOSYS under Rosetta in linux/amd64 containers on Apple
            # Silicon -- every mkdir/open fails with "Function not
            # implemented" (bit the crate x9 eval 2026-10-18; arm64-native
            # containers like django are unaffected). python tarfile goes
            # through glibc's plain open/mkdir and works everywhere.
            install_command = (
                f"mkdir -p {_AMALGAMATOR_INSTALL_DIR} && "
                f"{python_probe} && "
                '"$PY" -c "import tarfile; t = tarfile.open(\'/tmp/amalgamator-local.tar.gz\'); '
                f"t.extractall('{_AMALGAMATOR_INSTALL_DIR}', filter='data') "
                'if hasattr(tarfile, \'data_filter\') else t.extractall(\''
                f'{_AMALGAMATOR_INSTALL_DIR}\')" && '
                f"rm -f /tmp/amalgamator-local.tar.gz && "
                f"cd {_AMALGAMATOR_INSTALL_DIR} && "
                '"$PY" -m pip install -e . --break-system-packages --ignore-requires-python --ignore-installed'
            )
            await self.exec_as_root(
                environment=environment,
                command=install_command,
            )
            return
        # amalgamator is a private/internal GitHub repo -- the container has
        # no credentials of its own, so an anonymous clone fails with
        # "could not read Username for 'https://github.com'". Pull a token
        # from the *host* environment (where `harbor run` was invoked) and
        # hand it to the container only for this one command, via env
        # interpolation so the raw token never appears in a logged command
        # string. Run `export GITHUB_TOKEN=$(gh auth token)` before `harbor
        # run` (or set a fine-grained PAT with read access to the repo).
        github_token = os.environ.get("GITHUB_TOKEN")
        if not github_token:
            raise RuntimeError(
                "GITHUB_TOKEN is not set on the host. amalgamator is a "
                "private/internal repo, so cloning it inside the container "
                "needs a token. Run `export GITHUB_TOKEN=$(gh auth token)` "
                "(or set a PAT with read access to amalgamator-ai/amalgamator) "
                "before `harbor run`."
            )
        clone_url = _AMALGAMATOR_REPO_URL.replace(
            "https://", "https://x-access-token:${GITHUB_TOKEN}@"
        )
        # Prefer an explicit python3.12 when the container ships one: the
        # CentOS Stream 8/9 tasks provide python3.12 alongside the distro
        # python (3.6/3.9) because amalgamator needs >= 3.12 -- but their
        # /usr/bin/python3 must stay the distro default for the EPEL centpkg
        # tooling the task itself builds with. Everywhere else (golang,
        # Ubuntu, Stream 10+ images) python3 is already new enough, and the
        # fallback keeps the previous behavior.
        python_probe = (
            'PY="$(command -v python3.12 || command -v python3)"'
        )
        install_command = (
            f"git clone --branch {_AMALGAMATOR_BRANCH} --single-branch "
            f"{clone_url} {_AMALGAMATOR_INSTALL_DIR} && "
            f"cd {_AMALGAMATOR_INSTALL_DIR} && "
            f"{python_probe} && "
            # --break-system-packages: Ubuntu 24.04's system python3 is PEP
            # 668 "externally managed". --ignore-requires-python: the repo's
            # pyproject.toml pins requires-python >=3.14, which is newer than
            # what's available in the task container; the code itself runs
            # fine on 3.12.
            '"$PY" -m pip install -e . --break-system-packages --ignore-requires-python --ignore-installed'
        )
        await self.exec_as_root(
            environment=environment,
            command=install_command,
            env={"GITHUB_TOKEN": github_token},
        )

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        
        # Determine model & endpoint
        if "/" not in self.model_name:
            raise ValueError("Model name must be in the format 'provider/model'")
        
        # maxsplit=1: some model names have their own "/" (e.g. self-hosted
        # "openai/Inferact/Qwen3.8-Flash-Next-NVFP4"). Only the leading
        # "provider/" segment should be split off.
        provider, _, _model_path = self.model_name.partition("/")
        access = self.model_connection
        
        api_base = None
        amalgamator_env = {}
        if provider == "openai":
            # Will infer base url from OPENAI_BASE_URL
            api_base = access.base_url
            amalgamator_env["OPENAI_API_KEY"] = access.api_key
        elif provider == "anthropic":
            # No base, will use anthropic API
            api_base = None
            amalgamator_env["ANTHROPIC_API_KEY"] = access.api_key
        
        # Any other provider supported by amalgamator goes here...
        
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        missing = [key for key, value in amalgamator_env.items() if not value]
        if missing:
            raise RuntimeError(
                f"Missing value(s) for {missing} on the host running `harbor "
                f"run`. Export the real key(s) in your shell before invoking "
                f"harbor, e.g. `export OPENAI_API_KEY=sk-...` (not a "
                f"self-referential `export OPENAI_API_KEY=\"$OPENAI_API_KEY\"` "
                f"in a shell where it was never set)."
            )
        
        # Update the config file with the model and endpoint
        cat_result = await self.exec_as_agent(
            environment=environment,
            command=f"cat {_CASE_YAML_PATH}",
        )
        config_file_dict: dict = yaml.safe_load(cat_result.stdout)

        # Overwrite the model and endpoint
        config_file_dict["model"] = self.model_name
        config_file_dict["api_base"] = api_base

        # Some OpenAI-compatible gateways (e.g. the PriceTag unified route)
        # authenticate via x-api-key and ignore the Authorization: Bearer
        # header that litellm's openai provider always sends. The gateway
        # accepts both headers together, so when a custom endpoint is in use
        # also pass the key as x-api-key via model_params (merged into every
        # litellm call, incl. the agent loop and context summarization).
        # stream_options asks streaming responses to include a final usage
        # chunk so gateway metering logs real token counts (0 without it);
        # litellm strips it for non-stream calls, where gateways 400 on it.
        if api_base and access.api_key:
            model_params = config_file_dict.setdefault("model_params", {})
            model_params.setdefault("extra_headers", {})["x-api-key"] = access.api_key
            model_params.setdefault("stream_options", {})["include_usage"] = True

        # GPT-5+/codex-class reasoning models 400 on chat completions when
        # function tools are combined with their default reasoning effort.
        # Accepted effort differs per family: Sol rejects "none" and needs
        # "low"; Luna/Terra accept tools only with "none". Harmless for
        # other models.
        if any(t in self.model_name for t in ("gpt", "sol")):
            effort = "none" if ("luna" in self.model_name or "terra" in self.model_name) else "low"
            config_file_dict.setdefault("model_params", {}).setdefault(
                "reasoning_effort", effort
            )

        # Overwrite any advanced options
        advanced = config_file_dict.setdefault("advanced", {})
        if self._context_length is not None:
            advanced["context_length"] = self._context_length
        if self._command_timeout is not None:
            advanced["command_timeout"] = self._command_timeout
        if self._max_build_test_retries is not None:
            advanced["max_build_test_retries"] = self._max_build_test_retries

        # Write the updated config file back to the environment. Uploading a
        # file (rather than piping through `echo`) avoids quoting/escaping
        # issues with YAML content (colons, quotes, special chars).
        await self._upload_config_text(
            environment,
            content=yaml.dump(config_file_dict, indent=2),
            remote_path=_CASE_YAML_PATH,
            filename="case.yaml",
        )

        # Run Amalgamator against the (now model-configured) case file.
        # Same python3.12-first probe as install(): see the comment there.
        await self.exec_as_agent(
            environment,
            command=(
                f"cd {_AMALGAMATOR_INSTALL_DIR} && "
                'PY="$(command -v python3.12 || command -v python3)" && '
                f'PYTHONPATH=. "$PY" -m auto_bug_fix.run_bug_fix {_CASE_YAML_PATH}'
            ),
            env=amalgamator_env,
            timeout_sec=self._command_timeout,
        )
