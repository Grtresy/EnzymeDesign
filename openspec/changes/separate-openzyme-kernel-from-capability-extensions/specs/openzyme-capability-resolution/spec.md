## ADDED Requirements

### Requirement: Four capability fact classes are distinct
Kernel MUST distinguish ExtensionCapabilityFact, ResourceCapabilityFact, AuthorityGrant/AgentAuthorityLease and ToolAffordance. Their schemas, owners, persistence and digests MUST be distinct, and no fact MAY be treated as proof of another class.

#### Scenario: Installed Plugin is mistaken for authority
- **WHEN** a Plugin and compatible target are present but the Agent lacks the required authority grant
- **THEN** its tool is blocked before dispatch and installation does not authorize the Agent

#### Scenario: Authority is mistaken for software availability
- **WHEN** an Agent has `external_compute` authority but no qualified route provides required software
- **THEN** the tool is `BLOCKED_QUALIFICATION` rather than exposed as callable

### Requirement: Capability dependencies use contracts rather than package names
Every Plugin requirement MUST reference canonical capability ID, contract/version constraints, required operations and optional same-target constraints. Plugin runtime code MUST NOT import a provider Plugin implementation or select a provider by Python distribution name.

#### Scenario: HMMER requirements resolve on HPC
- **WHEN** HMMER requires revision compute and `software.hmmer >=3.3,<4` with build/search operations on one target
- **THEN** the resolver returns only routes whose exact providers and inventory facts satisfy every constraint

#### Scenario: Dependency graph contains a cycle
- **WHEN** activated Plugin requirements form a capability dependency cycle
- **THEN** deployment activation fails before writers, routes, workers or external effects start

### Requirement: Declared tool catalog is derived from activated manifests
`DeclaredToolCatalog` MUST be deterministically derived from Kernel base tools plus exact successfully activated Plugin manifests. It MUST include tool contract, owner, schema, governance, required authorities, capability requirements and contract digest, and duplicate canonical names MUST fail rather than overwrite.

#### Scenario: Engine registry registers a duplicate tool
- **WHEN** two contributions declare the same canonical dotted tool name
- **THEN** catalog construction rejects the complete activation and retains neither partial override

#### Scenario: Optional Plugin is absent
- **WHEN** a Distribution declares an optional Plugin whose wheel is not installed
- **THEN** no fabricated tool schema enters the declared catalog while safe inspection reports the missing Plugin capability

### Requirement: Tool affordance is resolved per subject and turn
Before every bounded turn Kernel MUST resolve a ToolAffordanceSnapshot from the Session bundle, capability binding revision, Agent authority, workspace generation/readiness, task/role policy, route inventory/health and approval governance. Affordance states MUST include AVAILABLE, AVAILABLE_WITH_APPROVAL, BLOCKED_DEPENDENCY, BLOCKED_CONFIGURATION, BLOCKED_QUALIFICATION, BLOCKED_AUTHORITY, BLOCKED_PROVISIONING, TEMPORARILY_UNAVAILABLE and HIDDEN.

#### Scenario: Build the model function list
- **WHEN** a turn snapshot contains available, blocked and hidden tools
- **THEN** only AVAILABLE and AVAILABLE_WITH_APPROVAL specs enter the model request

#### Scenario: Hidden capability is inspected
- **WHEN** the subject is not authorized to know a tool or route exists
- **THEN** the tool is absent from both the function list and `capabilities.inspect`

### Requirement: Target-bound route selection is explicit
Every target-bound formal tool call MUST carry one exact `route_id` selected by the Agent from its current affordance. Kernel, Plugin and Distribution MUST NOT infer a sole route, substitute another route or silently choose local execution.

#### Scenario: One compatible route exists
- **WHEN** a call omits `route_id` even though exactly one compatible route is available
- **THEN** validation returns a typed missing-route error with `effect_certainty=no_effect`

#### Scenario: Selected route becomes unavailable
- **WHEN** the selected route is down or stale at dispatch
- **THEN** dispatch fails without switching target, provider, software version or local process

### Requirement: Dispatch revalidates the exact affordance
Immediately before dispatch Kernel MUST revalidate the snapshot digest, Session capability binding, AgentAuthorityLease generation/fence, workspace generation, route/driver identity, target inventory generation, qualification validity and current health. Drift MUST return `tool_affordance_stale`, `effect_certainty=no_effect` and `fallback_performed=false`.

#### Scenario: Authority is revoked after model selection
- **WHEN** the model returns a previously visible call after its authority lease is revoked
- **THEN** dispatch rejects the call with no mutation or external effect

#### Scenario: Continuation resumes after a new route appears
- **WHEN** an existing operation continuation resumes after composition adds another route
- **THEN** it remains bound to the original route and does not migrate automatically

### Requirement: Capability inspection is safe and actionable
Kernel MUST provide `capabilities.inspect` for authorized subjects to inspect activated/inactive/degraded Plugin facts, declared-but-blocked tools, safe blockers, required capabilities, qualification validity and usable route proofs. It MUST redact credentials, private paths, binary locators, raw probe output, hidden capabilities and other Agents' targets.

#### Scenario: Inspect a missing HMMER requirement
- **WHEN** HMMER is declared but no bound inventory satisfies its version range
- **THEN** inspection reports `software_requirement_unsatisfied`, the safe range and affected target without exposing SSH or filesystem details

### Requirement: Capability identities use layered digests
Kernel contract, Adapter bundle, Extension bundle, declared tool catalog, route catalog, projection catalog, Session capability binding and turn affordance snapshot MUST use separate canonical digests. Transient target health MUST have a separate observation identity and MUST NOT alter a release contract digest.

#### Scenario: Target health changes
- **WHEN** a qualified target becomes temporarily unavailable without a manifest or inventory change
- **THEN** the release and declared catalog digests remain stable while a new affordance snapshot blocks dispatch

### Requirement: Capability resolution and documentation share one contract
Main architecture, `docs/v3/` control-plane/capability/runtime/public-interface documents, manifest schema reference and tool authoring docs MUST use the four fact classes, exact affordance states, route rule and digest split implemented by source.

#### Scenario: Documentation describes one static global tool list
- **WHEN** current documentation claims all installed tools are always exposed or one `tool_catalog_digest` represents runtime availability
- **THEN** source-to-document qualification fails
