## ADDED Requirements

### Requirement: EnzymeDesign owns an executable resident-teammate Host launcher
`enzymedesign-distribution` SHALL provide an executable entry point that composes the adopted EnzymeDesign Plugin bundle with exact Store/workspace/runtime Adapters, provisioning/runtime workers and generic Host app. It MUST use only public OpenZyme seams and MUST NOT start a live provider, HPC route or scientific campaign by default.

#### Scenario: Start EnzymeDesign non-live composition
- **WHEN** valid product configuration and adopted Plugin manifests are supplied
- **THEN** launcher publishes the exact product release/bundle/catalog identities and starts the resident product surfaces

#### Scenario: Product Plugin binding is invalid
- **WHEN** a required manifest, role policy, registry snapshot or selected Adapter binding drifts
- **THEN** startup fails closed with the owning component identity and no Standard-only fallback

#### Scenario: Stop EnzymeDesign
- **WHEN** the product process retires
- **THEN** Host, workers, runtime/process owners, Plugin runtimes and Store stop in explicit owner order without creating scientific or Task terminal facts

### Requirement: EnzymeDesign role policy separates essentials from long-tail Plugin tools
For every EnzymeDesign resident role, the Distribution SHALL declare exact Direct role essentials, Deferred long-tail Plugin tools and Hidden forbidden tools against the adopted catalog. The policy MUST be digest-bound to the product release and MUST NOT rely on empty policy decisions.

#### Scenario: Reporter starts a turn
- **WHEN** a reporter role is admitted
- **THEN** stable collaboration verbs and declared reporting essentials are Direct while unrelated available scientific tools are Deferred or Hidden according to policy

#### Scenario: Model discovers a scientific long-tail tool
- **WHEN** capability inspection finds an available Deferred Plugin tool and explicitly expands it
- **THEN** only that tool becomes model-visible for the command and its existing route/authority/approval facts remain unchanged

#### Scenario: Role policy is incomplete
- **WHEN** the adopted Plugin catalog contains a tool without an exposure decision for the role
- **THEN** product admission fails rather than exposing all mounted tools

### Requirement: EnzymeDesign has a fresh product-level non-live resident E2E
EnzymeDesign acceptance SHALL construct the real product Distribution from empty temporary file-backed roots and recording substitutes, then prove the complete resident collaboration loop, product projections and Direct/Deferred/Hidden behavior. It MUST distinguish mounted, exercised and substituted surfaces.

#### Scenario: Complete the EnzymeDesign loop
- **WHEN** the test creates/provisions a Session, posts a workflow-bound message and explicitly drains a deterministic runtime
- **THEN** it observes durable workflow authority, assistant/tool transcript, collaboration truth and product extension projections

#### Scenario: Exercise Deferred expansion
- **WHEN** the fake model inspects and expands one long-tail Plugin tool
- **THEN** the report records that exact tool as mounted/exercised/substituted and proves no authority or route widening

#### Scenario: Attempt a real external product route
- **WHEN** the test reaches provider, HPC, SSH, Slurm, browser or external network code
- **THEN** qualification fails before effect and cannot be described as external readiness or deployment cutover
