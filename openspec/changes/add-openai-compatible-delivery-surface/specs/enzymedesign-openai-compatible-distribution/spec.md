## ADDED Requirements

### Requirement: EnzymeDesign OpenAI Compatible is a distinct explicit Distribution
`enzymedesign-openai-compatible` MUST be a versioned Distribution with component ID `enzymedesign.openai-compatible`. It MUST select one exact OpenZyme Kernel, the EnzymeDesign-compatible Adapter profile, the required and optional EnzymeDesign/general Plugins, subordinate Drivers, native Host/client/CLI/Web UI delivery surfaces, and `openzyme.openai-compatible.api`. It MUST NOT redefine business state, become a semantic layer, rename OpenZyme Standard, or implicitly convert every EnzymeDesign installation into a public compatibility service.

#### Scenario: Activate the compatible product composition
- **WHEN** the exact compatible manifest, selected component packages, surface contract, schema proof, and installed-wheel proof all validate
- **THEN** one new deployment epoch selects the compatible Distribution and only then permits its declared surfaces to start

#### Scenario: Install ordinary EnzymeDesign without the compatibility Distribution
- **WHEN** the base EnzymeDesign Distribution is installed or activated without `enzymedesign-openai-compatible`
- **THEN** no `/v1` compatibility listener, public credential, Session mapper, or compatibility runtime orchestration becomes active

### Requirement: The derived composition directly closes the EnzymeDesign component set
The compatible Distribution manifest MUST directly enumerate exact Kernel, Adapter, Plugin, Driver, and delivery-surface identities and digests. Its non-compatibility Kernel/Adapter/Plugin/Driver selection MUST equal the reviewed same-version EnzymeDesign product composition unless a separately specified product change intentionally differs. It MUST NOT use runtime inheritance, `extends`, import order, environment credentials, installed entry points, or `openzyme-standard` as a semantic dependency to complete the composition. Any base-selection drift MUST fail qualification and require an explicit manifest/version/digest update.

#### Scenario: Base EnzymeDesign adds a required Plugin
- **WHEN** the reviewed EnzymeDesign composition changes but the compatible manifest retains the old non-surface component set
- **THEN** composition qualification fails instead of silently activating a reduced or ambient Plugin set

#### Scenario: An unlisted compatible surface package is installed
- **WHEN** `openzyme-openai-compatible-api` is present in the environment but absent from the active Distribution manifest
- **THEN** no compatible route, listener, credential validation, or background observation starts

### Requirement: The compatibility API is selected as a delivery surface, not an Adapter or Plugin
The Distribution MUST bind `openzyme.openai-compatible.api` under `delivery_surfaces` with an exact contract digest. The app MUST use the repository's application-surface source classification and MUST NOT provide a Kernel Port Adapter manifest, occupy an Adapter slot, contribute Agent tools/state/workers/projections, register a Driver, or alter the Session capability bundle. Its removal MUST leave Kernel and Plugin canonical semantics unchanged apart from release/composition identity.

#### Scenario: Composition places the API in an Adapter slot
- **WHEN** a candidate manifest selects the compatibility API under `adapters` or as a Plugin/Driver
- **THEN** source-bound composition qualification rejects the Distribution before activation

#### Scenario: Remove only the compatibility surface in a successor epoch
- **WHEN** the deployment is quiescent and a reviewed successor composition omits the compatibility API while retaining the same semantic components
- **THEN** compatible ingress disappears and existing canonical Sessions remain governed by normal OpenZyme lifecycle rules

### Requirement: Distribution packaging has a closed direct installation boundary
The repository MUST provide `distributions/enzymedesign-openai-compatible/openzyme-composition.toml` and a buildable `packages/enzymedesign-openai-compatible-distribution` wheel whose project name is `enzymedesign-openai-compatible`. The wheel and deployment artifact closure MUST contain the exact selected Python components, Host/client/CLI assets, Web UI build identity, compatibility API wheel, and composition manifest required by the release. It MUST NOT acquire components through ambient extras, developer dependencies, editable source paths, legacy mixed packages, or a Distribution-to-Distribution semantic dependency. The packaged manifest MUST be byte/digest equivalent to the repository manifest.

#### Scenario: Build and inspect the Distribution wheel
- **WHEN** the compatible Distribution and all selected component wheels/assets are built in an isolated environment
- **THEN** metadata, packaged resources, component inventory, direct dependency closure, and manifest digests match the reviewed composition exactly

