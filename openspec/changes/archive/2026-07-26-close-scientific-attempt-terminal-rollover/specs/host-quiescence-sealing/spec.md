## MODIFIED Requirements

### Requirement: Freeze closes writer admission before waiting
The Host MUST enter `freezing` through one transaction that increments the mutation fence and closes new writer admission before checking active writers. Existing writers MUST retain only the authority required to retire or commit work allowed by the freeze policy; stale-generation writers and all new registrations MUST be rejected. Session-scoped writer selection, nested-parent validation, and writer registration MUST share one atomic ordering against freeze and follow-up scope creation. The Host MUST distinguish expected zero-open or closed-during-registration coordination from ambiguous open-scope cardinality through a closed typed reason without weakening the fence.

#### Scenario: Begin freeze
- **WHEN** an authorized owner requests closure of an open scope
- **THEN** the Host atomically records `freezing`, advances the fence, and prevents new writer registration

#### Scenario: Late writer registration races freeze
- **WHEN** a writer registration races with the freeze transaction
- **THEN** exactly one ordering wins and no writer can become active under the closed generation after freeze commits

#### Scenario: Stale callback writes after freeze
- **WHEN** a callback holding the previous generation attempts a canonical commit after freeze
- **THEN** the repository rejects the commit before any canonical row, artifact, event, report, or ledger changes

#### Scenario: Session writer is admitted atomically
- **WHEN** a session has exactly one open mutation scope and a writer is admitted
- **THEN** scope selection, parent validation, generation/fence validation, and registration commit in one atomic ordering

#### Scenario: Freeze wins session writer admission
- **WHEN** freeze closes the only open scope before the atomic session writer admission commits
- **THEN** admission fails with the typed expected closed-admission reason and no writer row becomes active

#### Scenario: Open-scope cardinality is ambiguous
- **WHEN** session writer admission observes more than one open mutation scope
- **THEN** admission fails with the typed ambiguous-scope reason and MUST NOT be classified as a retryable rollover

#### Scenario: Session has never entered mutation authority
- **WHEN** a compatibility caller opens a writer turn for a session with no mutation-scope history
- **THEN** the Host preserves the existing untracked-session behavior without registering a writer

#### Scenario: Owning transaction observes an untracked session
- **WHEN** a Host-managed write transaction needs a nested writer turn and its stable transaction snapshot proves the session has no mutation-scope history
- **THEN** the Host preserves the local untracked-session behavior without opening a second writer connection or reacquiring its own SQLite write lock
