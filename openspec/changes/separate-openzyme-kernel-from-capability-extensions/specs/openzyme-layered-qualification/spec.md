## ADDED Requirements

### Requirement: Qualification has three closed composition profiles
The architecture invariant registry MUST define exact `kernel_fake_adapters@1`, `openzyme_standard_local_file_sqlite_git@1` and `enzymedesign_local_single_process_file_sqlite@1` profiles. Each profile MUST declare its semantic-owner graph, Distribution composition, permitted fake external Ports, required scenarios, dependency/content constraints and expected layered bundle digests; passing one profile MUST NOT imply another passed.

#### Scenario: Kernel and Standard pass but EnzymeDesign does not
- **WHEN** the first two exact profiles are satisfied and any required EnzymeDesign scenario is violated or unproven
- **THEN** the report records the narrower passes but overall change/cutover qualification remains false

#### Scenario: A profile has no exact selection
- **WHEN** registry or runner cannot close the required scenario and invariant set for a profile
- **THEN** that profile is `unproven` and no completion receipt is produced

### Requirement: Kernel qualification uses only fake infrastructure Ports
The Kernel profile MUST execute real Kernel application services and state machines using deterministic in-memory/fake repository, runtime, workspace and effect Ports. It MUST prove collaboration, AgentAuthorityLease/fence, ExtensionBundleRegistry, capability/affordance resolution, Workspace Runtime contracts, runtime coordination, Git-shaped publication/handoff semantics, controlled-operation and explicit Task finish without importing or starting SQLite, Git commands, Host, network, process/container or any concrete Plugin/Adapter.

#### Scenario: Kernel profile imports an adapter
- **WHEN** collection or runtime import tracing observes a Standard, Host, runtime implementation or extension module
- **THEN** the profile fails even when all functional assertions pass

#### Scenario: Kernel semantics pass in isolation
- **WHEN** all required positive and negative fake-port scenarios settle within budget
- **THEN** the report proves only Kernel semantic closure and makes no claim about Standard deployment mechanisms

### Requirement: Standard qualification uses the real Plugin-free Distribution
The Standard profile MUST activate the real generic Host, file-backed SQLite, local Git/LFS workspace, selected LLM/process Adapters, HTTP client and Kernel public projection with no semantic Plugin activated. Only declared LLM/provider/process external Ports MAY be controlled; fixture-only Host foundations or hidden Plugin registrations MUST NOT support the claim.

#### Scenario: Exercise Plugin-free production composition
- **WHEN** the Standard profile creates/restarts a Session and performs Task, Agent, Approval, runtime command, checkpoint, publication and handoff operations
- **THEN** canonical SQLite/Git/public projection facts preserve exact identity and no extension state or import is required

#### Scenario: Ambient extension self-registers
- **WHEN** an installed but unlisted extension adds a tool, route, worker, projection or migration during Standard qualification
- **THEN** activation/profile fails and records the ambient registration key

### Requirement: EnzymeDesign qualification uses the real product Distribution
The EnzymeDesign profile MUST activate the exact product Distribution manifest, real generic Host and selected Plugin/Driver/Adapter implementations, migrations and projections. It MAY replace only declared LLM/provider/runner/Chrome/process external Ports and MUST retain all production application seams and cross-owner identities.

#### Scenario: Run a cross-layer product scenario
- **WHEN** a required scenario crosses Agent authority, published revision, target inventory, route selection, Compute result handoff and Science validation
- **THEN** it uses the production manifest/services/repositories/workers/projections and proves both allowed outcome and forbidden Task/effect inference

#### Scenario: Simplified fixture omits an extension seam
- **WHEN** a test bypasses manifest activation, seeds success directly in a repository or replaces a non-external product service
- **THEN** it cannot satisfy the EnzymeDesign architecture claim

#### Scenario: Formal HMMER and Vina cross-layer slice uses seeded canonical prerequisites
- **WHEN** a non-live scenario uses the real mounted product graph and formal HMMER/Vina services but seeds canonical inventory, publication, path or Science evidence prerequisites or substitutes other product applications
- **THEN** it may prove only the named cross-layer slice and MUST NOT be described as the complete EnzymeDesign product lifecycle

### Requirement: Source, pyproject and wheel gates prove dependency direction
Qualification MUST inspect AST/import relations, every member/root `pyproject.toml`, lock metadata, built wheel `METADATA`, wheel contents and fresh-environment imports. It MUST enforce both the semantic-owner axis and Distribution composition rules plus forbidden dependency/vocabulary sets rather than relying on source directory names alone.

#### Scenario: Source imports are clean but wheel metadata leaks a dependency
- **WHEN** Kernel source has no direct forbidden import but its built wheel declares LangChain, FastAPI, Research, Science or another outer-layer dependency
- **THEN** the Kernel package/profile fails qualification

#### Scenario: Archive is importable
- **WHEN** archived code is reachable through an active package, test collection path or entry point
- **THEN** the active-source boundary fails until archive exposure is removed

### Requirement: Plugin removability and composition integrity are executable tests
Qualification MUST test Plugin-free Standard, required missing and optional absent Plugin, valid resource-degraded Plugin, invalid optional Plugin, exact addition/removal, version/digest drift, unlisted entry point, capability dependency cycles, every catalog collision family, namespace violation, Session pin mismatch and unsettled-state removal. Adapter, Extension, declared-tool, route, projection, migration, capability-binding and composition digests MUST be independently recomputed.

#### Scenario: Remove Research from a new bundle
- **WHEN** all Research state has a valid disposition and no Session pin or operation requires it
- **THEN** the reduced bundle starts, Core projection remains compatible and Research surfaces are absent

