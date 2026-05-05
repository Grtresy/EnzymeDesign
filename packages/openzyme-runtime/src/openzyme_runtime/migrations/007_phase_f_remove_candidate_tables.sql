INSERT INTO artifact_records (
    artifact_id,
    episode_id,
    run_id,
    kind,
    storage_uri,
    created_at,
    title,
    description,
    tags_json,
    provenance_json,
    availability_json,
    metadata_json
)
SELECT
    candidate_id,
    episode_id,
    NULL,
    'other',
    'artifact://design-option/' || candidate_id,
    created_at,
    title,
    summary,
    '["design-option"]',
    '{"source_type":"generated","legacy_source":"candidate_record"}',
    '{"local_readable":false,"execution_input":false}',
    json_object(
        'semantic_type', 'design_option',
        'supporting_evidence_ids', json(COALESCE(supporting_evidence_ids_json, '[]'))
    )
FROM candidate_records
WHERE NOT EXISTS (
    SELECT 1 FROM artifact_records WHERE artifact_records.artifact_id = candidate_records.candidate_id
);

DROP TABLE IF EXISTS selected_candidates;
DROP TABLE IF EXISTS candidate_rankings;
DROP TABLE IF EXISTS candidate_records;
