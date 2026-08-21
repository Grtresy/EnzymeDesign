export type Sha256Digest = `sha256:${string}`;

export type PublicToolAffordanceState =
  | "available"
  | "available_with_approval"
  | "blocked_dependency"
  | "blocked_configuration"
  | "blocked_qualification"
  | "blocked_authority"
  | "blocked_provisioning"
  | "temporarily_unavailable";

export interface PublicToolAffordance {
  tool_name: string;
  tool_contract_digest: Sha256Digest;
  state: PublicToolAffordanceState;
  required_authorities: string[];
  route_ids: string[];
  route_refs: Record<string, unknown>[];
  blockers: Array<{
    code: string;
    requirement: string | null;
    target_id: string | null;
  }>;
}

export interface LayeredReleaseIdentityV2 {
  schema_version: "openzyme_layered_release_identity@1";
  kernel_contract_digest: Sha256Digest;
  core_schema_digest: Sha256Digest;
  adapter_bundle_digest: Sha256Digest;
  extension_bundle_digest: Sha256Digest;
  declared_tool_catalog_digest: Sha256Digest;
  route_catalog_digest: Sha256Digest;
  projection_catalog_digest: Sha256Digest;
  migration_catalog_digest: Sha256Digest;
  workspace_backend_digest: Sha256Digest;
  host_build_digest: Sha256Digest;
  client_build_digest: Sha256Digest;
  release_digest: Sha256Digest;
  public_contract_digest: Sha256Digest;
}

export interface FileWorkspaceV2Core {
  session: Record<string, unknown>;
  tasks: Record<string, unknown>[];
  lanes: Record<string, unknown>[];
  agents: Record<string, unknown>[];
  protocol: Record<string, unknown>;
  conversation: Record<string, unknown>;
  approvals: Record<string, unknown>[];
  authority_leases: Record<string, unknown>[];
  capability_binding: Record<string, unknown> & { binding_digest: Sha256Digest };
  runtime: Record<string, unknown>;
  workspace: Record<string, unknown>;
  publications: Record<string, unknown>[];
  operations: Record<string, unknown>;
  failures: Record<string, unknown>;
  tool_reflection: {
    declared_tool_catalog_digest: Sha256Digest;
    affordance_snapshot_digest: Sha256Digest;
    capability_binding_digest: Sha256Digest;
    available_tool_names: string[];
    affordances: PublicToolAffordance[];
  };
}

export interface FileWorkspaceV2ExtensionSection {
  section_contract_digest: Sha256Digest;
  payload: Record<string, unknown>;
  next_cursor: string | null;
  projection_digest: Sha256Digest;
}

export interface FileWorkspacePublicV2 {
  schema_version: "file_workspace_public@2";
  release: LayeredReleaseIdentityV2;
  core: FileWorkspaceV2Core;
  extensions: Record<string, FileWorkspaceV2ExtensionSection>;
}
