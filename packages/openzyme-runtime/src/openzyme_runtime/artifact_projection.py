from __future__ import annotations

from typing import Any


PRIVATE_ARTIFACT_KEYS = {
    "storage_uri",
    "local_path",
    "host_path",
    "sandbox_host_path",
    "source_storage_uri",
    "intermediate_storage_uri",
    "runner_path",
    "runner_config",
    "ssh_config",
}


def sanitize_private_artifact_fields(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in PRIVATE_ARTIFACT_KEYS:
                continue
            sanitized[key_text] = sanitize_private_artifact_fields(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_private_artifact_fields(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_private_artifact_fields(item) for item in value]
    return value


def project_artifact_for_agent(artifact: Any) -> dict[str, Any]:
    payload = dict(artifact.to_dict())
    payload.pop("storage_uri", None)
    return sanitize_private_artifact_fields(payload)


def project_artifacts_for_agent(artifacts: Any) -> list[dict[str, Any]]:
    return [project_artifact_for_agent(artifact) for artifact in artifacts]


__all__ = [
    "PRIVATE_ARTIFACT_KEYS",
    "project_artifact_for_agent",
    "project_artifacts_for_agent",
    "sanitize_private_artifact_fields",
]
