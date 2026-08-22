# file-workspace-cutover-assurance Specification

## Purpose
TBD - created by archiving change close-file-workspace-cutover-verification-gaps. Update Purpose after archive.
## Requirements
### Requirement: Change completion markers follow current authoritative evidence
Every completion-sensitive task for the file-workspace predecessor set and `separate-openzyme-kernel-from-capability-extensions` MUST have a machine-readable mapping to current source, implementation, test/qualification, composition/wheel, migration and documentation evidence. A task contradicted by executable behavior, a deleted test, stale source-bound receipt, missing layer/profile, dependency leak, manifest drift, stale documentation or false claim MUST be restored to incomplete and linked to an exact repair task. Unrelated and still-proven completed predecessor tasks MUST remain complete.

#### Scenario: A checked task cites a deleted test
- **WHEN** the evidence-gap audit proves that a checked task names a test file or behavior that no longer exists
- **THEN** that task is unchecked, linked to the gap registry and remains incomplete until replacement behavior evidence passes

#### Scenario: A task remains valid
- **WHEN** current source and focused/full verification still prove a predecessor task exactly under its migrated owner
- **THEN** its completion marker is preserved and the split change does not reset it merely because another layer failed

#### Scenario: Implementation moved without documentation
- **WHEN** a package owner or public seam changed but its mapped main architecture, `docs/v3/`, README or deployment document remains stale
- **THEN** that implementation slice and final change remain incomplete even if its code tests pass

### Requirement: Qualification covers current behavior and forbidden outcomes
Cutover qualification MUST execute positive and negative behavior across the three exact Kernel-only, Standard and EnzymeDesign profiles. It MUST retain coverage for HPC dispatch/observe/cancel/replay/restart/response loss/tamper, publication certainty/reconciliation, Agent workspace recovery, cleanup residue, fresh/offline proof, scientific adoption/finalization/AOX bundle, Web UI state/view/controller and public diagnostic redaction. It MUST add Plugin discovery/activation/removal/collision/namespace/Session-pin, required/optional/degraded distinctions, capability cycles, target inventory/adoption, route/affordance staleness, local/remote Workspace Runtime, wheel dependency and source-document drift cases. Each scenario MUST assert both the allowed outcome and relevant forbidden fallback, duplicate effect, Task/scientific inference, identity substitution, ambient capability or secret disclosure.

#### Scenario: Focused tests are green but a required family is absent
- **WHEN** the selected suite passes but lacks one required layer, behavior, documentation or forbidden-outcome family
- **THEN** qualification remains incomplete and no architecture, release or archive receipt is issued

#### Scenario: Cancellation response is lost
- **WHEN** a test loses the cancellation response after backend invocation across the Compute Plugin seam
- **THEN** it proves exact-identity reconciliation, zero replacement cancellation/submission and preservation of the specific cause

#### Scenario: An extension registers ambient capability
- **WHEN** an installed but undeclared entry point adds a tool, route, worker, projection or migration
- **THEN** Standard/EnzymeDesign activation fails before partial registration and qualification records the forbidden key

### Requirement: Architecture qualification uses production composition and declared ports
Architecture qualification MUST use the real production path for each declared profile: Kernel application services with only fake infrastructure Ports, Plugin-free OpenZyme Standard Distribution, and the full EnzymeDesign Distribution. Its invariant registry MUST contain non-empty source-derived boundary relations, component kinds, package/wheel owners, documentation refs and external-Port declarations for every claimed family. Simplified fixtures, enum membership, operation-name scans, empty registry sections or one composition profile used to prove another profile's dependency claim MUST NOT support an architecture claim.

#### Scenario: Registry omits external ports
- **WHEN** a qualification profile claims external-effect coverage but its external-port set is empty or not source-bound
- **THEN** the qualification runner rejects the profile before producing an admission result

#### Scenario: Restart the production composition
- **WHEN** a required restart/fencing scenario runs in Standard or EnzymeDesign
- **THEN** the real repository/service/worker/manifest composition is restarted around declared fake external ports and the oracle proves persisted identity, Session bundle pin, fencing and no duplicate effect

#### Scenario: Kernel profile imports Standard
- **WHEN** the Kernel-only profile imports SQLite, Git implementation, Host, runtime implementation or an extension
- **THEN** the profile fails even if its behavioral assertions would otherwise pass

### Requirement: Scientific and UI acceptance uses direct current tests
Retained Science extension adoption/finalization services and EnzymeDesign AOX file-bundle finalization MUST have direct tests for valid identity, identity drift, cross-attempt rejection and atomic closure. The `@2` Core UI and every required extension renderer MUST have executable state, view and controller/client tests for file tree, revision, publication, extension sections, job, diagnostic, Session bundle and stale-contract behavior. Task text MUST cite only existing tests and MUST NOT infer component coverage from a build, manifest parse or unrelated client test.

