from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, Callable


CallImpl = Callable[[str, dict[str, Any]], dict[str, Any]]


class RunnerClient:
    def __init__(
        self,
        *,
        runner_bin: str = "mcp-hpc-runner",
        runner_config: str | Path | None = None,
        call_impl: CallImpl | None = None,
        timeout: float | None = None,
    ) -> None:
        self.runner_bin = runner_bin
        self.runner_config = Path(runner_config) if runner_config else None
        self._call_impl = call_impl
        self.timeout = timeout

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._call_impl is not None:
            return self._call_impl(name, arguments)

        cmd = [self.runner_bin]
        if self.runner_config is not None:
            cmd.extend(["--config", str(self.runner_config)])
        cmd.extend(["call-tool", "--name", name, "--arguments", json.dumps(arguments)])
        try:
            raw = subprocess.run(
                cmd, capture_output=True, text=True, check=False, timeout=self.timeout
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"mcp-hpc-runner call timed out after {self.timeout}s for {name}"
            ) from exc
        if raw.returncode != 0:
            stderr = raw.stderr.strip()
            raise RuntimeError(
                f"mcp-hpc-runner call failed ({raw.returncode}) for {name}: {stderr}"
            )
        payload = raw.stdout.strip()
        if not payload:
            return {}
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"mcp-hpc-runner returned invalid JSON for {name}"
            ) from exc
