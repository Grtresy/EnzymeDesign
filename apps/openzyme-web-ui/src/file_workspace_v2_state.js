export const FILE_WORKSPACE_PUBLIC_V2_SCHEMA = "file_workspace_public@2";
export const FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE =
  "application/vnd.openzyme.file-workspace+json;version=2";

export const FILE_WORKSPACE_V2_CORE_FIELDS = Object.freeze([
  "agents",
  "approvals",
  "authority_leases",
  "capability_binding",
  "conversation",
  "failures",
  "lanes",
  "operations",
  "protocol",
  "publications",
  "runtime",
  "session",
  "tasks",
  "tool_reflection",
  "workspace",
]);

const ARRAY_CORE_FIELDS = new Set([
  "agents",
  "approvals",
  "authority_leases",
  "lanes",
  "publications",
  "tasks",
]);

const FORBIDDEN_CORE_TOKENS = new Set([
  "alphafold",
  "aox",
  "arti" + "fact",
  "arti" + "factcatalog",
  "arti" + "factindex",
  "arti" + "facts",
  "compute",
  "docking",
  "fpocket",
  "hpc",
  "hmmer",
  "reportdrafts",
  "reports",
  "research",
  "revisionexecutions",
  "scientificattempts",
  "scientificdeliverables",
  "scientificselections",
  "vina",
]);

const FORBIDDEN_CORE_FRAGMENTS = [
  "accesstoken",
  "credential",
  "hostpath",
  "loginalias",
  "privatekey",
  "privateref",
  "refreshtoken",
  "remoteroot",
  "repositoryroot",
  "schedulerhandle",
  "storageuri",
];

const DIGEST = /^sha256:[0-9a-f]{64}$/;
export const FILE_WORKSPACE_V2_RELEASE_FIELDS = Object.freeze([
  "adapter_bundle_digest",
  "client_build_digest",
  "core_schema_digest",
  "declared_tool_catalog_digest",
  "extension_bundle_digest",
  "host_build_digest",
  "kernel_contract_digest",
  "migration_catalog_digest",
  "projection_catalog_digest",
  "public_contract_digest",
  "release_digest",
  "route_catalog_digest",
  "schema_version",
  "workspace_backend_digest",
]);
const OBJECT_SECTION_FIELDS = Object.freeze({
  conversation: ["memories", "messages"],
  failures: ["observations"],
  operations: [
    "command_receipts",
    "continuations",
    "controlled",
    "publication_intents",
    "task_evidence",
  ],
  protocol: ["inbox", "records"],
  runtime: [
    "continuation_intents",
    "outcome_consumptions",
    "session_leases",
    "settlement_intents",
    "signals",
    "turn_commands",
  ],
  workspace: [
    "checkpoints",
    "generations",
    "repository_binding_pins",
    "revision_path_verifications",
    "runtime_bindings",
  ],
});
const TOOL_REFLECTION_FIELDS = Object.freeze([
  "affordance_snapshot_digest",
  "affordances",
  "available_tool_names",
  "capability_binding_digest",
  "declared_tool_catalog_digest",
]);
const TOOL_AFFORDANCE_FIELDS = Object.freeze([
  "blockers",
  "required_authorities",
  "route_ids",
  "route_refs",
  "state",
  "tool_contract_digest",
  "tool_name",
]);
const PUBLIC_TOOL_STATES = new Set([
  "available",
  "available_with_approval",
  "blocked_dependency",
  "blocked_configuration",
  "blocked_qualification",
  "blocked_authority",
  "blocked_provisioning",
  "temporarily_unavailable",
]);

function normalizedToken(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]/g, "");
}

function requireDigest(value, field) {
  if (typeof value !== "string" || !DIGEST.test(value)) {
    throw new Error(`${field} must be a canonical SHA-256 digest`);
  }
}

