CREATE TABLE scientific_attempt_closure_response_records (
    closure_response_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL
        DEFAULT 'scientific_attempt_closure_response@1'
        CHECK (schema_version = 'scientific_attempt_closure_response@1'),
    closure_request_id TEXT NOT NULL UNIQUE
        REFERENCES scientific_attempt_closure_request_records(closure_request_id)
        ON DELETE RESTRICT,
    attempt_id TEXT NOT NULL UNIQUE
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    message_id TEXT NOT NULL UNIQUE
        REFERENCES inbox_messages(message_id) ON DELETE RESTRICT,
    document_id TEXT NOT NULL UNIQUE
        REFERENCES engine_documents(document_id) ON DELETE RESTRICT,
    recipient TEXT NOT NULL,
    recipient_kind TEXT NOT NULL,
    response_digest TEXT NOT NULL,
    binding_digest TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TRIGGER scientific_attempt_closure_response_matches
BEFORE INSERT ON scientific_attempt_closure_response_records
WHEN NOT EXISTS (
    SELECT 1
    FROM scientific_attempt_closure_request_records AS request
    JOIN scientific_attempt_records AS attempt
      ON attempt.attempt_id = request.attempt_id
    JOIN inbox_messages AS message
      ON message.message_id = NEW.message_id
     AND message.session_id = attempt.session_id
     AND message.sender = 'harness'
     AND message.sender_kind = 'harness'
     AND message.recipient = NEW.recipient
     AND message.recipient_kind = NEW.recipient_kind
     AND message.message_type = 'assistant_message'
     AND message.payload_ref = NEW.document_id
    JOIN engine_documents AS document
      ON document.document_id = NEW.document_id
     AND document.session_id = attempt.session_id
     AND document.document_kind = 'conversation_message'
    WHERE request.closure_request_id = NEW.closure_request_id
      AND request.attempt_id = NEW.attempt_id
)
BEGIN
    SELECT RAISE(
        ABORT,
        'scientific attempt closure response identity mismatch'
    );
END;

CREATE TRIGGER scientific_attempt_closure_response_records_immutable_update
BEFORE UPDATE ON scientific_attempt_closure_response_records
BEGIN
    SELECT RAISE(
        ABORT,
        'scientific attempt closure responses are immutable'
    );
END;

CREATE TRIGGER scientific_attempt_closure_response_records_immutable_delete
BEFORE DELETE ON scientific_attempt_closure_response_records
BEGIN
    SELECT RAISE(
        ABORT,
        'scientific attempt closure responses are immutable'
    );
END;

CREATE TRIGGER mutation_guard_scientific_attempt_closure_response_records_insert
BEFORE INSERT ON scientific_attempt_closure_response_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_closure_response_records_update
BEFORE UPDATE ON scientific_attempt_closure_response_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_closure_response_records_delete
BEFORE DELETE ON scientific_attempt_closure_response_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;
