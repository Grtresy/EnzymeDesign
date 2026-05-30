PRAGMA foreign_keys = ON;

ALTER TABLE controlled_operation_records ADD COLUMN adapter_envelope_schema_version TEXT;
ALTER TABLE controlled_operation_records ADD COLUMN sdk_module TEXT;
ALTER TABLE controlled_operation_records ADD COLUMN function_name TEXT;
ALTER TABLE controlled_operation_records ADD COLUMN route_policy_id TEXT;
ALTER TABLE controlled_operation_records ADD COLUMN placement TEXT;
ALTER TABLE controlled_operation_records ADD COLUMN hpc_workspace_id TEXT;
ALTER TABLE controlled_operation_records ADD COLUMN selected_backend TEXT;
ALTER TABLE controlled_operation_records ADD COLUMN resource_class TEXT;
ALTER TABLE controlled_operation_records ADD COLUMN runtime_packaging_id TEXT;
ALTER TABLE controlled_operation_records ADD COLUMN toolchain_id TEXT;
ALTER TABLE controlled_operation_records ADD COLUMN provider_config_digest TEXT;
ALTER TABLE controlled_operation_records ADD COLUMN input_artifact_ids_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE controlled_operation_records ADD COLUMN stage_refs_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE controlled_operation_records ADD COLUMN planned_fetch_intent_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE controlled_operation_records ADD COLUMN approval_requirement_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE controlled_operation_records ADD COLUMN adapter_approval_envelope_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE controlled_operation_records ADD COLUMN adapter_result_envelope_json TEXT NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_controlled_operations_route_policy
    ON controlled_operation_records(route_policy_id);

CREATE INDEX IF NOT EXISTS idx_controlled_operations_sdk_module
    ON controlled_operation_records(sdk_module, function_name);
