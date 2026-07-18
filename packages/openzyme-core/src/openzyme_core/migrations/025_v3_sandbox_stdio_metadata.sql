ALTER TABLE sandbox_run_records
    ADD COLUMN stdout_metadata_json TEXT;

ALTER TABLE sandbox_run_records
    ADD COLUMN stderr_metadata_json TEXT;
