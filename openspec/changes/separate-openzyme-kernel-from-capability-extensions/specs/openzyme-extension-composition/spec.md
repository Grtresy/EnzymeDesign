## ADDED Requirements

### Requirement: Entry points locate implementations but never activate capabilities
Python entry points MUST only locate manifest providers for explicitly selected Adapters, Plugins and Drivers. A versioned Distribution manifest MUST be the sole activation source. An installed but unlisted implementation MUST have no tools, routes, workers, projections, migrations, providers, target probes or startup side effects.

#### Scenario: An unlisted Plugin is installed
- **WHEN** an environment contains a valid `openzyme.extensions` manifest-locator entry point that is absent from the active Distribution manifest
- **THEN** startup does not import its runtime registration path and no capability from it appears in any active catalog

#### Scenario: A required Plugin is missing
- **WHEN** a Distribution requires a Plugin whose exact entry point, package version or digest-bound manifest is absent
- **THEN** deployment activation fails before repositories, writers, workers, routes or external effects are enabled

#### Scenario: An optional Plugin is absent
- **WHEN** a Distribution lists a Plugin as optional and no matching implementation is installed
- **THEN** deployment activation may continue with that Plugin in `inactive` state, no contribution from it is registered, and the absence is represented explicitly rather than by a fallback

### Requirement: Manifests distinguish Adapter, Plugin, Driver and Distribution
Every manifest MUST use a closed, versioned schema and one explicit component kind. An Adapter MUST implement an existing Port without introducing product semantics; a Plugin MAY contribute namespaced semantics and tools; a Driver MUST remain subordinate to one Plugin contract and translate typed requests to a concrete mechanism; a Distribution MUST only select and bind exact components. A component MUST NOT claim more than one of these ownership roles through an ambiguous manifest.

#### Scenario: Adapter attempts to add a canonical entity
- **WHEN** an Adapter manifest declares a new top-level product entity or domain finish rule instead of implementing a declared Port
- **THEN** schema/ownership validation rejects the component before activation

#### Scenario: Driver is activated without its owning Plugin
- **WHEN** a Distribution selects a Driver but does not select the Plugin contract that owns the typed request and result semantics
- **THEN** dependency resolution rejects the composition and does not expose a provider-specific tool

### Requirement: Plugin manifests are closed and digest-bound
Each PluginManifest MUST declare Plugin ID/version, package/build identity, required Kernel and extension-SPI contracts, provided capability IDs, package-independent capability requirements, tool specs, required authority grants, approval policies, projections, routes, workers, finish validators, state/migration namespace, Driver slots, qualification specifications and non-secret configuration schema. The Host MUST canonicalize the manifest and verify its digest and every referenced catalog digest.

#### Scenario: Manifest bytes are tampered
- **WHEN** one manifest field or referenced tool schema differs from the bytes bound by the Distribution digest
- **THEN** activation fails with expected and observed identity and no partial registration occurs

#### Scenario: Unknown manifest field appears
- **WHEN** a manifest supplies an undeclared field or unsupported schema version
- **THEN** the closed-schema validator rejects it rather than ignoring the field

#### Scenario: Plugin imports a provider by package name
- **WHEN** a Plugin requirement names a concrete HPC, Slurm, SSH, Provider or other implementation package instead of a versioned capability contract
- **THEN** dependency qualification fails even if that package happens to be installed

### Requirement: Composition produces deterministic layered bundle identities
The composition loader MUST deterministically derive the Kernel contract/schema digest, Adapter bundle digest, Extension bundle digest, declared-tool catalog digest, route catalog digest, projection catalog digest, migration bundle digest, workspace-backend identity and total Distribution bundle digest from canonical ordered identities. Discovery, filesystem and import order MUST NOT change any digest.

#### Scenario: Entry-point order changes
- **WHEN** the same exact declared components are discovered in a different iteration order
- **THEN** every normalized catalog and layered bundle digest is identical

