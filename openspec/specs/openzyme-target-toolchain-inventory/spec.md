# openzyme-target-toolchain-inventory Specification

## Purpose
定义 operator-controlled target toolchain inventory、qualification spec/receipt、resource facts、显式 adoption、有效期与脱敏要求。
## Requirements
### Requirement: Target inventory generations are immutable and structured
Every qualified compute target MUST expose an immutable `TargetToolchainInventory` generation binding exact target/profile/provider identity, qualification policy, environment closure, generation time/validity and structured software, hardware, accelerator, dataset, asset and license capability facts. The existing aggregate toolchain digest MUST become the closure digest of this inventory.

#### Scenario: Record an HMMER software fact
- **WHEN** qualification verifies HMMER 3.4 with hmmbuild, hmmsearch and hmmpress operations
- **THEN** the inventory stores the canonical capability ID, semantic version, supported operations, environment/binary digests and qualification receipt digest

#### Scenario: Mutate an inventory generation
- **WHEN** software, environment, dataset or qualification facts change
- **THEN** the provider must publish a new generation rather than modifying the prior inventory

### Requirement: Tool Plugins declare qualification specifications
A Tool Plugin MUST provide a declarative QualificationSpec for each required external software/service, including capability ID, allowed version range, version query, deterministic smoke input, expected result schema, resource requirements and required asset/dataset/license facts. The spec MUST NOT contain target credentials or execute during import/turn resolution.

#### Scenario: Vina declares its requirements
- **WHEN** the Vina Plugin is activated
- **THEN** its manifest contributes a versioned Vina qualification spec without importing SSH or Slurm implementations

### Requirement: Qualification is operator-controlled and adapter-executed
Only an operator-controlled target qualification workflow MAY select a target and credential, ask the target provider to execute Plugin qualification specs through declared SSH/Slurm/process Adapters and publish receipts. A Plugin or Agent turn MUST NOT independently SSH, run `which`, cache an unbound version string or create a canonical resource fact.

#### Scenario: Agent turn tries to probe HMMER
- **WHEN** affordance resolution lacks a valid HMMER fact
- **THEN** it reports a qualification blocker and performs no probe or credential request

#### Scenario: Qualification adapter response is lost
- **WHEN** a target probe may have executed but its response is lost
- **THEN** the qualification operation reconciles the same identity and does not issue an automatic replacement probe

### Requirement: Qualification receipts bind the real execution environment
Every SoftwareQualificationReceipt MUST bind target/inventory generation, Plugin qualification spec, Adapter/provider identity, command/environment closure, bounded result/schema validation, execution time, validity and private diagnostic identity. Kernel MUST index only safe facts and digests; private paths, credentials and raw streams MUST remain protected.

#### Scenario: Job route uses a different environment
- **WHEN** a formal workload route does not bind the inventory/environment generation that produced its capability fact
- **THEN** route admission fails before dispatch

### Requirement: Session inventory adoption is explicit and operator-owned
Only operator/admin authority MAY publish, adopt or revoke an inventory generation for a Session by creating a monotonic `SessionCapabilityBindingRevision`. Agents MAY choose routes already present in the current revision but MUST NOT adopt a new generation or expand target access.

#### Scenario: Operator adopts a new inventory
- **WHEN** a valid newer generation is explicitly adopted for a Session
- **THEN** Kernel records a new binding revision and future turns use it while prior operation identities remain unchanged

#### Scenario: Agent requests automatic adoption
- **WHEN** an Agent asks a tool call to use an unbound newer inventory
- **THEN** admission rejects it with `no_effect` and no implicit binding mutation

### Requirement: Qualification validity and target health are separate
Inventory generation and qualification validity MUST be distinct from transient health. An expired/revoked qualification or explicit target-down observation MUST block new dispatch; scheduler queue depth or resource contention MUST NOT remove a route if the scheduler still accepts work.

#### Scenario: Target is busy but accepting jobs
- **WHEN** the scheduler is healthy and accepts submissions while resources are queued
- **THEN** the route remains available and exposes safe scheduling facts rather than disappearing

#### Scenario: Qualification expires
- **WHEN** the selected inventory receipt is past its validity boundary
- **THEN** new dispatch is blocked without probing, fallback or inventory auto-upgrade

