PRAGMA foreign_keys = ON;

ALTER TABLE tasks ADD COLUMN failure_summary TEXT;
ALTER TABLE tasks ADD COLUMN failure_ref TEXT;
