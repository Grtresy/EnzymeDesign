## ADDED Requirements

### Requirement: Live qualification backends require exact selected bindings
A live qualification backend MUST be constructed only through an Adapter- or Driver-owned probe bridge whose component version and digest match the selected Distribution binding, resolved real subject, exact operation, credential locator, budget lease and occurrence authorization. Distribution MAY compose and verify bridge metadata but MUST NOT implement raw Provider, Git, container, SSH, Slurm or scientific-process effects or fall back to another installed implementation.

#### Scenario: Adjacent Adapter is installed
- **WHEN** the selected binding cannot build its qualification bridge but another compatible-looking Adapter is importable
- **THEN** factory construction fails with the selected binding identity and does not use the adjacent Adapter

#### Scenario: Plan-only factory receives a credential locator
- **WHEN** the workflow is not occurrence-authorized
- **THEN** the factory exposes only safe bridge metadata and never resolves or passes credential material