#### Scenario: A legacy implementation leaks into the wheel closure
- **WHEN** wheel or import inspection finds a forbidden legacy mixed implementation, Host internal shortcut, undeclared Provider, or optional component outside the manifest
- **THEN** qualification fails even if the `/v1` smoke test returns a syntactically valid response

### Requirement: Public and private process topology is explicit and single-instance
The supported first-release deployment MUST run the compatibility API as one independently supervised process, expose only its public `/v1` listener through the competition-facing ingress, and reach the canonical Host `/v3` endpoint only over a configured private network path. Host `/v3`, Web UI, CLI/operator credentials, control store, Provider credentials, runner, SSH, Slurm, and private diagnostics MUST NOT be exposed through the compatibility listener. More than one active compatibility instance for the same tenant/project/session namespace MUST make the deployment unqualified.

#### Scenario: Start the declared topology
- **WHEN** one compatible sidecar and one compatible private Host pass startup verification for the same Distribution release
- **THEN** public traffic reaches only `/v1`, internal traffic uses the private Host credential, and native operator surfaces remain separately controlled

#### Scenario: Two sidecars share one mapping namespace
- **WHEN** deployment inventory observes two active compatibility processes for the same tenant, project, and HMAC namespace
- **THEN** readiness/qualification fails because the first release has no distributed per-Session admission lease

### Requirement: Configuration fixes one tenant and one project with separated secrets
The compatible Distribution's runtime configuration MUST bind exactly one non-secret tenant ID, one fixed existing project ID, one model label, one private Host base URL, one set of hard runtime/resource bounds, and three independent secret identities for public Bearer authentication, private Host authorization, and HMAC Session mapping. The private Host principal MUST be project-scoped, non-admin, and limited to the user/operator permissions required for Session creation, message admission, exact inspection, and explicit runtime-command admission/observation. Request bodies and headers MUST NOT override tenant, project, Host principal, runtime bounds, route, Provider, Plugin, target, or approval policy.

#### Scenario: External caller attempts to select a project
- **WHEN** a compatibility request includes an unknown project, route, Provider, or runtime-bound field
- **THEN** the request fails as unsupported before any fixed deployment selection changes

#### Scenario: Public and private tokens are equal
- **WHEN** startup configuration resolves the public Bearer and private Host credential to the same secret identity or digest
- **THEN** startup fails before either listener or Host mutation path becomes ready

#### Scenario: Host principal has global admin scope
- **WHEN** the configured private principal has admin authority or project wildcard access instead of the fixed project scope
- **THEN** deployment qualification rejects the credential policy rather than accepting broader authority for convenience

### Requirement: Startup gates every surface behind exact composition and contract proof
The Distribution MUST follow the existing fail-closed startup sequence: parse and verify the exact composition, selected locators/components, catalogs, schema, installed wheels/assets, release identity, public Host/client contract, fixed project access, and compatibility surface contract before enabling writers, runtime dispatch, or the public listener. The compatibility process MUST become ready only after the canonical Host has an active matching epoch. Package installation, a syntactically active manifest, successful import, or a standalone `/v1` unit test MUST NOT count as deployment activation.

#### Scenario: Surface contract digest drifts
- **WHEN** the installed compatibility API contract digest differs from the value selected by the Distribution
- **THEN** activation fails before `/v1/models` advertises a model or `/v1/chat/completions` accepts a turn

#### Scenario: Host is reachable but pinned to another release
- **WHEN** the private Host answers health/inspection but its exact release or public-contract identity differs from the compatible Distribution
- **THEN** the compatibility surface remains not ready and performs no fallback to a legacy Host contract

### Requirement: Native surfaces retain all approval and operator authority
The compatible Distribution MUST include or explicitly bind the native Web UI and CLI/operator surfaces needed to inspect Sessions, pending approvals, runtime commands, failures, and continuation state. Only those authenticated native operations may resolve an Approval, grant scientific authorization, or explicitly advance a continuation. The compatibility surface MUST have no chat-to-approval route and MUST NOT hide the underlying Session from authorized operators.

#### Scenario: A compatibility turn waits for approval
- **WHEN** the bounded runtime command creates a pending Approval
- **THEN** an authorized operator can inspect and resolve it through the native surface while the public chat endpoint reports approval required without resolving it

#### Scenario: Compatibility surface is removed
- **WHEN** the public sidecar is stopped for rollback while the canonical Host and native surfaces remain active
- **THEN** operators retain access to the created Sessions, approvals, commands, tasks, and failure evidence