#### Scenario: Scientific finalizer remains imported but untested
- **WHEN** a retained finalization service has no test that invokes its public extension behavior
- **THEN** the owning Science/EnzymeDesign task and overall assurance remain incomplete even if lower-level domain tests pass

#### Scenario: UI build passes without behavior tests
- **WHEN** the frontend compiles but Core shell or extension renderer state/view/controller behavior is absent or deleted
- **THEN** public-interface acceptance remains incomplete and the build is recorded only as build evidence

#### Scenario: Core UI depends on a Science field
- **WHEN** a Core reducer or view test proves that Task/runtime rendering reads a Science extension payload
- **THEN** the ownership boundary fails until the reducer consumes only Core facts

### Requirement: Final evidence is source-bound and generated in one closed order
Current acceptance MUST bind an exact clean commit, source-tree identity, OpenSpec artifacts, component/table/import owner manifests, built wheel identities, Adapter/Extension/declared-tool/route/projection/migration/schema/inventory/document digests, test/qualification plan, evidence outputs, deployment bootstrap/offline cutover proof and receipt-generation code. The required order is source and documentation freeze, built-wheel/catalog verification, all three qualification profiles plus mainline, quiescent migration/bootstrap verification, per-task evidence closure, then release receipt generation. Any later source, config, OpenSpec or required documentation change MUST invalidate the current receipt chain and require re-execution from freeze.

#### Scenario: Old receipt binds a parent commit
- **WHEN** a release or per-change receipt references a commit, wheel, composition or documentation digest other than the final current identity
- **THEN** it is marked superseded and cannot complete a task or authorize archive

#### Scenario: Source changes after a green run
- **WHEN** code, config, docs, tests or OpenSpec current artifacts change after qualification evidence is captured
- **THEN** the previous evidence remains historical but no longer proves current acceptance and all affected profiles/gates are rerun

#### Scenario: Documentation changes after the code freeze
- **WHEN** a required stable document is corrected after source-bound tests completed
- **THEN** the combined source/document identity changes and the mapped drift/qualification gates rerun before completion

### Requirement: Full mainline and strict OpenSpec are necessary but not individually sufficient
Before archive, the final clean source MUST pass strict validation for this change and all affected current specs, retired-surface/import audits, source-document traceability, built-wheel/dependency gates, Plugin catalog/removability gates, all required focused/negative suites, all three complete architecture qualification profiles and `./scripts/check-mainline.sh`. Each result MUST be tied to its actual selection, source, wheel and Distribution identity. A green subset, structural validation, successful artifact creation, telemetry failure after command success or mainline lacking required profile behavior MUST be described at its real scope.

#### Scenario: Strict validation passes
- **WHEN** all OpenSpec documents validate structurally but implementation, documentation or layered qualification has not passed
- **THEN** artifacts are apply-ready only and implementation/archive completion remain false

#### Scenario: Telemetry flush fails after command success
- **WHEN** OpenSpec returns a successful status/validation result and a later telemetry request fails
- **THEN** evidence records command success separately from the non-authoritative telemetry failure without hiding either event

#### Scenario: Mainline omits a wheel profile
- **WHEN** `check-mainline.sh` is green but no current evidence installs and inspects the Kernel or Standard wheel closure
- **THEN** mainline is recorded as passed at its scope while final split acceptance remains incomplete

### Requirement: Archive is an evidence consequence rather than an operator shortcut
The split change MUST remain active until every implementation and documentation task is complete, `@2` migration/activation evidence and all composition profiles are current, no unresolved owner/import/table/catalog/documentation gap remains, and archive sync order is proven. Other active changes MUST be verified and decided separately. Archive MUST preserve predecessor/history artifacts and MUST NOT silently sync, omit or reinterpret a delta contrary to its explicit archive decision.

#### Scenario: One implementation or documentation task remains open
- **WHEN** all package moves pass but one required migration, README, stable document, UI renderer or qualification task is incomplete
- **THEN** archive does not run and the OpenSpec artifact set is not presented as completed implementation

#### Scenario: Another active change is unrelated
- **WHEN** an active change lies outside this change's dependency/evidence map
- **THEN** archive leaves it active unless it independently passes its own verification and receives a separate archive decision

#### Scenario: Old compatibility authority remains
- **WHEN** a temporary re-export, `@1` mutation path or old package implementation remains after final qualification
- **THEN** archive is blocked until the second authority is deleted and current gates rerun
