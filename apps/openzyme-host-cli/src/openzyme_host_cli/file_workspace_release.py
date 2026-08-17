FILE_WORKSPACE_PUBLIC_SCHEMA = "file_workspace_public@1"
FILE_WORKSPACE_PUBLIC_MEDIA_TYPE = (
    "application/vnd.openzyme.file-workspace+json;version=1"
)
FILE_WORKSPACE_TOOL_CATALOG_DIGEST = (
    "sha256:48d1dbb40daf79e2eb52d0752bc1605b5a04cf681b35bf99a1a80806d5eab22e"
)
FILE_WORKSPACE_EXECUTOR_TOOL_CATALOG_DIGEST = (
    "sha256:6f779e28071a3ab14536b7cd4d89333c71343992f0c01f632ad29bffd57fb73c"
)
FILE_WORKSPACE_SCHEMA_BUNDLE_DIGEST = (
    "sha256:af450859355e263e668e8fbd17d4b73b24320d247263015cc9ad4922381fb250"
)
FILE_WORKSPACE_CLI_BUILD_DIGEST = (
    "sha256:122613c3e152838340e747bf5623fd9db179466b5bd0533dd6c3e0319ee17ca6"
)


def require_current_workspace(
    payload: object,
    *,
    tool_catalog_digest: str = FILE_WORKSPACE_TOOL_CATALOG_DIGEST,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("file-workspace response must be an object")
    workspace = payload.get("workspace", payload)
    if not isinstance(workspace, dict):
        raise ValueError("file-workspace response is missing workspace state")
    if (
        workspace.get("schema_version") != FILE_WORKSPACE_PUBLIC_SCHEMA
        or workspace.get("tool_catalog_digest")
        != tool_catalog_digest
        or workspace.get("schema_bundle_digest")
        != FILE_WORKSPACE_SCHEMA_BUNDLE_DIGEST
    ):
        raise ValueError("file-workspace release bundle mismatch")
    return dict(workspace)


__all__ = [
    "FILE_WORKSPACE_CLI_BUILD_DIGEST",
    "FILE_WORKSPACE_EXECUTOR_TOOL_CATALOG_DIGEST",
    "FILE_WORKSPACE_PUBLIC_MEDIA_TYPE",
    "FILE_WORKSPACE_PUBLIC_SCHEMA",
    "FILE_WORKSPACE_SCHEMA_BUNDLE_DIGEST",
    "FILE_WORKSPACE_TOOL_CATALOG_DIGEST",
    "require_current_workspace",
]