### Requirement: Surface-local state is non-canonical and disposable
The compatibility process MUST keep only bounded in-process locks, transport caches, and safe diagnostics; deterministic HMAC mapping and Host idempotency identities MUST allow restart observation without a second business-state store. The Host control store and selected Workspace Adapter MUST remain the only canonical persistence owners. Stopping or reinstalling the surface MUST NOT delete, rewrite, finish, or migrate Sessions, Tasks, Approvals, runtime commands, publications, scientific state, reports, or workspace revisions. HMAC-key change MUST be treated as an explicit namespace/lifecycle change and MUST NOT trigger multi-key guessing or silent remapping.

#### Scenario: Sidecar restarts during a running command
- **WHEN** the compatibility process stops after command admission and restarts with the same exact configuration
- **THEN** an identical retry observes the existing Host message, command, and projection without replaying the turn

#### Scenario: Operator changes the mapping key
- **WHEN** startup observes a different mapping-key identity for a deployment that retains existing compatible Sessions
- **THEN** readiness fails or a new explicit namespace is required; the process does not probe old keys or create replacement Sessions silently

### Requirement: The architecture prerequisite is a hard apply gate
Implementation and activation of this Distribution MUST require the completed, verified target state of `separate-openzyme-kernel-from-capability-extensions`, including the `file_workspace_public@2` Host/client cutover, exact EnzymeDesign composition, source/wheel qualification, and removal of required legacy callers. The implementation MUST NOT add an `@1` branch, import current legacy Host/Core internals, or claim compatibility against an incomplete target composition. Discovery of an unmet prerequisite MUST block apply or acceptance rather than be converted into this change's task scope.

#### Scenario: Target public client cutover is incomplete
- **WHEN** apply begins and the only available conversation/runtime path uses `file_workspace_public@1` or a Host internal service
- **THEN** implementation stops at the prerequisite gate and no compatibility fallback code is added

### Requirement: Non-live qualification proves protocol, orchestration, packaging, and negative boundaries
The compatible Distribution MUST add a named non-live qualification profile that exercises the real compatibility app, public client contract, fake/non-live Host, exact composition loader, and packaged artifacts. It MUST cover valid/invalid auth, models, non-streaming, SSE order and termination, `max_tokens=1`, session mapping, absent session identity, idempotent retry, per-Session conflict, restart observation, pending approval, runtime failed/locked/timeout/no-output, disconnect, bounds, contract/release drift, secret redaction, and exactly-one-command behavior. It MUST also inspect source imports, wheel metadata/content, dependency closure, manifest equality, delivery-surface classification, and absence/rollback behavior. A live LLM, Provider, network retrieval, browser, container, SSH, Slurm, HPC, MICU, or campaign result MUST NOT substitute for this deterministic proof.

#### Scenario: Protocol probe passes but orchestration duplicates drain
- **WHEN** `/v1` returns valid OpenAI-shaped bytes while qualification observes two distinct runtime commands for one turn identity
- **THEN** the profile fails and the Distribution is not ready for implementation acceptance or deployment

#### Scenario: Complete non-live profile passes
- **WHEN** every protocol, lifecycle, failure, package, composition, source-bound, and no-live scenario passes under the exact built artifacts
- **THEN** the result proves local L0 distribution readiness but does not claim live Provider/HPC, public deployment, competition review, or workflow terminal success

### Requirement: Documentation and release evidence move with the compatible Distribution
Implementation MUST update `docs/OpenZyme架构设计.md`, the relevant `docs/v3/` architecture/public-interface/distribution/operator documents, app/package READMEs, `distributions/README.md`, build/test inventory, and a compatibility deployment guide in the same slice. Documentation MUST distinguish Kernel, Adapter, Plugin, Driver, Distribution, and delivery surface; list supported and rejected L0 fields; define credentials, Session identity/lifecycle, persistence, concurrency, approval, timeout/disconnect, error and forbidden-fallback semantics; and identify `docs/openai-compatible-agent-integration-guide.md` as the external competition contract source. Release evidence MUST record exact source, wheels/assets, manifests/digests, non-live test commands, probe outputs, and known unsupported capabilities.

#### Scenario: Implementation exposes `/v1` but docs claim tool calling
- **WHEN** current docs advertise reasoning, multimodal, attachments, function calling, token streaming, or chat approval that the L0 surface does not implement
- **THEN** documentation alignment qualification fails despite passing basic endpoint tests

#### Scenario: Release evidence is complete
- **WHEN** the reviewed source, built artifacts, exact composition, public contract, operator guide, test inventory, and probe receipt all identify the same compatible release and limitations
- **THEN** the documentation/release gate records a source-bound non-live readiness result
