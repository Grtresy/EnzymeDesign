## ADDED Requirements

### Requirement: Core owns the scientific-attempt terminal scope projection
Core MUST expose one typed, read-only projection of the monotonic handoff from an attempt mutation scope to its deterministic post-closure session scope. The projection MUST return only `rollover_pending` or `post_closure_scope_open`; every lifecycle, authority-envelope, identity, cardinality, parent, kind, or state inconsistency MUST fail closed with a bounded typed reason.

#### Scenario: Attempt closure rollover is pending
- **WHEN** the exact attempt lifecycle is `closure_requested`, its mutation scope is `freezing`, `quiescent`, or `sealed`, and the session has no open or competing nonterminal scope
- **THEN** Core returns `rollover_pending` without mutating either lifecycle or scope state

#### Scenario: Exact post-closure scope is open
- **WHEN** the exact attempt lifecycle is `closed`, its mutation scope is `sealed`, and exactly one open session child has the deterministic post-attempt ID, reference, and parent
- **THEN** Core returns `post_closure_scope_open` and identifies that child as the legal current writer scope

#### Scenario: Attempt envelope is missing or ambiguous
- **WHEN** the caller's exact session, task, campaign, workflow, or attempt envelope resolves zero or multiple attempts
- **THEN** Core rejects the projection instead of selecting a plausible attempt

#### Scenario: Post scope has drifted identity
- **WHEN** a child scope has a wrong ID, reference, session kind, session binding, or parent
- **THEN** Core rejects the topology even if that child is the only open scope

#### Scenario: Competing active scope exists
- **WHEN** multiple children, multiple open scopes, or an unrelated nonterminal scope coexist with the attempt rollover
- **THEN** Core rejects the topology as ambiguous

#### Scenario: Lifecycle and scope state disagree
- **WHEN** a closed lifecycle lacks a sealed attempt scope or a post scope exists before immutable closure
- **THEN** Core rejects the non-monotonic topology

### Requirement: AOX coordinates only a proven terminal rollover
The AOX terminal observer MUST enter bounded rollover coordination only when the original atomic writer-admission failure has an allowed expected coordination reason and the Core projection verifies the exact authorized scientific attempt. It MUST retry only the short observer/barrier read inside the original deadline and MUST preserve every unrelated admission, parent, identity, or topology error.

#### Scenario: Finalization completes before classification
- **WHEN** observer admission loses to freeze but the exact post-closure scope is already open before AOX classifies the failure
- **THEN** AOX retries the short observer against that post scope and can complete the terminal barrier read

#### Scenario: Classifier observes rollover pending
- **WHEN** observer admission loses to freeze and Core first projects `rollover_pending`
- **THEN** AOX waits within the original deadline until the exact post-closure scope opens, then retries only the short observer/barrier read

#### Scenario: Original admission was ambiguous
- **WHEN** the original writer-admission reason is ambiguous open-scope cardinality
- **THEN** AOX returns that failure immediately even if a later read happens to show one open scope

#### Scenario: Rollover deadline expires
- **WHEN** the exact legal rollover does not reach `post_closure_scope_open` before the original command deadline
- **THEN** AOX fails with `scientific_attempt_scope_rollover_stalled` and creates no new authority, drain, model call, tool call, or scope mutation

#### Scenario: Nonterminal observer path fails admission
- **WHEN** a writer-admission failure occurs outside the exact formal terminal observer path
- **THEN** AOX preserves the original failure without applying scientific rollover coordination

### Requirement: Terminal rollover diagnostics are safe and typed
Sealed AOX failure evidence MUST preserve only allowlisted bounded machine values needed to distinguish writer admission and rollover outcomes. It MUST NOT expose authority material, filesystem paths, prompts, private writer metadata, or unbounded exception text.

#### Scenario: Safe rollover failure is sealed
- **WHEN** a terminal observer fails during admission or rollover classification
- **THEN** sealed details may include the mutation-scope error code, admission reason, rollover phase, scope state, and bounded open-scope count

#### Scenario: Unsafe details accompany the exception
- **WHEN** an underlying error contains IDs, paths, tokens, prompts, or private writer records
- **THEN** those fields are excluded from sealed failure projection
