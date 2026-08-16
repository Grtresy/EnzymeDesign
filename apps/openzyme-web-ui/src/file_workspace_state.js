export const FILE_WORKSPACE_PUBLIC_SCHEMA = "file_workspace_public@1";

const REQUIRED_ARRAY_SECTIONS = [
  "agent_workspaces",
  "workspace_status",
  "private_revisions",
  "published_revisions",
  "reports",
  "scientific_deliverables",
  "external_jobs",
  "external_job_results",
  "capability_leases",
];

export function requireFileWorkspaceProjection(
  payload,
  { toolCatalogDigest, schemaBundleDigest },
) {
  if (!payload || payload.schema_version !== FILE_WORKSPACE_PUBLIC_SCHEMA) {
    throw new Error("unsupported file-workspace public schema");
  }
  if (
    payload.tool_catalog_digest !== toolCatalogDigest
    || payload.schema_bundle_digest !== schemaBundleDigest
  ) {
    throw new Error("file-workspace release bundle mismatch");
  }
  for (const section of REQUIRED_ARRAY_SECTIONS) {
    if (!Array.isArray(payload[section])) {
      throw new Error(`file-workspace section ${section} is invalid`);
    }
  }
  return structuredClone(payload);
}

export function reduceFileWorkspaceEvent(state, event) {
  if (!event || event.schema_version !== FILE_WORKSPACE_PUBLIC_SCHEMA) {
    return {
      ...state,
      blocked: true,
      blocking_error: "stale file-workspace event contract",
    };
  }
  return {
    ...state,
    refresh_required: true,
    last_event_id: event.event_id,
  };
}
