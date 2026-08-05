## ADDED Requirements

### Requirement: External conductor identity is not Host runtime configuration truth
The current AOX runtime configuration MUST describe Host, model/provider, execution,
resource, reliability, and scientific-contract inputs only.  External Codex identity,
public command-surface claims, receipt/supervision schema claims, and sealed
`automatic_* = false` orchestration fields MUST live outside product runtime config and
MUST NOT affect agent or Host business behavior.

#### Scenario: Build a current runtime config
- **WHEN** a new AOX launch seals its effective runtime configuration
- **THEN** the canonical config contains no conductor or automatic-orchestration policy object

#### Scenario: Reverify historical runtime evidence
- **WHEN** frozen evidence contains a historical config with driver or conductor fields
- **THEN** the historical loader can verify exact bytes but the config cannot satisfy current launch admission

### Requirement: Supervision is policy-free process and evidence containment
Live-attempt supervision MUST start/stop the exact Host process, bind source/config/root
identity, preserve typed causal evidence, and prove local settlement.  It MUST NOT inject
agent tool policy, choose scientific actions, retry/relaunch an attempt, infer business
terminal state, or treat process exit as workflow acceptance.

#### Scenario: Start a supervised Host
- **WHEN** a current preflight authorizes Host startup
- **THEN** supervision composes the ordinary Host product path without an AOX tool-dispatch interceptor

#### Scenario: Retire after incomplete agent work
- **WHEN** the bounded process is retired while canonical workflow facts remain incomplete
- **THEN** supervision records process/evidence settlement and leaves product eligibility to canonical evaluators and the offline reducer
