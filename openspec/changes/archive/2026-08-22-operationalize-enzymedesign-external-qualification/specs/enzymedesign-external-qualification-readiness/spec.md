## ADDED Requirements

### Requirement: External qualification uses an exact indivisible unit
Every external qualification readiness entry MUST bind exactly one capability, operation, route, target or provider subject, source digest, build digest and configuration digest. It MUST additionally bind the owning component or Driver, contract digest, qualification-spec digest and any credential locator identity required by that operation. A result for one unit MUST NOT qualify another operation, route, subject or drifted digest.

#### Scenario: One smoke reports multiple unexecuted operations
- **WHEN** a backend executes one operation but reports readiness for another operation in the same capability
- **THEN** the verifier rejects the result and records no readiness for either mismatched unit

#### Scenario: Configuration changes after readiness
- **WHEN** the provider endpoint, target environment or bounded non-secret configuration has a digest different from the unit
- **THEN** the old evidence is inapplicable and the changed unit requires a new plan and result

### Requirement: Lifecycle claims remain distinct and non-transitive
The system MUST represent `selected`, `runtime_mounted`, `ready_non_live`, `qualified`, `cutover` and `live occurrence` as distinct evidence states. No earlier state MUST imply a later state, and a deterministic readiness backend MUST be unable to issue a `qualified`, `cutover` or live-occurrence receipt.

#### Scenario: Recording backend completes all fixtures
- **WHEN** every non-live readiness unit and negative fixture passes
- **THEN** the report claims only `ready_non_live` and explicitly records that no external effect or credential access occurred

#### Scenario: A mounted Adapter has no live receipt
- **WHEN** an exact Adapter runtime is mounted but no current real-subject qualification receipt exists
- **THEN** its lifecycle remains `runtime_mounted` or `ready_non_live` and is not advertised as qualified

### Requirement: Product profiles close required qualification units exactly
EnzymeDesign MUST define one required base profile and named optional profiles. A readiness plan MUST contain all and only the units in the base profile plus every explicitly enabled optional profile. An enabled optional profile MUST be complete; missing, duplicate, unexpected, colliding or unknown profile/unit identities MUST fail closed.

#### Scenario: Optional AlphaFold profile is disabled
- **WHEN** the plan request does not enable the AlphaFold profile
- **THEN** AlphaFold units are absent without weakening the required base profile

#### Scenario: Optional profile is enabled but incomplete
- **WHEN** one required unit or negative fixture of an enabled profile is missing
- **THEN** plan construction or verification fails with `qualification_profile_incomplete`

### Requirement: The product catalog covers every selected external boundary
The readiness catalog MUST enumerate the selected LLM, Tavily, Bio HTTP, Git/LFS, Podman, SSH and Slurm Adapter routes plus target-specific HMMER, Vina, fpocket, AlphaFold and preprocessing Driver operations. Each entry MUST name whether it belongs to base or an optional profile and MUST name its required positive and negative probes.

#### Scenario: Selected external Adapter has no catalog unit
- **WHEN** the Distribution selects an external-effect Adapter whose declared operation has no readiness unit
- **THEN** catalog closure fails before a readiness plan can be emitted

#### Scenario: Scientific Driver only proves importability
- **WHEN** a Driver has import/compile tests but no target-specific software smoke unit
- **THEN** it remains mounted-only and the corresponding enabled profile is not readiness-complete

### Requirement: Probe execution is controlled, bounded and reconcilable
External qualification MUST use a declared probe Port with exact dispatch and reconcile operations. A probe request MUST bind the unit and attempt identity, bounded input/schema, timeout and credential locator identity. A response-loss or unknown-effect outcome MUST reconcile the same attempt and MUST NOT redispatch, retry or select another route implicitly.

#### Scenario: Response is lost after terminal backend execution
- **WHEN** dispatch reports unknown effect certainty for an attempt
- **THEN** the coordinator calls reconcile for the same attempt and never creates a second occurrence

#### Scenario: Reconcile remains uncertain
- **WHEN** the backend cannot establish a terminal result for that attempt
- **THEN** the unit is `blocked_readiness` with explicit operator action and no fallback

### Requirement: Credentials are explicit locators with bounded scope
Plans and public evidence MUST contain only stable credential slot/locator identity and scope digest, never credential material. Credential resolution MUST require an exact authorized unit and MUST reject missing, expired or scope-mismatched locators. It MUST NOT inspect ambient environment variables, default profiles, adjacent accounts or anonymous access as fallback.

#### Scenario: Non-live readiness attempts credential resolution
- **WHEN** the readiness coordinator tries to obtain credential material
- **THEN** the rejecting resolver fails the run and records `credential_material_accessed = true` as a policy violation

#### Scenario: Live locator scope names another Provider
- **WHEN** a resolver is asked to use a locator whose scope does not bind the unit subject and operation
- **THEN** qualification is blocked before any provider request or mutation

### Requirement: Readiness receipts are digest-bound and independently verifiable
Each non-live readiness result MUST bind the canonical plan/unit digest, recording backend and fixture identity, observed operation, expected and observed schema digests, required negative-test set, timestamps, diagnostic identity, effect certainty and explicit external-effect, credential-access and fallback flags. An independent verifier MUST recompute all digests and require a one-to-one result for every planned unit.

#### Scenario: Receipt is copied to another target
- **WHEN** a receipt payload is reused with a different subject or route identity
- **THEN** digest verification fails and no readiness fact is emitted

#### Scenario: Negative fixture was not exercised
- **WHEN** all positive fixtures pass but a required timeout, auth, schema, response-loss or operation-mismatch fixture is absent
- **THEN** the plan report is invalid

### Requirement: Qualification failures are structured and secret-safe
Public readiness failures MUST include a stable error code, component, phase, plan/unit identity, effect certainty, mutation/fallback facts, retry/reconcile policy, operator action and diagnostic ID. Protected diagnostics MAY contain bounded cause chains, stdout/stderr, return code and request identity under the same diagnostic ID. Public payloads MUST reject secret material, credential values, private paths and unbounded tracebacks.

#### Scenario: Backend raises with a secret-bearing message
- **WHEN** an underlying backend exception contains configured secret material
- **THEN** the public failure is redacted and bounded while the protected diagnostic retains only policy-approved private context

### Requirement: Required CI is non-live and live execution is operator-gated
Ordinary pull-request and mainline CI MUST run the deterministic readiness suite with `OPENZYME_ALLOW_LIVE=0`, known credential variables absent, and guards rejecting network, SSH, scheduler, container and external process effects. Live markers MUST run only through an explicit manual operator workflow with separate profile opt-in, protected configuration and secrets; they MUST NOT run on pull request, push or schedule triggers.

#### Scenario: Pull request changes an Adapter
- **WHEN** ordinary CI evaluates the change
- **THEN** it runs contract, catalog, fixture, reconcile, secret-safety and non-live readiness verification without contacting the external system

#### Scenario: Live marker lacks explicit opt-in
- **WHEN** a live-marked test is selected without the manual workflow and required profile authorization
- **THEN** it fails closed or reports an explicit non-execution reason and cannot be counted as a live pass

### Requirement: Readiness hands off to later changes without performing them
A completed readiness change MUST emit only the canonical catalog/profile/plan schemas, non-live evidence and operator decision checklist needed by a later qualification change. It MUST NOT adopt target inventory, activate live runtime, create real qualification receipts, perform cutover or enable automatic fallback.

#### Scenario: All readiness CI passes
- **WHEN** this change reaches implementation completion
- **THEN** work pauses before creating or executing the real qualification change until the operator confirms its concrete decision points
