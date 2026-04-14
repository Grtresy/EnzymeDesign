ALTER TABLE artifact_records ADD COLUMN title TEXT;
ALTER TABLE artifact_records ADD COLUMN description TEXT;
ALTER TABLE artifact_records ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE artifact_records ADD COLUMN provenance_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE artifact_records ADD COLUMN availability_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE artifact_records ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';