### Requirement: Target inventory is namespaced and secret-safe
Detailed inventory/probe state MUST be owned by the target provider Plugin namespace. Kernel MAY persist generic safe capability facts and immutable owner refs required for resolution, but public projection MUST NOT expose binary paths, remote roots, login aliases to non-owners, credentials, license secrets or raw qualification output.

#### Scenario: Inspect another target
- **WHEN** an unauthorized Agent requests inventory details for another owner's target
- **THEN** the response omits both the facts and existence-sensitive locators according to visibility policy

### Requirement: Inventory implementation and documentation move together
HPC/Compute READMEs, target config examples, operator qualification guide, runner wire docs, main architecture and `docs/v3/execution-pipeline-docs/` MUST describe the structured inventory, qualification owner, validity, Session adoption and no-turn-probe rules implemented by source.

#### Scenario: Config still documents only toolchain digest
- **WHEN** current target configuration or docs treat an opaque `toolchain_digest` as sufficient proof of installed software
- **THEN** source-to-document qualification fails

### Requirement: Adopted external capability facts preserve exact qualification-unit identity
Any target/provider resource fact derived from external qualification MUST bind capability, operation, route, subject identity, source digest, build digest, configuration digest, qualification spec/validator identity, receipt digest and validity interval. The inventory MUST NOT broaden one observed operation into a capability-wide fact or reuse evidence across route, target/provider or digest drift.

#### Scenario: Only hmmbuild was observed
- **WHEN** qualification succeeds for `hmmbuild` but not `hmmsearch`
- **THEN** the adopted fact can satisfy only the exact hmmbuild operation

#### Scenario: Target image build changes
- **WHEN** the current build digest differs from the qualification unit
- **THEN** the old fact is stale and no route requiring that build is supplied

### Requirement: Qualification freshness and revocation fail closed per unit
Inventory adoption and capability resolution MUST reject expired, failed, revoked, duplicate, schema-invalid or identity-drifted qualification receipts independently for each unit. Rejection MUST preserve other exact valid routes but MUST NOT retry, substitute another subject or silently retain the previous fact for the rejected unit.

#### Scenario: Provider receipt expires during a Session
- **WHEN** a later affordance observation finds the receipt past `valid_until`
- **THEN** the route is omitted or blocked with `blocked_qualification`, while the pinned product bundle remains unchanged

+## ADDED Requirements

### Requirement: External qualification receipts have risk-based freshness and protected storage
Provider receipts MUST expire after 24 hours; Git/LFS, Podman, SSH, Slurm and AlphaFold receipts MUST expire after 7 days; HMMER, Vina, fpocket and preprocessing software receipts MUST expire after 30 days. Exact identity drift, operator revocation or protected-ledger integrity failure MUST invalidate the affected unit immediately. Canonical safe receipts MUST reside in a protected SQLite qualification ledger, while bounded private diagnostics reside in a protected evidence root linked only by `diagnostic_id`.

#### Scenario: Provider endpoint identity drifts before TTL
- **WHEN** the current endpoint or account locator digest differs from the receipt subject
- **THEN** the receipt is invalid immediately and no remaining TTL is honored

#### Scenario: Public receipt export is requested
- **WHEN** an operator exports qualification evidence
- **THEN** the JSON contains safe identities and digests but no credential material, private path, raw stream or traceback

### Requirement: Adoption preserves operation identity and remains explicit
Only an authorized operator adoption step MAY turn an unexpired qualification receipt into a Provider or target resource fact. Adoption MUST bind the exact operation, route, real subject, source, build, configuration, policy and receipt digests and MUST NOT broaden one operation, environment or batch into another; qualification execution itself MUST leave inventories and Session bindings unchanged.

#### Scenario: HMMER target has only hmmbuild evidence
- **WHEN** adoption is requested for both hmmbuild and hmmsearch
- **THEN** only hmmbuild can be adopted and hmmsearch remains blocked

#### Scenario: Qualification completes without adoption authority
- **WHEN** a real receipt is valid but no operator adoption decision exists
- **THEN** the receipt remains stored as qualification evidence and no runtime resource fact changes
