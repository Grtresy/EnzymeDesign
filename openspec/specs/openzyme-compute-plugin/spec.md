# openzyme-compute-plugin Specification

## Purpose
定义 revision-bound 通用 Compute Plugin 的 admission、durable dispatch occurrence、route、结果验证与 owner continuation 生命周期。
## Requirements
### Requirement: Revision-bound formal compute is an optional Plugin
`openzyme-compute` MUST own the generic lifecycle that turns an exact immutable workspace revision plus typed ExecutionWorkloadSpec into route-bound dispatch, observation, reconciliation, cancellation, terminal result and owner continuation. Standard without Compute MUST retain all Core collaboration, workspace and publication capabilities and initialize no compute job state.

#### Scenario: Activate Compute
- **WHEN** a Distribution includes the exact Compute manifest and its dependencies resolve
- **THEN** its tools, workers, routes, projection, migrations and runner wire identities enter the Session bundle

#### Scenario: Omit Compute
- **WHEN** Plugin-free Standard starts without the Plugin
- **THEN** publication remains usable and no formal compute or scheduler surface appears

### Requirement: Compute admission binds an exact immutable revision and route
Every formal workload MUST bind Session/Task/Agent authority, workspace generation, PublishedRevision/source ref, commit/tree, verified Git LFS closure, clean observation, workload contract/digest, explicit Agent-selected route ID, target inventory generation where applicable and idempotency identity. Host paths, mutable working trees, general artifact catalogs, implicit staging and implicit route selection MUST NOT be accepted.

#### Scenario: Admit a clean revision workload
- **WHEN** the owner submits a request whose exact revision/tree/LFS/authority/route facts verify
- **THEN** Compute records one identity-bound request and prepares only that immutable tree for dispatch

#### Scenario: Request omits route
- **WHEN** a formal workload omits route ID or names a dirty private path
- **THEN** admission fails with no auto-publish, staging, backend selection or external effect

### Requirement: ExecutionWorkloadSpec is typed and provider-neutral
ExecutionWorkloadSpec MUST contain a versioned workload contract, exact argv or declared entry point, root-relative cwd, environment/resource policy, input RevisionPathRefs, result contract and required capability facts without containing SSH/Slurm clients, remote absolute paths, credentials or domain implementation objects. Domain Drivers MAY compile this spec but MUST NOT dispatch it directly.

#### Scenario: HMMER Driver compiles a search
- **WHEN** the HMMER Plugin accepts a formal search request
- **THEN** its selected Driver emits one closed workload requiring the exact HMMER software capability and result schema

#### Scenario: Workload embeds Slurm directives as authority
- **WHEN** a workload attempts to supply raw scheduler credentials, job IDs or Host/remote locators
- **THEN** closed-schema validation rejects it before Compute admission

### Requirement: Compute composes with Kernel ControlledOperation
Dispatch, observe, reconcile, cancel and result settlement MUST use the Kernel ControlledOperation identity and effect certainty. Compute MUST add workload/request/result facts without duplicating approval, dispatch certainty, retry or cancellation state.

#### Scenario: Provider acceptance is unknown
- **WHEN** transport fails after the exact workload may have reached its route provider
- **THEN** the shared operation remains dispatch_in_doubt, Compute observes by the same opaque identity and submits no replacement

#### Scenario: Cancellation response is lost
- **WHEN** cancellation may have been accepted but its response is lost
- **THEN** observation reconciles the same cancel intent and does not issue another cancellation or workload

### Requirement: Compute persists the dispatch occurrence before the external effect
Every Compute execution MUST durably persist a Store-owned dispatch state and exact occurrence identity before invoking the selected route. The state MUST distinguish `not_started`, `reconcile_required`, `dispatched` and `settled`, and MUST retain the latest content-bound dispatch receipt digest. Once the state is not `not_started`, `submit()` MUST NOT invoke `dispatch()` again. Reconciliation MUST accept the original request plus occurrence identity and MUST NOT require a provider handle.

#### Scenario: Dispatch response is lost before a handle is returned
- **WHEN** the provider may have accepted the exact request but dispatch returns `dispatch_in_doubt` with no provider handle
- **THEN** restart replays only `reconcile(request, occurrence_identity)`, preserves the same occurrence, and the route dispatch count remains one