#### Scenario: Tool collision is introduced
- **WHEN** a fixture extension duplicates an active canonical tool name
- **THEN** Host activation fails before any partial route/worker/repository registration

#### Scenario: Optional Plugin has no qualified resource
- **WHEN** a valid optional Plugin activates but no adopted target inventory satisfies its route requirements
- **THEN** the Plugin is degraded, its tools are blocked in affordance resolution, and the profile proves no external probe or fallback occurs

### Requirement: Capability inventory route and affordance behavior are executable tests
Qualification MUST cover the four capability fact classes, immutable target inventory generation, operator-only adoption, declared/effective catalog separation, all affordance states, safe inspection, explicit route choice and dispatch-time stale rejection. It MUST prove that package installation is not authority, authority is not software availability, and transient health is not a release digest.

#### Scenario: Agent attempts inventory adoption
- **WHEN** an Agent requests an unbound newer target generation
- **THEN** the scenario proves `no_effect`, no binding mutation and no automatic route exposure

#### Scenario: One route exists but is omitted
- **WHEN** a formal HMMER request omits route ID despite one currently compatible route
- **THEN** the scenario proves missing-route rejection and no inferred target

### Requirement: Workspace Runtime behavior is qualified locally and remotely
Qualification MUST exercise structured root-confined filesystem operations, bounded argv execution, durable mutation/process/transfer operations, read-only observations, response-loss reconciliation, local/HPC tool separation, opaque remote workspace IDs and scheduler-credential exclusion. It MUST prove that raw workspace receipts do not publish files, settle formal Compute, adopt science or finish Tasks.

#### Scenario: Local exec requests an HPC credential
- **WHEN** the local `workspace.exec` path asks for SSH/HPC access
- **THEN** admission fails before credential issuance and no remote Adapter is called

#### Scenario: Remote command response is lost
- **WHEN** `hpc.workspace.exec` may have been accepted before transport loss
- **THEN** the same ControlledOperation remains `dispatch_in_doubt`, with zero retry and zero alternate route

### Requirement: Existing V3 invariants remain equivalent across the split
The migration qualification MUST preserve current authority, idempotency, lease/fence, effect certainty, restart/reconciliation, boundedness, secret redaction, immutable revision/path handoff and separation of runtime outcome, publication, report, scientific closure and Task terminal. Package movement or extension receipt MUST NOT weaken any forbidden outcome.

#### Scenario: Extension outcome is terminal
- **WHEN** Research, Reporting, Science, Compute or HPC records its own valid terminal outcome
- **THEN** qualification proves that Task status changes only after a separate authorized explicit `task.finish`

#### Scenario: Lost response occurs across the new package seam
- **WHEN** publication, provider or runner response is lost at an adapter/extension boundary
- **THEN** exact identity/effect reconciliation and no-replacement behavior match the pre-split invariant

### Requirement: Implementation-documentation traceability is a release gate
The registry MUST bind each architecture owner and public seam to current source/config/manifest/schema plus `docs/OpenZyme架构设计.md`, relevant `docs/v3/` files and affected package/app/operator documentation. Qualification MUST detect contradictory owners, stale imports/commands/paths, obsolete public contracts and undocumented fallbacks; keyword presence alone MUST NOT satisfy traceability.

#### Scenario: Documentation contradicts source ownership
- **WHEN** source assigns ScientificAttempt to `openzyme-science` but a current stable document assigns it to Kernel
- **THEN** the owning implementation slice and final layered qualification fail with both source and document references

#### Scenario: Current seam is coherently documented
- **WHEN** source, tests, manifest, schema, README and stable docs describe the same identity, owner, lifecycle, persistence, compatibility, error and forbidden-fallback semantics
- **THEN** the registry records that seam as documentation-aligned for the exact source identity

### Requirement: Qualification evidence is source-bound, non-live and non-authoritative for product state
Every profile report MUST bind exact clean source, OpenSpec artifacts, profile registry, built wheels, Distribution/Adapter/Extension/catalog/schema/inventory/doc digests, selected tests, observations and budgets. No required scenario MAY skip, xfail, call a real Provider/HPC/Chrome/MICU endpoint or mutate a product Session as qualification authority; the report MUST NOT itself authorize a live campaign.

#### Scenario: OpenSpec telemetry fails after validation succeeds
- **WHEN** a local OpenSpec command exits successfully and a later telemetry flush fails
- **THEN** evidence records structural success and non-authoritative telemetry failure separately

#### Scenario: Real external call is attempted
- **WHEN** a qualification process observes an undeclared socket, SSH, scheduler, browser, provider or container effect
- **THEN** the profile fails, preserves the bounded diagnostic and cannot substitute a live success result

### Requirement: Completion requires implementation and documentation, not artifacts alone
OpenSpec proposal/design/spec/tasks completion MUST establish an implementation plan but MUST NOT be represented as the architectural split being implemented. Change completion and archive MUST require current code/config/migrations/tests, synchronized documentation, all three profiles, strict OpenSpec and full mainline evidence on one source identity.

#### Scenario: All OpenSpec artifacts validate before implementation
- **WHEN** proposal, design, specs and tasks pass strict structural validation but implementation tasks remain unchecked
- **THEN** the change is apply-ready only and neither implementation nor archive acceptance is claimed

#### Scenario: Code passes but docs lag
- **WHEN** executable tests pass while any required current document is stale or contradictory
- **THEN** completion remains false until code and documentation are aligned and requalified together
