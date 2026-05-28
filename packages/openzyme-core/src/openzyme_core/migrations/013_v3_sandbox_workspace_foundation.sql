CREATE TABLE IF NOT EXISTS sandbox_image_records (
    image_ref TEXT PRIMARY KEY,
    image_digest TEXT,
    image_family TEXT NOT NULL,
    image_version TEXT NOT NULL,
    sandbox_protocol_version TEXT NOT NULL,
    manifest_schema_version TEXT NOT NULL,
    capabilities_declared_json TEXT NOT NULL,
    compatibility TEXT NOT NULL,
    compatibility_error TEXT,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sandbox_image_default
    ON sandbox_image_records(is_default)
    WHERE is_default = 1;

CREATE TABLE IF NOT EXISTS sandbox_workspace_records (
    sandbox_workspace_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    agent_member_id TEXT NOT NULL REFERENCES agent_members(member_id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    focus_task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    focus_lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    image_ref TEXT NOT NULL,
    image_digest TEXT,
    image_version TEXT,
    sandbox_protocol_version TEXT,
    image_compatibility TEXT NOT NULL,
    manifest_version TEXT NOT NULL,
    volume_digest TEXT,
    quota_summary_json TEXT NOT NULL,
    directory_summary_json TEXT NOT NULL,
    materialized_input_artifact_ids_json TEXT NOT NULL,
    registered_artifact_ids_json TEXT NOT NULL,
    source_code_artifact_ids_json TEXT NOT NULL,
    last_command_summary_json TEXT,
    last_error_json TEXT,
    created_at TEXT NOT NULL,
    last_attached_at TEXT NOT NULL,
    UNIQUE(session_id, agent_member_id),
    FOREIGN KEY (session_id, agent_id) REFERENCES agent_members(session_id, agent_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sandbox_workspace_session
    ON sandbox_workspace_records(session_id);

CREATE INDEX IF NOT EXISTS idx_sandbox_workspace_agent_member
    ON sandbox_workspace_records(agent_member_id);
