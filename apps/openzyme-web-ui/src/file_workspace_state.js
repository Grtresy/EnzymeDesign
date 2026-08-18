export const FILE_WORKSPACE_PUBLIC_SCHEMA = "file_workspace_public@1";
export const WORKSPACE_CHANGED_PATHS_PAGE_SCHEMA = "workspace_changed_paths_page@1";

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
  "failure_observations",
];

const PRIVATE_DIAGNOSTIC_KEYS = new Set([
  "private_diagnostic",
  "private_diagnostic_record",
  "traceback",
]);

function rejectPrivateDiagnosticPayload(value) {
  if (Array.isArray(value)) {
    value.forEach(rejectPrivateDiagnosticPayload);
    return;
  }
  if (!value || typeof value !== "object") {
    return;
  }
  for (const [key, nested] of Object.entries(value)) {
    if (PRIVATE_DIAGNOSTIC_KEYS.has(key)) {
      throw new Error(`private diagnostic field ${key} is forbidden in public workspace state`);
    }
    rejectPrivateDiagnosticPayload(nested);
  }
}

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
  rejectPrivateDiagnosticPayload(payload);
  return structuredClone(payload);
}

export function requireWorkspaceChangedPathsPage(
  payload,
  { workspaceId, workspaceGeneration },
) {
  if (!payload || payload.schema_version !== WORKSPACE_CHANGED_PATHS_PAGE_SCHEMA) {
    throw new Error("unsupported changed-paths page schema");
  }
  if (
    payload.workspace_id !== workspaceId
    || payload.workspace_generation !== workspaceGeneration
  ) {
    throw new Error("changed-paths page workspace identity is stale");
  }
  if (!Array.isArray(payload.paths) || !payload.paths.every((path) => typeof path === "string")) {
    throw new Error("changed-paths page paths are invalid");
  }
  if (payload.continuation !== null && typeof payload.continuation !== "string") {
    throw new Error("changed-paths page continuation is invalid");
  }
  rejectPrivateDiagnosticPayload(payload);
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