function requireExactKeys(value, expected, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${field} must be an object`);
  }
  const observed = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (JSON.stringify(observed) !== JSON.stringify(wanted)) {
    throw new Error(`${field} fields are closed`);
  }
}

function rejectExtensionFieldsInCore(value, path = "core") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => rejectExtensionFieldsInCore(item, `${path}[${index}]`));
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, nested] of Object.entries(value)) {
    const token = normalizedToken(key);
    if (
      FORBIDDEN_CORE_TOKENS.has(token)
      || FORBIDDEN_CORE_FRAGMENTS.some((fragment) => token.includes(fragment))
    ) {
      throw new Error(`file_workspace_public@2 core contains forbidden field ${path}.${key}`);
    }
    rejectExtensionFieldsInCore(nested, `${path}.${key}`);
  }
}

function requireRelease(release) {
  requireExactKeys(release, FILE_WORKSPACE_V2_RELEASE_FIELDS, "file_workspace_public@2 release");
  if (release.schema_version !== "openzyme_layered_release_identity@1") {
    throw new Error("file_workspace_public@2 release schema is unsupported");
  }
  for (const field of FILE_WORKSPACE_V2_RELEASE_FIELDS.filter((name) => name !== "schema_version")) {
    requireDigest(release[field], `release.${field}`);
  }
}

export function requireExactReleaseIdentity(observed, expected) {
  requireRelease(observed);
  requireRelease(expected);
  for (const field of FILE_WORKSPACE_V2_RELEASE_FIELDS) {
    if (observed[field] !== expected[field]) {
      throw new Error(`file_workspace_public@2 release identity drift: ${field}`);
    }
  }
  return structuredClone(observed);
}

function requireToolReflection(core, release) {
  const reflection = core.tool_reflection;
  requireExactKeys(reflection, TOOL_REFLECTION_FIELDS, "core.tool_reflection");
  requireDigest(reflection.declared_tool_catalog_digest, "tool_reflection.declared_tool_catalog_digest");
  requireDigest(reflection.affordance_snapshot_digest, "tool_reflection.affordance_snapshot_digest");
  requireDigest(reflection.capability_binding_digest, "tool_reflection.capability_binding_digest");
  requireDigest(core.capability_binding.binding_digest, "capability_binding.binding_digest");
  if (reflection.declared_tool_catalog_digest !== release.declared_tool_catalog_digest) {
    throw new Error("tool reflection belongs to another declared catalog");
  }
  if (reflection.capability_binding_digest !== core.capability_binding.binding_digest) {
    throw new Error("tool reflection belongs to another capability binding");
  }
  if (!Array.isArray(reflection.available_tool_names) || !Array.isArray(reflection.affordances)) {
    throw new Error("tool reflection collections are invalid");
  }
  const observed = new Set();
  const visible = [];
  for (const affordance of reflection.affordances) {
    requireExactKeys(affordance, TOOL_AFFORDANCE_FIELDS, "tool affordance");
    if (typeof affordance.tool_name !== "string" || !affordance.tool_name) {
      throw new Error("tool affordance name is invalid");
    }
    if (observed.has(affordance.tool_name)) {
      throw new Error("tool affordance name is duplicated");
    }
    observed.add(affordance.tool_name);
    requireDigest(affordance.tool_contract_digest, `${affordance.tool_name}.tool_contract_digest`);
    if (!PUBLIC_TOOL_STATES.has(affordance.state)) {
      throw new Error("tool affordance state is invalid");
    }
    for (const field of ["blockers", "required_authorities", "route_ids", "route_refs"]) {
      if (!Array.isArray(affordance[field])) {
        throw new Error(`tool affordance ${field} is invalid`);
      }
    }
    if (affordance.state === "available" || affordance.state === "available_with_approval") {
      if (affordance.blockers.length) {
        throw new Error("available tool affordance contains blockers");
      }
      visible.push(affordance.tool_name);
    }
  }
  if (JSON.stringify(reflection.available_tool_names) !== JSON.stringify(visible)) {
    throw new Error("available tool names differ from public affordances");
  }
}

function requireCore(core, release) {
  requireExactKeys(core, FILE_WORKSPACE_V2_CORE_FIELDS, "file_workspace_public@2 core");
  for (const field of FILE_WORKSPACE_V2_CORE_FIELDS) {
    if (ARRAY_CORE_FIELDS.has(field)) {
      if (!Array.isArray(core[field])) {
        throw new Error(`file_workspace_public@2 core.${field} must be an array`);
      }
    } else if (!core[field] || typeof core[field] !== "object" || Array.isArray(core[field])) {
      throw new Error(`file_workspace_public@2 core.${field} must be an object`);
    }
  }
  for (const [section, fields] of Object.entries(OBJECT_SECTION_FIELDS)) {
    requireExactKeys(core[section], fields, `core.${section}`);
    for (const field of fields) {
      if (!Array.isArray(core[section][field])) {
        throw new Error(`core.${section}.${field} must be an array`);
      }
    }
  }
  rejectExtensionFieldsInCore(core);
  requireToolReflection(core, release);
}

function requireExtensionSections(extensions) {
  if (!extensions || typeof extensions !== "object" || Array.isArray(extensions)) {
    throw new Error("file_workspace_public@2 extensions must be an object");
  }
  for (const [sectionId, section] of Object.entries(extensions)) {
    if (!sectionId || sectionId.trim() !== sectionId) {
      throw new Error("extension section id is invalid");
    }
    requireExactKeys(
      section,
      ["next_cursor", "payload", "projection_digest", "section_contract_digest"],
      `extensions.${sectionId}`,
    );
    requireDigest(section.section_contract_digest, `${sectionId}.section_contract_digest`);
    requireDigest(section.projection_digest, `${sectionId}.projection_digest`);
    if (section.next_cursor !== null && typeof section.next_cursor !== "string") {
      throw new Error(`${sectionId}.next_cursor is invalid`);
    }
    if (!section.payload || typeof section.payload !== "object" || Array.isArray(section.payload)) {
      throw new Error(`${sectionId}.payload must be an object`);
    }
  }
}

export function requireFileWorkspaceV2Projection(payload) {
  requireExactKeys(payload, ["core", "extensions", "release", "schema_version"], "file_workspace_public@2");
  if (payload.schema_version !== FILE_WORKSPACE_PUBLIC_V2_SCHEMA) {
    throw new Error("unsupported file_workspace_public@2 schema");
  }
  requireRelease(payload.release);
  requireCore(payload.core, payload.release);
  requireExtensionSections(payload.extensions);
  return structuredClone(payload);
}

export function requireAvailableTool(coreState, toolName) {
  const affordance = coreState?.core?.tool_reflection?.affordances?.find(
    (item) => item.tool_name === toolName,
  );
  if (!affordance) {
    throw new Error(`tool ${toolName} is absent from the exact affordance snapshot`);
  }
  if (affordance.state !== "available" && affordance.state !== "available_with_approval") {
    const blockerCodes = affordance.blockers.map((item) => item.code).join(",") || affordance.state;
    throw new Error(`tool ${toolName} is blocked: ${blockerCodes}; fallback_performed=false`);
  }
  return structuredClone(affordance);
}

export function reduceFileWorkspaceV2CoreEvent(state, event) {
  if (!event || event.schema_version !== FILE_WORKSPACE_PUBLIC_V2_SCHEMA) {
    return {
      ...state,
      contractBlocked: true,
      mutationAllowed: false,
      blockingError: "stale file_workspace_public@2 event contract",
    };
  }
  return {
    ...state,
    refreshRequired: true,
    lastEventId: event.event_id,
  };
}