#### Scenario: One implementation version drifts
- **WHEN** an installed package version differs from the version selected by the Distribution while its component ID remains the same
- **THEN** the computed observation is rejected and the Host does not silently bind the newer implementation

#### Scenario: Target health changes
- **WHEN** a bound target's transient health changes but no manifest, tool contract, inventory generation or Session capability-binding revision changes
- **THEN** release-bundle digests remain stable while the turn affordance observation may change independently

### Requirement: Capability dependencies resolve as a closed acyclic graph
The activation resolver MUST match required capability IDs and version/operation constraints against declared providers without importing provider internals. It MUST reject missing required dependencies, incompatible versions, ambiguous single-valued providers and every dependency cycle. It MUST preserve all matching target-scoped routes when the contract permits multiple explicit routes.

#### Scenario: Plugin dependency cycle exists
- **WHEN** selected Plugins form a direct or transitive capability dependency cycle
- **THEN** activation fails with the bounded cycle path and registers none of the involved contributions

#### Scenario: Multiple HPC targets satisfy one requirement
- **WHEN** two qualified target-scoped routes satisfy a multi-route capability requirement
- **THEN** both receive distinct route identities and the resolver does not choose one implicitly

### Requirement: Registration catalogs reject every canonical collision
Host activation MUST reject duplicate capability provider IDs where uniqueness is required, canonical dotted tool names, normalized method/route pairs, projection contract IDs, worker IDs, finish-validator IDs, Driver IDs and migration namespaces. Registration MUST be all-or-nothing and MUST NOT use last-loaded, priority, alias or load-order fallback resolution.

#### Scenario: Two Plugins register one tool name
- **WHEN** two selected manifests provide the same canonical dotted tool name
- **THEN** startup fails with both Plugin identities and the conflicting key before either tool is callable

#### Scenario: Routes collide after normalization
- **WHEN** two route declarations differ textually but normalize to the same HTTP method and path
- **THEN** the route catalog rejects the bundle instead of selecting one handler

#### Scenario: Existing registry would overwrite a tool
- **WHEN** a contribution is registered under a canonical key already owned by another contribution
- **THEN** the registry raises a typed collision failure and preserves the pre-registration catalog unchanged

### Requirement: Activation state distinguishes absent, invalid and resource-degraded Plugins
An absent optional Plugin MUST be `inactive`. A present Plugin whose manifest, schema, digest, migration namespace, dependency graph or registration integrity is invalid MUST block activation even when marked optional. A structurally valid Plugin whose external resource qualification or route supply is currently unsatisfied MAY activate as `degraded`; its blocked tools MUST not enter effective tool catalogs.

#### Scenario: Optional Plugin has an invalid manifest
- **WHEN** an optional Plugin implementation is found but its manifest digest or schema is invalid
- **THEN** Host activation fails instead of treating it as absent or degraded

#### Scenario: Valid HMMER Plugin has no qualified route
- **WHEN** the HMMER Plugin contract is valid but no adopted target inventory satisfies its software and Compute-route requirements
- **THEN** the Plugin is `degraded`, its declared tools remain inspectable with typed blockers, and none is callable

### Requirement: Deployment activation and Session pin exact composition
A Distribution deployment MUST activate one verified composition epoch. Every new Session MUST atomically pin its Kernel contract/schema, Adapter bundle, Extension bundle, declared tool/route/projection/migration catalogs, workspace backend and initial SessionCapabilityBindingRevision. A Session MUST NOT mutate under a different pinned bundle or acquire a newly installed Plugin through hot replacement.

#### Scenario: Resume with a drifted bundle
- **WHEN** a Session pinned to one Extension bundle is restored under a Host with another incompatible bundle
- **THEN** messages, runtime drains, approvals, tool calls, workspace mutations, publication and external operations fail with a typed upgrade-required result before mutation

