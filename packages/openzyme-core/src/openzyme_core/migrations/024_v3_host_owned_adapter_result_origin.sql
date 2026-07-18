PRAGMA foreign_keys = ON;

-- This provenance bit is deliberately outside adapter_result_envelope_json.
-- Historical S12 callers could populate that JSON, so a value inside it cannot
-- prove that the Host adapter executor produced the persisted result.
ALTER TABLE controlled_operation_records ADD COLUMN adapter_result_origin TEXT;
