## ADDED Requirements

### Requirement: Change completion markers follow current authoritative evidence
Every one of the fourteen target changes MUST have a machine-readable mapping from each completion-sensitive task to its current evidence, source identity and verification result. A task contradicted by executable behavior, a deleted test, stale source-bound receipt, missing coverage or false documentation MUST be restored to incomplete and linked to an exact repair task. Unrelated and still-proven completed tasks MUST remain complete.

#### Scenario: A checked task cites a deleted test
- **WHEN** the evidence-gap audit proves that a checked task names a test file or behavior that no longer exists
- **THEN** that task is unchecked, linked to the gap registry and remains incomplete until replacement behavior evidence passes

#### Scenario: A task remains valid
- **WHEN** current source and focused/full verification still prove a task exactly
- **THEN** its completion marker is preserved and the closure change does not reset it merely because another task failed

### Requirement: Qualification covers current behavior and forbidden outcomes
The cutover qualification MUST execute positive and negative behavior for HPC dispatch/observe/cancel/replay/restart/response loss/tamper, publication certainty/reconciliation, agent workspace recovery classification, cleanup residue, fresh/offline proof, scientific adoption/finalization/AOX bundle, Web UI state/view/controller and public diagnostic redaction. Each scenario MUST assert both the allowed outcome and relevant forbidden fallback, duplicate effect, task/scientific inference, identity substitution or secret disclosure.

#### Scenario: Focused tests are green but a required family is absent
- **WHEN** the selected suite passes but lacks one required behavior or forbidden-outcome family
- **THEN** qualification remains incomplete and no architecture, release or archive receipt is issued

#### Scenario: Cancellation response is lost
- **WHEN** a test loses the cancellation response after backend invocation
- **THEN** it proves exact-identity reconciliation, zero replacement cancellation/submission and preservation of the specific cause

### Requirement: Architecture qualification uses production composition and declared ports
Architecture qualification MUST load the real production composition outside explicitly declared external ports. Its invariant registry MUST contain non-empty, source-derived boundary relations and external-port declarations for every claimed cross-layer family, and each entry MUST bind a production owner, adapter, scenario/test identity and forbidden outcome. Simplified fixtures, enum membership, operation-name scans or empty registry sections MUST NOT support an architecture claim.

#### Scenario: Registry omits external ports
- **WHEN** a qualification profile claims external-effect coverage but its external-port set is empty or not source-bound
- **THEN** the qualification runner rejects the profile before producing an admission result

#### Scenario: Restart the production composition
- **WHEN** a required restart/fencing scenario runs
- **THEN** the real repository/service/worker composition is restarted around declared fake external ports and the oracle proves persisted identity, fencing and no duplicate effect

### Requirement: Scientific and UI acceptance uses direct current tests
Retained scientific adoption/finalization services and AOX file-bundle finalization MUST have direct tests for valid identity, identity drift, cross-attempt rejection and atomic closure. The current Web UI MUST have executable state, view and controller/client tests for file tree, revision, publication, job, diagnostic and stale-contract behavior. Task text MUST cite only existing tests and MUST NOT infer component coverage from a build or unrelated client test.

#### Scenario: Scientific finalizer remains imported but untested
- **WHEN** a retained finalization service has no test that invokes its public behavior
- **THEN** the owning cutover task and overall assurance remain incomplete even if lower-level domain tests pass

#### Scenario: UI build passes without behavior tests
- **WHEN** the frontend compiles but state/view/controller behavior is absent or deleted
- **THEN** public-interface acceptance remains incomplete and the build is recorded only as build evidence

### Requirement: Final evidence is source-bound and generated in one closed order
Current acceptance MUST bind an exact clean commit, source-tree identity, OpenSpec artifact digests, test/qualification plan, evidence outputs, deployment bootstrap/reset proof and receipt-generation code. The required order is source freeze, full mainline and qualification, device reset/bootstrap verification, per-change evidence closure, then release receipt generation. Any later source change MUST invalidate the current receipt chain and require re-execution from source freeze.

#### Scenario: Old receipt binds a parent commit
- **WHEN** a release or per-change receipt references a commit or source digest other than the final current source identity
- **THEN** it is marked superseded and cannot complete a task or authorize archive

#### Scenario: Source changes after a green run
- **WHEN** code, docs, tests or OpenSpec current artifacts change after mainline evidence is captured
- **THEN** the previous evidence remains historical but no longer proves current acceptance and the authoritative gate is rerun

### Requirement: Full mainline and strict OpenSpec are necessary but not individually sufficient
Before archive, the final clean source MUST pass `openspec validate --strict`, the retired-surface audit, all required focused/negative suites, the complete current architecture qualification profile and `./scripts/check-mainline.sh`. Each command result MUST be tied to its actual selection and source identity. A green subset, structural validation, telemetry failure after a successful command, or mainline run lacking the required behavior MUST be described at its real scope.

#### Scenario: Strict validation passes
- **WHEN** all OpenSpec documents validate structurally but implementation tests have not passed
- **THEN** artifacts can be considered structurally valid but implementation and archive completion remain false

#### Scenario: Telemetry flush fails after command success
- **WHEN** OpenSpec returns a successful status/validation result and a later telemetry request fails
- **THEN** evidence records the command success separately from the detailed non-authoritative telemetry failure without hiding either event

### Requirement: Archive is an evidence consequence rather than an operator shortcut
The fourteen target changes and this closure change MUST remain active until every mapped task is complete, final evidence and device reset are current, no unresolved gap remains, and archive sync order is proven. Other active changes MUST be verified and decided separately. Bulk archive MUST preserve historical artifacts and MUST NOT silently sync or omit a delta contrary to its explicit archive decision.

#### Scenario: One target change still has an open task
- **WHEN** thirteen changes are complete but one mapped task or proof remains incomplete
- **THEN** the coordinated archive does not run and no partial archive is presented as full cutover closure

#### Scenario: Another active change is unrelated
- **WHEN** an active change lies outside the fourteen-target dependency map
- **THEN** bulk archive leaves it active unless it independently passes its own verification and receives a separate archive decision
