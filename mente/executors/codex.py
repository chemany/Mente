"""Minimal Codex-backed executor for Mente."""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

from mente.executors.kernel_adapter import CodexKernelAdapter
from mente.executors.prompting import render_execution_prompt
from mente.executors.runtime_home import resolve_runtime_home
from mente.task_core.models import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


class CodexExecutor(CodexKernelAdapter):
    """Execute Mente requests through the Codex CLI."""

    def __init__(
        self,
        codex_binary: str = "codex",
        sandbox: str = "workspace-write",
        approval_policy: str = "never",
    ) -> None:
        self.codex_binary = codex_binary
        self.sandbox = sandbox
        self.approval_policy = approval_policy

    def build_prompt(self, request: ExecutionRequest) -> str:
        """Build a stable textual prompt from an execution request."""
        return render_execution_prompt(request)

    def build_request_payload(self, request: ExecutionRequest) -> dict[str, object]:
        """Build the stable adapter payload for a prepared execution request."""
        return {
            "prompt": self.build_prompt(request),
            "workspace": request.workspace,
        }

    def build_command(
        self,
        request: ExecutionRequest,
        output_last_message: str | None = None,
        output_schema: str | None = None,
        config_overrides: list[str] | None = None,
        workdir: str | None = None,
        add_dirs: list[str] | None = None,
    ) -> list[str]:
        """Build the Codex CLI command for a request."""
        payload = self.build_request_payload(request)
        command = [
            self.codex_binary,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
        ]
        for override in config_overrides or []:
            command.extend(["-c", override])
        command.extend(self._build_execution_mode_args())
        command.extend(
            [
                "--skip-git-repo-check",
                "--color",
                "never",
                "--cd",
                workdir or request.workspace,
            ]
        )
        for add_dir in add_dirs or []:
            command.extend(["--add-dir", add_dir])
        if output_last_message:
            command.extend(["--output-last-message", output_last_message])
        if output_schema:
            command.extend(["--output-schema", output_schema])
        command.append(str(payload["prompt"]))
        return command

    def _build_execution_mode_args(self) -> list[str]:
        """Map legacy sandbox/approval settings onto the current Codex CLI."""
        if self.approval_policy == "never":
            if self.sandbox == "danger-full-access":
                return ["--dangerously-bypass-approvals-and-sandbox"]
            return ["--sandbox", self.sandbox, "--full-auto"]

        return ["--sandbox", self.sandbox]

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Run Codex synchronously and normalize the response."""
        output_path: Path | None = None
        schema_path: Path | None = None
        runtime_workdir: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="mente-codex-",
                suffix=".txt",
                delete=False,
            ) as handle:
                output_path = Path(handle.name)
            with tempfile.NamedTemporaryFile(
                prefix="mente-codex-schema-",
                suffix=".json",
                mode="w",
                encoding="utf-8",
                delete=False,
            ) as handle:
                json.dump(self._structured_output_schema(), handle)
                schema_path = Path(handle.name)
            codex_home = resolve_runtime_home()
            codex_home.mkdir(parents=True, exist_ok=True)
            runtime_workdir = Path(
                tempfile.mkdtemp(prefix="mente-codex-workdir-")
            ).resolve()
            self._seed_auth_into_isolated_home(codex_home)
            config_overrides = self._build_runtime_config_overrides()

            command = self.build_command(
                request,
                output_last_message=str(output_path),
                output_schema=str(schema_path),
                config_overrides=config_overrides,
                workdir=str(runtime_workdir),
                add_dirs=[str(Path(request.workspace).resolve())],
            )
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    cwd=request.workspace,
                    check=False,
                    env=self._build_subprocess_env(codex_home),
                )
            except OSError as exc:
                logger.error(
                    "codex execution failed to start for task %s in %s: %s",
                    request.task_id,
                    request.workspace,
                    exc,
                )
                return ExecutionResult(
                    status="failed",
                    summary=str(exc),
                    commands_run=[shlex.join(command)],
                    failure_reason="spawn_error",
                    metadata={
                        "exception_type": type(exc).__name__,
                        "exception": str(exc),
                    },
                )

            summary = ""
            memory_candidates: list[str] = []
            structured_output = None
            if output_path.exists():
                raw_output = output_path.read_text(encoding="utf-8").strip()
                structured_output = self._parse_structured_output(raw_output)
                if structured_output is not None:
                    summary = structured_output.get("assistant_summary", "").strip()
                    memory_candidates = [
                        candidate.strip()
                        for candidate in structured_output.get("memory_candidates", [])
                        if isinstance(candidate, str) and candidate.strip()
                    ]
                else:
                    summary = raw_output
            if not summary:
                summary = (completed.stdout or completed.stderr).strip()

            status = "success" if completed.returncode == 0 else "failed"
            logger.info(
                "codex execution finished for task %s in %s with status %s and exit code %s",
                request.task_id,
                request.workspace,
                status,
                completed.returncode,
            )
            return ExecutionResult(
                status=status,
                summary=summary,
                commands_run=[shlex.join(command)],
                memory_candidates=memory_candidates,
                failure_reason=None if completed.returncode == 0 else f"exit_code:{completed.returncode}",
                metadata={
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "structured_output": structured_output,
                },
            )
        finally:
            if output_path is not None:
                try:
                    os.unlink(output_path)
                except FileNotFoundError:
                    pass
            if schema_path is not None:
                try:
                    os.unlink(schema_path)
                except FileNotFoundError:
                    pass
            if runtime_workdir is not None:
                shutil.rmtree(runtime_workdir, ignore_errors=True)

    def _structured_output_schema(self) -> dict[str, object]:
        """Return the schema used for final structured Codex responses."""
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "assistant_summary": {"type": "string"},
                "memory_candidates": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["assistant_summary", "memory_candidates"],
        }

    def _parse_structured_output(self, raw_output: str) -> dict[str, object] | None:
        """Parse structured Codex output and fall back cleanly on malformed data."""
        if not raw_output:
            return None

        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError:
            return None

        if not isinstance(parsed, dict):
            return None

        if not isinstance(parsed.get("assistant_summary"), str):
            return None
        if not isinstance(parsed.get("memory_candidates"), list):
            return None

        return parsed

    def _build_subprocess_env(self, codex_home: Path) -> dict[str, str]:
        """Construct a minimal subprocess environment for isolated Codex runs."""
        env: dict[str, str] = {}
        for key in (
            "LANG",
            "LC_ALL",
            "OPENAI_API_KEY",
            "PATH",
            "PYTHONIOENCODING",
            "PYTHONPATH",
            "SHELL",
            "SSL_CERT_DIR",
            "SSL_CERT_FILE",
            "SYSTEMROOT",
            "TERM",
            "TMP",
            "TEMP",
            "TMPDIR",
        ):
            value = os.environ.get(key)
            if value:
                env[key] = value
        env["HOME"] = str(codex_home)
        env["CODEX_HOME"] = str(codex_home)
        return env

    def _seed_auth_into_isolated_home(self, codex_home: Path) -> None:
        """Copy only Codex auth material into the isolated runtime home."""
        source_auth = self._resolve_public_codex_home() / "auth.json"
        if not source_auth.exists():
            return
        target_auth = codex_home / "auth.json"
        shutil.copy2(source_auth, target_auth)
        target_auth.chmod(0o600)

    def _resolve_public_codex_home(self) -> Path:
        """Resolve the user's shared Codex home used only as an auth seed source."""
        configured = os.environ.get("CODEX_HOME", "").strip()
        if configured:
            return Path(configured).expanduser()
        return Path.home() / ".codex"

    def _build_runtime_config_overrides(self) -> list[str]:
        """Extract the minimum provider routing config needed for isolated runs."""
        source_config = self._resolve_public_codex_home() / "config.toml"
        if not source_config.exists():
            return []

        try:
            parsed = tomllib.loads(source_config.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return []

        provider = parsed.get("model_provider")
        if not isinstance(provider, str) or not provider.strip():
            return []

        overrides = [self._format_config_override("model_provider", provider)]
        model = parsed.get("model")
        if isinstance(model, str) and model.strip():
            overrides.append(self._format_config_override("model", model))

        provider_config = parsed.get("model_providers", {}).get(provider)
        if isinstance(provider_config, dict):
            overrides.extend(
                self._flatten_config_overrides(
                    f"model_providers.{provider}",
                    provider_config,
                )
            )
        return overrides

    def _flatten_config_overrides(self, prefix: str, value: object) -> list[str]:
        """Flatten nested config data into dotted Codex `-c key=value` overrides."""
        if isinstance(value, dict):
            overrides: list[str] = []
            for key in sorted(value):
                if not isinstance(key, str):
                    continue
                overrides.extend(
                    self._flatten_config_overrides(
                        f"{prefix}.{key}",
                        value[key],
                    )
                )
            return overrides
        if isinstance(value, list):
            return [self._format_config_override(prefix, value)]
        if isinstance(value, (str, bool, int, float)):
            return [self._format_config_override(prefix, value)]
        return []

    def _format_config_override(self, key: str, value: object) -> str:
        """Render a stable TOML-compatible `key=value` override string."""
        return f"{key}={json.dumps(value, ensure_ascii=True)}"
