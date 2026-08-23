## ADDED Requirements

### Requirement: Identity discovery is source-bound and effect-free
The qualification system MUST discover only allowlisted, credential-free Provider and target identity fields from named source observations. Discovery MUST NOT resolve credential material, contact a network service, start a container, open SSH, call a scheduler or execute scientific software, and every observation MUST be classified as `resolved`, `partial`, `missing`, `unsafe` or `drifted` without implying qualification.

#### Scenario: Safe configuration contains a secret canary
- **WHEN** discovery receives an allowlisted endpoint field beside a credential-bearing canary field
- **THEN** the report contains the endpoint and source digest but neither reads nor serializes the canary

#### Scenario: A target display name is available without inventory closure
- **WHEN** discovery observes an SSH host and partition but no structured inventory generation or native proofs
- **THEN** the target identity is `partial` and no real-subject digest is issued

### Requirement: Missing identity produces a bounded operator decision packet
Every partial, missing, unsafe or drifted identity required by an enabled profile MUST produce an `ExternalIdentityGap` bound to affected exact units and source digests. The gap MUST list mutually exclusive resolution candidates, their prerequisites, effects, credentials, cost and security implications, identify one recommendation, and MUST remain unresolved until an explicit operator decision binds one candidate.

#### Scenario: Git service subject is missing
- **WHEN** Git and Git LFS binaries exist but no dedicated qualification repository and LFS endpoint are configured
- **THEN** the packet recommends a local isolated qualification repository without hosted sync, offers keeping the affected profile blocked as an alternative, and the plan builder selects neither automatically

#### Scenario: Operator decision names an unknown candidate
- **WHEN** a decision references a candidate outside the source-bound gap packet
- **THEN** the verifier rejects the decision and preserves `blocked_identity`

### Requirement: Identity preparation is independently planned and authorized
An operator decision MUST select a candidate without claiming that the subject now exists. When the selected candidate requires account/locator provisioning, local repository creation, image build/pull, safe target-profile mutation or remote inventory observation, the system MUST create an `ExternalIdentityPreparationPlan` bound to the exact source, discovery report, gap and decision digests, batch, actions, credential locators, generous hard budgets, cleanup and protected storage. The plan MUST set `live_effect_authorized=false` and MUST NOT issue a real-subject identity or qualification evidence.

Every preparation effect MUST require a distinct durable one-shot `ExternalIdentityPreparationOccurrenceAuthorization` binding the exact preparation-plan digest, batch and operator. The authorization MUST NOT expire by wall-clock passage; it remains usable only to start or resume that exact occurrence, and a terminal stored result MUST be restored without redispatch. Source, plan, batch or operator drift MUST invalidate it, and an exact explicit revocation MUST block it before credential resolution or effect. Preparation completion MUST be followed by a new effect-free identity observation and a rebuilt qualification dry plan; preparation authority MUST NOT authorize qualification probes.

#### Scenario: Local Git candidate is selected
- **WHEN** the operator selects a local isolated Git/LFS repository but has not authorized its creation
- **THEN** the preparation plan identifies the local-only creation and cleanup actions, the qualification plan remains `blocked_identity`, and no repository is created

#### Scenario: Preparation plan is authorized and completes
- **WHEN** an exact preparation occurrence produces the required non-secret subject fields
- **THEN** discovery is rerun and the qualification dry plan is rebuilt without promoting preparation observations to `qualified`

#### Scenario: Durable preparation authority is resumed after wall-clock passage
- **WHEN** the exact preparation occurrence is resumed with the same source-bound plan, batch, operator and authorization after any elapsed wall-clock time
- **THEN** completed actions are restored from protected evidence without redispatch and only incomplete exact actions may continue

#### Scenario: Preparation authority is explicitly revoked
- **WHEN** exact revocation evidence binds the preparation authorization and operator before the occurrence is terminal
- **THEN** execution fails before credential resolution or external effect and performs no fallback

#### Scenario: Preparation authorization is offered to a qualification backend
- **WHEN** identity preparation authority exists but no exact qualification occurrence authorization exists
- **THEN** the qualification backend remains blocked before credential resolution and effect

#### Scenario: Safe preparation results are rediscovered
- **WHEN** every exact Batch 1 preparation action has one terminal safe result bound to its plan, authorization, owner and input digest
- **THEN** the results are persisted without credential material, projected through a new effect-free discovery snapshot and cannot by themselves create qualification evidence

#### Scenario: Real locator rebinding changes unit identity
- **WHEN** post-preparation Batch 1 replaces non-live locator placeholders with the exact LLM, Tavily and HPC locators and removes the credential placeholder from local-only Git/LFS
- **THEN** the qualification catalog and unit digests are rebuilt before constructing the real-subject dry plan

### Requirement: Real subject identity is an exact typed closure
A Provider subject MUST bind provider ID, credential-free endpoint, account or project locator digest, API or contract variant and bounded configuration digest. A target subject MUST bind target and deployment IDs, host or runtime identity, environment, image or inventory digest, route mechanism and relevant policy digest. Logical catalog IDs and readiness unit digests MUST NOT substitute for the resulting real-subject digest.

Software/image/inventory/version facts MAY participate in the subject closure, but a positive or negative operation smoke receipt MUST NOT be required to create the dry plan that schedules that same operation. Smoke receipts are qualification evidence, not subject identity.

#### Scenario: Provider account changes under the same logical ID
- **WHEN** the account locator digest changes while `provider.llm.primary` remains the catalog ID
- **THEN** the prior subject, dry plan and qualification evidence are inapplicable

