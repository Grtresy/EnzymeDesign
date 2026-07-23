## ADDED Requirements

### Requirement: Scientific disposition never rewrites execution truth
A scientific selection or disposition SHALL reference canonical controlled-operation execution and result identities without changing their status, approval, effect certainty, retry eligibility, backend facts, or artifact lineage. Execution records MUST remain the exhaustive occurrence authority after adoption, supersession, failure, abandonment, or attempt closure.

#### Scenario: Supersede a completed operation
- **WHEN** an agent supersedes a completed operation with another adopted occurrence
- **THEN** the original execution remains completed and auditable while only its scientific disposition changes in the separate selection revision

#### Scenario: Dispose a failed operation
- **WHEN** an agent marks a terminal known failure as `failed`
- **THEN** the disposition does not convert the execution to no-effect or remove its failure evidence
