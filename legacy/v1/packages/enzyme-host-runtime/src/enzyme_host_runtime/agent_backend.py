from __future__ import annotations

import atexit
from dataclasses import dataclass
import json
import os
from pathlib import Path
import select
import shlex
import subprocess
import threading
from typing import Any
import uuid

_CONFIG_PATH = Path(".enzyme/agent_backend.json")


@dataclass(slots=True)
class LLMSidecarConfig:
    provider: str
    model: str
    timeout_seconds: float
    allow_fallback: bool
    command: tuple[str, ...]
    cwd: str
    config_path: str


@dataclass(slots=True)
class AgentBackendConfig:
    backend: str
    llm_sidecar: LLMSidecarConfig


@dataclass(slots=True)
class SidecarResponse:
    request_id: str
    operation: str
    result: dict[str, Any] | list[Any] | str
    provenance: dict[str, Any]


class SidecarInvocationError(RuntimeError):
    def __init__(
        self,
        summary: str,
        *,
        category: str,
        retryable: bool,
        provenance: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(summary)
        self.summary = summary
        self.category = category
        self.retryable = retryable
        self.provenance = dict(provenance or {})


class LLMSidecarClient:
    def __init__(self, config: LLMSidecarConfig) -> None:
        self.config = config
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        atexit.register(self.close)

    def request(
        self,
        *,
        operation: str,
        context: dict[str, Any],
        backend: dict[str, Any],
    ) -> SidecarResponse:
        payload = {
            "requestId": f"llmreq-{uuid.uuid4().hex[:12]}",
            "operation": operation,
            "backend": backend,
            "context": context,
        }
        with self._lock:
            try:
                return self._send_request(payload)
            except (BrokenPipeError, OSError):
                self._restart_process()
                return self._send_request(payload)

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)

    def _send_request(self, payload: dict[str, Any]) -> SidecarResponse:
        process = self._ensure_process()
        if process.stdin is None or process.stdout is None:
            raise SidecarInvocationError(
                "Sidecar stdio pipes are unavailable.",
                category="sidecar-unavailable",
                retryable=True,
            )
        process.stdin.write(json.dumps(payload, ensure_ascii=True) + "\n")
        process.stdin.flush()
        ready, _, _ = select.select([process.stdout], [], [], self.config.timeout_seconds + 0.5)
        if not ready:
            self._restart_process()
            raise SidecarInvocationError(
                f"Timed out waiting for sidecar response for {payload['operation']}.",
                category="timeout",
                retryable=True,
            )
        line = process.stdout.readline()
        if not line:
            stderr = ""
            if process.stderr is not None:
                stderr = process.stderr.read().strip()
            self._restart_process()
            raise SidecarInvocationError(
                stderr or f"Sidecar exited before responding to {payload['operation']}.",
                category="sidecar-unavailable",
                retryable=True,
            )
        response = json.loads(line)
        if response.get("ok") is True:
            return SidecarResponse(
                request_id=str(response.get("requestId") or payload["requestId"]),
                operation=str(response.get("operation") or payload["operation"]),
                result=response.get("result"),
                provenance=dict(response.get("provenance") or {}),
            )
        error = dict(response.get("error") or {})
        raise SidecarInvocationError(
            str(error.get("summary") or "Sidecar request failed."),
            category=str(error.get("category") or "sidecar-error"),
            retryable=bool(error.get("retryable")),
            provenance=dict(response.get("provenance") or {}),
        )

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        self._process = subprocess.Popen(
            list(self.config.command),
            cwd=self.config.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        return self._process

    def _restart_process(self) -> None:
        self.close()
        self._process = None


def load_agent_backend_config(project_root: Path) -> AgentBackendConfig:
    config_path = project_root / _CONFIG_PATH
    payload: dict[str, Any] = {}
    if config_path.exists():
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    llm_payload = dict(payload.get("llm_sidecar") or {})
    backend = str(payload.get("backend") or "heuristic")
    backend = _env_override("ENZYME_AGENT_BACKEND", backend)
    provider = _env_override("ENZYME_AGENT_PROVIDER", str(llm_payload.get("provider") or "fake"))
    model = _env_override("ENZYME_AGENT_MODEL", str(llm_payload.get("model") or "fake-structured-agent"))
    timeout_seconds = _float_override(
        "ENZYME_AGENT_TIMEOUT_SECONDS",
        float(llm_payload.get("timeout_seconds") or 30.0),
    )
    allow_fallback = _bool_override(
        "ENZYME_AGENT_ALLOW_FALLBACK",
        bool(llm_payload.get("allow_fallback", True)),
    )
    command = _command_override(
        "ENZYME_AGENT_SIDECAR_COMMAND",
        llm_payload.get("command") or _default_sidecar_command(config_path),
    )
    cwd_value = str(llm_payload.get("cwd") or _repo_root() / "apps" / "pi-ai-sidecar")
    cwd = _env_override("ENZYME_AGENT_SIDECAR_CWD", cwd_value)
    return AgentBackendConfig(
        backend=backend,
        llm_sidecar=LLMSidecarConfig(
            provider=provider,
            model=model,
            timeout_seconds=timeout_seconds,
            allow_fallback=allow_fallback,
            command=command,
            cwd=str(Path(cwd).resolve()),
            config_path=str(config_path.resolve()),
        ),
    )


def _default_sidecar_command(config_path: Path) -> list[str]:
    return [
        "node",
        str((_repo_root() / "apps" / "pi-ai-sidecar" / "src" / "index.mjs").resolve()),
        "--config",
        str(config_path.resolve()),
    ]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _env_override(name: str, fallback: str) -> str:
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    return raw.strip() or fallback


def _float_override(name: str, fallback: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    return float(raw)


def _bool_override(name: str, fallback: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return fallback


def _command_override(name: str, fallback: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None:
        return tuple(str(item) for item in fallback)
    return tuple(shlex.split(raw))
