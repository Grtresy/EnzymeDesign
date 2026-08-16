## ADDED Requirements

### Requirement: Supervision binds canonical attempt authority
The live supervisor SHALL accept only a canonical active attempt authority whose campaign, scope, root, nonce, process epoch, workflow/config digest, and authorization consumption match the launch request. Filesystem names, command-line labels, or child-reported ids MUST NOT create or extend attempt authority.

#### Scenario: Launch an authorized attempt
- **WHEN** the parent holds a valid unconsumed attempt authority matching the exact launch
- **THEN** it binds that authority id into the child protocol and supervision receipt

#### Scenario: Launch without authority
- **WHEN** a numbered live request lacks an exact one-attempt approval or durable envelope consumption
- **THEN** the supervisor rejects it before spawning a child or opening mutable roots

### Requirement: Fatal unknown outcome blocks envelope continuation
If fatal supervision cannot prove local retirement or exact external-effect outcome, the supervisor SHALL record the blocker against the governing attempt/campaign authority. Remaining envelope count or budget MUST NOT authorize another live attempt until canonical retirement and effect reconciliation clear the blocker.

#### Scenario: Child dies after possible provider dispatch
- **WHEN** the process group retires but the external effect remains unknown
- **THEN** parent fatal evidence is sealed, the campaign authority is blocked, and no next attempt is admitted

#### Scenario: Child fails before any effect
- **WHEN** retirement and canonical records prove no external effect and all writers are closed
- **THEN** the failed attempt remains non-eligible but does not create an unknown-effect blocker beyond its consumed slot
