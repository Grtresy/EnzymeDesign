## ADDED Requirements

### Requirement: Research orchestration is a provider-neutral extension
`openzyme-research` MUST own Research request, source/evidence records, bounded orchestration, tools, workers, projection and extension state without owning Session, Task, Approval, publication or runtime truth. Its base contracts MUST NOT require Tavily, a browser, a scientific database or a model framework.

#### Scenario: Run Research with a fake provider
- **WHEN** the Research extension is activated with a deterministic provider adapter
- **THEN** its normal request/source/evidence lifecycle executes through the same manifest, tool and worker surfaces without Tavily or browser imports

#### Scenario: Research extension is absent
- **WHEN** Standard activates without `openzyme.research@1`
- **THEN** Core Session/Task/runtime/workspace behavior remains available and no Research table, tool, worker or projection is required

### Requirement: Kernel does not choose Research from Task kind
Core and Kernel MUST NOT inspect `task.kind == "research"` or another domain label to auto-invoke `deep_research.start`, change Task status or synthesize a Research brief. An Agent MUST explicitly invoke a Research capability, or a separately declared policy extension MAY propose the invocation under its own manifest identity.

#### Scenario: A research-labelled Task becomes ready
- **WHEN** a ready Task has kind `research` but no Agent or enabled policy invokes a Research tool
- **THEN** Kernel records no Research invocation and does not change the Task merely because of its kind

#### Scenario: Agent selects Research
- **WHEN** an authorized Agent invokes the exact Research tool in its Session catalog
- **THEN** normal tool admission and controlled-operation rules apply without a hidden planner step

### Requirement: Research provider adapters are independently selectable
Concrete web, document, Tavily or browser providers MUST live in separate provider adapter distributions with exact manifest/configuration identity. Provider selection MUST be explicit in composition and MUST NOT change Research or Kernel canonical schemas.

#### Scenario: Select Tavily explicitly
- **WHEN** composition includes the Tavily provider adapter with valid secret locator and manifest digest
- **THEN** Research dispatches only through that adapter and records its provider/operation identity without exposing the secret

#### Scenario: Tavily is unavailable
- **WHEN** Tavily fails or is not configured
- **THEN** Research records a structured failure and does not silently switch to a browser, another provider or fabricated source set

### Requirement: Research external calls use controlled-operation semantics
Every provider request that may have an external effect or ambiguous acceptance MUST bind a Kernel ControlledOperation identity, approval/capability context, deadline and reconciliation policy. Research MUST NOT implement independent retry, duplicate dispatch or effect-certainty status.

#### Scenario: Provider response is lost
- **WHEN** a provider may have accepted the exact Research request but its response is lost
- **THEN** the operation remains `dispatch_in_doubt` until exact observation/reconciliation and Research does not create a replacement request

#### Scenario: Request is rejected before dispatch
- **WHEN** schema, lease or approval admission fails before calling the provider
- **THEN** the operation records `no_effect` and no Research success/source evidence is created

### Requirement: Research evidence remains source-bound and non-terminal
Research source/evidence MUST bind request, provider, retrieval identity, bounded content/digest and provenance. A transcript, engine document, source count or provider success MUST NOT automatically become a PublishedRevision, Task evidence, scientific adoption or Task terminal fact.

#### Scenario: Research returns sources
- **WHEN** a Research operation settles with verified provider results
- **THEN** the extension records bounded source/evidence facts under its namespace and wakes the owning Agent without publishing files or finishing the Task

#### Scenario: Source provenance is incomplete
- **WHEN** a result lacks required retrieval identity or content digest
- **THEN** the Research result is rejected or marked incomplete and cannot be projected as verified evidence

### Requirement: Durable Research work is handed off through published files
An Agent that wants to share Research prose, tables or an index MUST write them in its workspace, create a clean checkpoint and explicitly publish a revision/path. Research projection MAY reference the resulting PublishedRevision/RevisionPathRef but MUST NOT store large report bodies as Core control-plane truth.

#### Scenario: Publish a Research summary
- **WHEN** the Agent writes and explicitly publishes a Research summary file
- **THEN** the extension links its Research identity to the exact immutable RevisionPathRef and later private edits do not alter that handoff

#### Scenario: Provider output exists only in extension state
- **WHEN** provider results have not been written and published by an Agent
- **THEN** another Agent cannot receive them as a verified file handoff through an implicit materialization fallback

### Requirement: Science-specific literature policy is optional and layered
PubMed, Semantic Scholar and literature quorum/quality policy MUST be provided by an explicitly composed science-research capability that may depend on Research and Science contracts. Base Research MUST NOT import or enforce these scientific source policies; EnzymeDesign biological databases MUST remain outside both base Research and Kernel.

#### Scenario: Use generic web Research
- **WHEN** composition enables base Research without science-research
- **THEN** no literature quorum, PubMed or Semantic Scholar schema is required

#### Scenario: Enable science-research
- **WHEN** composition explicitly adds the science-research manifest
- **THEN** its tools, evidence policy and projection appear under its own contract ID and are included in the Session bundle digest

### Requirement: Research implementation and documentation are independently removable
Research source, manifests, README, tool reference, provider configuration and `docs/v3/` capability-engine descriptions MUST identify Research as an extension. Removing it from composition MUST require no Kernel code or documentation rewrite beyond the active bundle declaration.

#### Scenario: Documentation still claims Core auto-plans Research
- **WHEN** current docs or prompts describe `DeepResearchTaskPlanner` or task-kind auto-routing after its source removal
- **THEN** documentation drift qualification fails

#### Scenario: Remove Research from Standard
- **WHEN** the extension has a valid removal disposition and is omitted from a new composition
- **THEN** its namespaced public section and tools disappear while Core schema and base documentation remain valid
