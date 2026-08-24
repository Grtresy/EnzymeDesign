## ADDED Requirements

### Requirement: Cutover planning closes two source identities without evidence promotion
The system MUST build an effect-free cutover plan that separately binds the exact qualification source identity, deployment source identity, immutable Batch 1 receipt set, qualified-owner compatibility proof, Distribution/wheel/configuration/schema/target inventory closure, protected runtime root, adoption set, quiescence, backups, monitoring, rollback policy and AlphaFold omission. The compatibility proof MUST reject any change to a qualified Adapter, Driver, workload, validator, subject, build, configuration or unit closure; it MUST NOT claim that the later deployment source itself was qualification-tested.

#### Scenario: Only cutover governance paths changed after qualification
- **WHEN** the deployment source differs from the qualification source only in explicitly inventoried cutover governance and adoption paths while every qualified owner closure remains identical
- **THEN** the plan records both source identities and may use the compatibility proof without rewriting any qualification receipt

#### Scenario: One qualified Driver changed
- **WHEN** the deployment source changes a qualified workload or validator closure
- **THEN** planning stops with source incompatibility before authority creation, credentials or deployment mutation

### Requirement: Protected deployment state is exact and secret-safe
The deployment root MUST be `/home/grtresy/.local/state/openzyme/deployments/enzymedesign-qualified-runtime`, owned by the current operator uid with mode `0700`, contain no symlink component, and store plan, authority, backup manifest, adoption ledger, activation state, startup proof, monitoring and cutover receipts as canonical mode-`0600` files. Ambient environment values MUST NOT be deployment truth, and public artifacts MUST NOT contain credential material, private diagnostics, raw streams or tracebacks.

#### Scenario: Runtime root is a symlink
- **WHEN** bootstrap observes a symlink or wrong owner/mode at any protected deployment component
- **THEN** it fails before reading qualification evidence or mutating deployment state

### Requirement: Cutover requires a distinct durable one-shot authority
Every cutover execution MUST require a create-once authority binding the exact plan digest, deployment source, operator and occurrence. Qualification, preparation, helper-deployment, P0–P16 decision or environment flags MUST NOT substitute. A terminal stored occurrence MUST be restored without redispatch; a nonterminal residual occurrence MUST stop for same-occurrence reconciliation and MUST NOT be overwritten, retried or rerouted.

#### Scenario: Qualification authority is supplied to cutover
- **WHEN** an executor receives a valid Batch 1 qualification authority but no exact cutover authority
- **THEN** it stops before backup, adoption or activation with zero mutation

### Requirement: Adoption consumes only current exact Batch 1 receipts
The executor MUST independently verify all 44 Batch 1 receipts and their receipt-set report immediately before mutation, including authorization, source, unit, subject, route, operation, schema, negative gate, budget, cleanup, integrity and validity interval. It MUST create exactly one `QualifiedExternalCapabilityFact` per accepted unit and MUST reject missing, duplicate, expired, rejected or drifted evidence. It MUST NOT adopt AlphaFold, broaden one operation, refresh TTL, choose another route or perform fallback.

#### Scenario: Provider receipt expires before activation
- **WHEN** any required Batch 1 receipt reaches `valid_until` before deployment mutation
- **THEN** the entire cutover remains blocked and no reduced profile or automatic requalification is attempted

#### Scenario: AlphaFold receipt is absent
- **WHEN** the Batch 1 receipt set is complete and AlphaFold remains deferred/non-qualified
- **THEN** cutover may adopt only Batch 1 and the startup proof must keep AlphaFold unadvertised and blocked

### Requirement: Quiescence and recoverable backup precede activation
All declared Host, Plugin worker, Agent runtime, process, runner, UI, SQLite and Git writer surfaces MUST be stopped or isolated with zero unsettled or unknown external effects before mutation. The executor MUST then create independently verifiable backups for SQLite, configuration, target inventory, wheel lock, qualification evidence and adoption ledger. Dual write MUST remain forbidden.

#### Scenario: One unknown external effect remains
- **WHEN** quiescence observes an unsettled or unknown effect
- **THEN** cutover stops before backup/adoption activation and preserves the same occurrence for reconciliation

### Requirement: Activation is atomic and requires startup readback
Deployment state and adoption ledger MUST be installed through same-parent staged, fsynced, atomic replacement. A cutover receipt MUST be issued only after read-only startup proof reconstructs the exact Distribution, wheels, schema, Adapter/Plugin/Driver mount, 44 adopted facts, runtime qualification admission, blocked AlphaFold and monitoring wiring. The receipt MUST state `cutover=true` and `live_occurrence=false`.

#### Scenario: Runtime mounts but one adopted fact is absent
- **WHEN** startup readback finds the expected composition but only 43 exact facts
- **THEN** no cutover receipt is issued and the pre-first-live recovery policy is applied

### Requirement: Rollback becomes forward-only after first live acceptance
Before the first post-cutover live effect is accepted, recovery MAY compare the current deployment digests and restore only exact pre-activation backups. Unknown drift MUST be left untouched and reported. Once any post-cutover live occurrence is accepted or has unknown effect certainty, the deployment MUST atomically enter a forward-only boundary; old deployment restore and automatic rollback are forbidden, and recovery MUST quiesce, reconcile and forward-repair while preserving evidence.

#### Scenario: Startup fails before any live effect
- **WHEN** activation changed only this occurrence's exact deployment state and startup readback fails before live dispatch
- **THEN** executor may compare-and-restore the exact backup and records a rollback receipt

#### Scenario: First live response is lost after acceptance
- **WHEN** the post-cutover backend may have accepted the exact occurrence before its response is lost
- **THEN** the system records the forward-only boundary and reconciles the same occurrence without restoring or redispatching

### Requirement: Monitoring and post-cutover smoke preserve authority boundaries
Monitoring MUST expose bounded redacted deployment, adoption, expiry, startup, cutover, first-live and diagnostic facts without credentials or private paths. Post-cutover smoke MUST use a separate occurrence identity and authority, select only an adopted Batch 1 route, use `max_retries=0`, and perform no fallback. Neither cutover receipt nor smoke success MUST authorize future live occurrences or claim AlphaFold availability.

#### Scenario: Cutover receipt is offered as live authority
- **WHEN** an external operation has a valid cutover receipt but no occurrence authority
- **THEN** dispatch fails before credential resolution or external effect