### Requirement: The dry plan closes exact batch authority before credentials or effects
An `ExternalQualificationDryPlan` MUST bind source identity, readiness catalog and plan digests, batch and exact unit set, resolved real subjects, credential locators without material, probe and fault sequence, retry policy, effect allowlist, budget, cleanup, TTL, storage policy and `live_effect_authorized=false`. An independent verifier MUST reject incomplete units, unresolved identities, secret-bearing fields, fallback, unbounded effects or evidence that any planned effect already occurred.

#### Scenario: Dry plan has one unresolved subject
- **WHEN** an enabled unit lacks a complete real-subject identity or accepted operator decision
- **THEN** the plan reports that unit as blocked and cannot become authorizable

#### Scenario: Dry plan attempts to inherit runtime retry
- **WHEN** an LLM or external-effect occurrence declares a retry count greater than zero
- **THEN** verification fails instead of inheriting the application runtime default

### Requirement: Live occurrence authorization is separate and pre-effect
Real qualification dispatch MUST require a durable one-shot `ExternalQualificationOccurrenceAuthorization` binding the exact dry-plan digest, batch and operator identity. The authorization MUST NOT expire by wall-clock passage; it remains usable only to start or resume that exact occurrence, and every terminal stored unit result MUST be restored without redispatch. Source, plan, batch or operator drift MUST invalidate it, and exact private revocation evidence MUST block it before credential resolution, budget reservation, owner bridge construction or external effect. A plan approval, environment flag, preparation authority or previous occurrence MUST NOT substitute.

#### Scenario: Plan-only workflow reaches the backend factory
- **WHEN** the dry plan is valid but no occurrence authorization is supplied
- **THEN** construction stops before credentials and records zero external effects

#### Scenario: Authorization binds another plan revision
- **WHEN** source, identity, unit, budget or policy changes after authorization
- **THEN** the authorization is rejected and a new dry plan requires approval

#### Scenario: Durable qualification authority is resumed after wall-clock passage
- **WHEN** the exact qualification occurrence is resumed with the same source-bound plan, batch, operator and authorization after any elapsed wall-clock time
- **THEN** completed units are restored from protected evidence without redispatch and only incomplete exact units may continue

#### Scenario: Qualification authority is explicitly revoked
- **WHEN** exact private revocation evidence binds the qualification authorization and operator before the occurrence is terminal
- **THEN** execution fails before credential resolution, budget reservation or external effect and performs no fallback

### Requirement: Budgets are generous circuit breakers at batch and occurrence scope
Each paid or resource-bearing occurrence MUST declare a warning threshold and a higher hard limit, and each batch MUST declare an aggregate warning threshold and hard limit. Crossing a warning threshold MUST produce a diagnostic without weakening or rerouting the probe. Capacity MUST be reserved before dispatch and settled after terminal observation or reconciliation; only insufficient hard-limit capacity MAY produce `blocked_budget`, and the system MUST NOT reduce the required test or choose a cheaper Provider, target or route as fallback.

#### Scenario: LLM cost crosses its warning threshold
- **WHEN** a bounded LLM occurrence remains below its authorized hard limit but exceeds its warning threshold
- **THEN** execution may continue unchanged and the ledger records a budget warning

#### Scenario: Batch hard limit cannot reserve the next occurrence
- **WHEN** the next exact probe would exceed the authorized batch hard limit
- **THEN** dispatch is blocked before credentials or effect and no smaller substitute probe is created

### Requirement: Effects, cleanup and controlled faults are exact
Every mutating probe MUST use an isolated qualification resource, bind a cleanup action and deadline, and record residual-state observation. Fault injection MUST occur only at declared Adapter control points, preserve same-attempt identity for response-loss reconciliation, and MUST NOT use shared network chaos, quota exhaustion, automatic retry, alternate credentials, Providers, targets or routes.

#### Scenario: Slurm acceptance response is lost
- **WHEN** a controlled interceptor drops the response after exact job acceptance
- **THEN** the coordinator reconciles the same submit attempt and never submits a replacement job

#### Scenario: Cleanup fails after a successful mutation
- **WHEN** a qualification resource cannot be removed by its cleanup deadline
- **THEN** the probe certainty is preserved and an independent cleanup failure with operator action is recorded

### Requirement: Real evidence is terminal, protected and qualification-only
Successful qualification evidence MUST bind the real backend and subject, exact unit and attempt, terminal result validation, required negative-test closure, authorization digest, budget settlement, cleanup observation, issued and valid-until timestamps and protected diagnostic identity. Canonical safe receipts MUST be stored in a protected SQLite ledger and MAY be exported as secret-safe JSON; credential material and private diagnostics MUST remain outside public artifacts. Such evidence establishes only `qualified` for its exact unit and MUST NOT adopt a resource, cut over a deployment or authorize later live occurrences.

#### Scenario: Positive probe passes without required negative closure
- **WHEN** the real operation succeeds but its declared negative test is missing or blocked
- **THEN** no qualified receipt is issued

#### Scenario: Qualified receipt is offered as cutover proof
- **WHEN** deployment admission receives only a current real-subject qualification receipt
- **THEN** it rejects cutover until a distinct cutover receipt is supplied

### Requirement: Live qualification is manual and batch-isolated
Ordinary CI MUST run discovery fixtures, gap and decision validation, dry-plan verification, plan-only backend guards and receipt tamper tests with `OPENZYME_ALLOW_LIVE=0`. Real qualification MUST run only in a protected manual workflow after exact occurrence authorization, and Batch 1 and AlphaFold Batch 2 MUST be triggered, budgeted and adjudicated independently.

#### Scenario: Pull request changes a live Adapter
- **WHEN** ordinary CI evaluates the change
- **THEN** it performs no credential lookup or external effect and cannot emit a real-subject receipt