#### Scenario: Dispatch raises an uncertain typed failure
- **WHEN** dispatch raises after the external request may have been accepted
- **THEN** Compute persists `reconcile_required` plus a diagnostic-bound receipt identity before propagating the failure, and a later Host epoch never redispatches the workload

### Requirement: Domain result validation precedes Compute terminal continuation
When a formal workload carries an exact subordinate Driver result-validator binding, Compute MUST persist the Driver identity, owning Plugin, compiled workload contract/digest and validator identity with the request. A terminal provider receipt MUST pass the generic Compute identity checks and the exact Driver-owned result validator before Compute stores it as terminal or registers the owner continuation.

#### Scenario: HMMER result bypasses its Driver validator
- **WHEN** a terminal HMMER receipt has a generic Compute identity but fails the exact HMMER result contract or claims `raw_shell=true`
- **THEN** Compute records a typed terminal-validation failure, stores no accepted terminal result and registers no owner continuation

#### Scenario: Restart observes a valid terminal result
- **WHEN** a restarted Host reconciles or observes a terminal result for a request with a persisted Driver validator binding
- **THEN** it invokes the same exact Driver validator before the durable result and continuation are committed

### Requirement: Compute providers and routes are capability-resolved
Compute MUST dispatch only through an exact route contributed by a compatible provider and present in the current Session capability binding. Local process, HPC and future providers MAY satisfy the same Compute capability contract; Compute MUST NOT import provider implementations or silently replace the Agent-selected route.

#### Scenario: HPC route satisfies a workload
- **WHEN** an Agent selects a bound HPC route whose inventory satisfies all workload requirements
- **THEN** Compute dispatches through that route with the exact inventory/driver/provider identities

#### Scenario: Selected route becomes stale
- **WHEN** route, inventory, authority or workspace identity drifts before dispatch
- **THEN** the operation remains no_effect and no local or alternate target is selected

### Requirement: Generic execution SDK is domain-free
`openzyme-execution-sdk` MUST expose only the controlled sandbox socket protocol, revision-bound request/result DTOs, opaque handles and structured errors. It MUST NOT include AOX calculations, reference sequences, motif/graph policy, HMMER/Vina semantics, Biopython or a domain-specific output contract.

#### Scenario: Install SDK in a generic image
- **WHEN** an arbitrary non-biological executor installs the SDK
- **THEN** it can communicate through the generic revision/workload protocol without installing a biological library

### Requirement: Runner wire contracts are narrow and independently deployable
`openzyme-execution-contracts` MUST contain the closed request/observation/cancel/result wire DTOs needed by `mcp-hpc-runner` and depend only on implementation-free contracts. The runner MUST NOT depend on `openzyme-domain`, Kernel repositories, Host services, Science or EnzymeDesign.

#### Scenario: Build the runner alone
- **WHEN** runner and execution-contract wheels are installed in a fresh environment
- **THEN** the service imports and validates its wire schema without the platform Domain/Kernel/Host

#### Scenario: Platform object crosses the wire
- **WHEN** a runner DTO exposes Core repository records, Host paths or scientific domain objects
- **THEN** wire-contract qualification rejects the build

### Requirement: Compute results are opaque bounded and non-terminal
A terminal compute result MUST bind the same request/operation/route, opaque provider handle, terminal receipt, result contract and bounded safe summary. The system MUST NOT require or fabricate expected outputs, infer scientific adoption, publish private files, complete a Task or expose raw scheduler IDs/logs in Core projection.

#### Scenario: Formal result settles
- **WHEN** exact observation yields a valid terminal provider receipt
- **THEN** Compute records its outcome and wakes the owning Agent without finishing the Task

#### Scenario: Result files must be shared
- **WHEN** output files exist in the owner workspace
- **THEN** the Agent explicitly inspects, commits/checkpoints and publishes them before any RevisionPathRef handoff or scientific adoption

### Requirement: Compute implementation and documentation align
Compute/Execution SDK, runner, tool/route manifests, Host mount, configuration and stable execution documents MUST describe the exact workload, route, effect certainty, owner and no-Host-path semantics implemented by source.

#### Scenario: Documentation prescribes direct runner access
- **WHEN** a current Agent/runtime document tells a Plugin or teammate to call runner, SSH or Slurm directly for formal work
- **THEN** source-to-document qualification fails