#### Scenario: Install an optional Plugin after Session creation
- **WHEN** an operator installs or activates an optional Plugin after a non-terminal Session was created
- **THEN** the existing Session does not acquire its tools, projections or state until an explicit offline-compatible Session upgrade creates a new pinned bundle

#### Scenario: Adopt a new target inventory
- **WHEN** an operator explicitly publishes and adopts a compatible TargetToolchainInventory generation for a Session
- **THEN** the Kernel creates a new immutable SessionCapabilityBindingRevision without changing the pinned Extension bundle

### Requirement: Extension state and migrations have exclusive namespaces
Every stateful Plugin MUST own one declared table/migration namespace and an independently digest-bound migration bundle. A table, index, trigger or migration step MUST have exactly one Kernel or Plugin owner; a Plugin MUST NOT read or write Kernel tables, another Plugin namespace, attached databases or undeclared schema objects.

#### Scenario: Adopt existing tables without renaming them
- **WHEN** offline cutover assigns an existing Science table to the Science Plugin
- **THEN** the table-owner manifest and Science migration bundle identify it uniquely, preserve its rows and constraints, and no Kernel migration continues to own it

#### Scenario: Plugin SQL targets a Kernel table
- **WHEN** a Plugin migration or runtime statement references a Kernel-owned table
- **THEN** the namespace/authorizer boundary rejects the statement and the enclosing transaction is rolled back

### Requirement: Atomic Plugin participation uses a restricted short Unit of Work
A Plugin that must update its state atomically with a Kernel command MUST use the declared ExtensionTransactionParticipant protocol and an immutable authorized command context. It MUST receive neither raw Kernel repositories nor an unrestricted database connection, and it MUST perform no LLM, provider, Git, process, SSH, scheduler or HPC call while the Unit of Work is open.

#### Scenario: Participant and Kernel mutation succeed
- **WHEN** Kernel authority is valid and the declared Plugin participant applies a namespace-local state transition
- **THEN** Kernel and Plugin mutations plus their durable outbox facts commit atomically in one bounded transaction

#### Scenario: Participant fails
- **WHEN** a participant raises, exceeds its statement/time budget or returns an invalid result
- **THEN** the whole Unit of Work rolls back, a structured participant failure is recorded outside the failed transaction, and the Kernel does not bypass or retry it implicitly

### Requirement: Plugin upgrade and removal are explicit offline operations
An activated Plugin MAY be upgraded, replaced or removed only after deployment quiescence and exact compatibility/migration verification. Removal MUST fail when a non-terminal Session pins it, it owns unsettled controlled operations or its state lacks a declared disposition; the Host MUST NOT hide the missing projection or fold its state into Kernel.

#### Scenario: Remove an unused Plugin
- **WHEN** no Session pins a Plugin, no owned state/effect remains and the offline removal verifier closes its manifest and migration disposition
- **THEN** a new composition epoch may omit it and the Kernel projection remains byte-semantically unchanged apart from release identity

#### Scenario: Remove a pinned Plugin
- **WHEN** a non-terminal Session or continuation pins the Plugin contract
- **THEN** activation of the reduced bundle is rejected until that Session is explicitly migrated or given a supported terminal/historical disposition

### Requirement: Composition failures are structured and secret-safe
Discovery, schema, dependency, collision, migration, activation, qualification-binding and participant failures MUST include a stable code, component/phase, component and Distribution identities, expected/observed safe facts, mutation/effect certainty, retry/reconcile policy, operator action and diagnostic ID. Public diagnostics MUST NOT expose secret configuration values, credentials, Host paths or private tracebacks.

#### Scenario: Provider configuration is invalid at activation
- **WHEN** a required non-secret configuration field or secret locator is absent
- **THEN** activation reports the exact component/configuration key and `mutation_applied = false` without printing a secret value or attempting a provider call

#### Scenario: Private cause exists
- **WHEN** manifest loading fails because an underlying import or filesystem operation raises
- **THEN** the public error remains bounded and the protected diagnostic preserves the chained cause and bounded context under the same diagnostic ID
