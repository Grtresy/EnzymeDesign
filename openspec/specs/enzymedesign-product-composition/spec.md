# enzymedesign-product-composition Specification

## Purpose
定义 EnzymeDesign 作为显式产品 Distribution 的组件选择、垂直能力所有权、公开扩展边界与产品级 non-live 组合资格要求。
## Requirements
### Requirement: EnzymeDesign is a distinct explicit product Distribution
EnzymeDesign MUST declare a versioned Distribution that selects an OpenZyme Kernel, an exact Standard-compatible Adapter profile, selected Research, Reporting, Science, Compute and HPC Plugins, subordinate Drivers, and enzyme-specific Plugins. It MAY reuse the official Standard Adapter choices but MUST NOT treat Standard as a new semantic layer. OpenZyme Kernel and generic Standard MUST NOT be branded or configured as the EnzymeDesign product implicitly.

#### Scenario: Activate the EnzymeDesign bundle
- **WHEN** the exact product composition and all required extension distributions pass activation
- **THEN** new Sessions pin the EnzymeDesign bundle and expose only its declared vertical capabilities

#### Scenario: Run generic OpenZyme without EnzymeDesign
- **WHEN** Standard is installed and EnzymeDesign distributions are absent
- **THEN** the generic product starts without AOX, HMMER, docking, protein-database or enzyme-specific imports

### Requirement: Enzyme-specific scientific contracts belong to EnzymeDesign
AOX workflow contracts, fixed references, motifs, thresholds, sequence-similarity rules, enzyme-specific deliverable roles, report templates and acceptance/qualification policy MUST be owned by EnzymeDesign extensions. Base Science MUST receive them only through generic workflow/role registration.

#### Scenario: Validate an AOX deliverable bundle
- **WHEN** the AOX extension is active and the exact required published file roles and calculation receipts are supplied
- **THEN** EnzymeDesign applies its declared AOX contract while Science preserves generic attempt/deliverable identities

#### Scenario: AOX policy appears in base Science
- **WHEN** source, manifest or wheel inspection finds an AOX reference, role list or threshold in `openzyme-science`
- **THEN** vertical-boundary qualification fails

### Requirement: Biological research and sequence analysis are vertical Plugins
UniProt, RCSB, InterPro, HMMER/hmmbuild/hmmsearch, sequence parsing, motif scoring and similarity graph implementations MUST live in EnzymeDesign packages with their own tools, providers, schemas and qualification. They MUST NOT be present in Kernel, Standard or base Research.

#### Scenario: Invoke formal HMMER through EnzymeDesign
- **WHEN** an authorized Agent calls an exact formal HMMER tool in an EnzymeDesign Session and selects one currently available route
- **THEN** the HMMER Plugin constructs a typed ExecutionWorkloadSpec, the Compute Plugin owns its controlled execution lifecycle, and the result remains bound to the selected route and publication/evidence boundaries

#### Scenario: Run hmmbuild through raw remote Shell
- **WHEN** an Agent invokes `hmmbuild` through `hpc.workspace.exec` for exploration
- **THEN** the result is only a remote process receipt and cannot by itself satisfy HMMER scientific adoption, formal deliverable or Task-finish evidence

#### Scenario: Base Research is installed alone
- **WHEN** only generic Research is installed
- **THEN** no protein database, HMMER, Biopython or enzyme source policy is imported or advertised

### Requirement: Structure, docking and preprocessing are vertical Plugins
fpocket, Vina, AlphaFold catalog, PDBQT generation, RDKit, Meeko, Open Babel and molecule/docking preprocessing MUST be owned by EnzymeDesign structure/docking packages. Their dependencies MUST enter only the EnzymeDesign installation closure. Formal Vina and other external computation MUST produce a typed ExecutionWorkloadSpec and use the Compute controlled-operation lifecycle; raw workspace Shell remains exploratory and non-formal.

#### Scenario: Prepare a docking input
- **WHEN** an EnzymeDesign Agent invokes a declared preprocessing capability
- **THEN** the vertical extension processes the exact authorized revision/input and publishes or returns results through its declared file/effect contract

#### Scenario: Submit Vina to an HPC-backed route
- **WHEN** the Vina Plugin requires `openzyme.execution.revision-job` and `software.autodock-vina` and an adopted HPC route satisfies both on the same target
- **THEN** it submits through public capability and Compute contracts without importing the HPC Plugin, SSH Driver or Slurm Adapter

#### Scenario: Install OpenZyme Standard
- **WHEN** a fresh environment installs Standard without EnzymeDesign
- **THEN** RDKit, Meeko, Open Babel, Vina, fpocket and AlphaFold packages/catalogs are absent

### Requirement: Generic pipeline SDK and AOX calculation code are physically separated
The current pipeline surface MUST be split so `openzyme-execution-sdk` contains only the generic control-socket/revision protocol, while AOX calculations, reference data and biological dependencies reside in EnzymeDesign. An executor image MUST install only the layer required by its declared workflow.

#### Scenario: Build a non-biological executor
- **WHEN** a compute image installs only `openzyme-execution-sdk`
- **THEN** no AOX module, reference sequence, motif threshold or Biopython dependency exists in the image

#### Scenario: Build an AOX executor
- **WHEN** an EnzymeDesign AOX executor package is selected
- **THEN** its manifest binds the generic SDK contract plus the exact AOX calculation contract and resource digests

### Requirement: Vertical Host, worker, route and UI surfaces register through manifests
AOX qualification/finalizer, enzyme routes, capability workers, projection schemas, UI renderers and fixtures MUST be registered by EnzymeDesign manifests. Generic Host source MUST contain no direct AOX/HPC product imports or conditional route construction.

#### Scenario: Mount AOX routes
- **WHEN** the EnzymeDesign manifest passes exact route/catalog validation
- **THEN** Host mounts the declared vertical routes and UI renderer under their contract identities

#### Scenario: Remove EnzymeDesign from composition
- **WHEN** a generic Standard bundle is activated
- **THEN** all vertical routes, workers, projections and UI panels are absent without modifying Host source

### Requirement: EnzymeDesign consumes only public OpenZyme seams
EnzymeDesign packages MUST NOT import Kernel repository implementations, SQLite adapters, Host internal services, Git storage locators or private runtime implementation classes. They MUST use Contracts, public Kernel application commands/queries, extension SPI, revision/path refs and controlled-operation ports.

#### Scenario: Vertical code imports CoreRepositories
- **WHEN** AST or wheel inspection finds an EnzymeDesign import of a Kernel/SQLite repository implementation
- **THEN** dependency qualification fails even if the vertical workflow tests pass

#### Scenario: Vertical effect uses the public gateway
- **WHEN** an EnzymeDesign capability requests external computation
- **THEN** it submits through the declared Compute/ControlledOperation application seam with exact Session/authority/revision/route identity

### Requirement: EnzymeDesign has product-level non-live qualification
The EnzymeDesign composition MUST run its real manifest/Host/extension/migration/projection path with only declared external ports replaced. Qualification MUST cover existing AOX scientific identity/finalization, bio tools, execution/HPC, preprocessing, route/UI and removal-from-Standard boundaries without performing live Provider/HPC/Chrome/MICU effects.

#### Scenario: Generic layers pass but product composition is broken
- **WHEN** Kernel and Standard profiles pass but an EnzymeDesign tool, route, migration, projection or scientific invariant is missing
- **THEN** the product qualification fails and the change cannot claim complete extraction

#### Scenario: A test attempts a real external call
- **WHEN** product qualification observes an undeclared network, SSH, scheduler, container or browser effect
- **THEN** the scenario fails immediately and no live result is accepted as a substitute

#### Scenario: Only the mounted formal-compute slice is executed
- **WHEN** qualification mounts the full EnzymeDesign Distribution but executes only HMMER/Vina through Compute while other product application services or lifecycle prerequisites are deterministic substitutes or seeded facts
- **THEN** evidence names it as a real mounted product graph with a formal HMMER/Vina cross-layer slice and does not claim all Plugins or external systems are end-to-end verified

### Requirement: EnzymeDesign code and documentation form one product boundary
EnzymeDesign package READMEs, product/deployment docs, main architecture, relevant `docs/v3/` extension references and qualification inventory MUST match the actual vertical imports, manifests, tools, routes, resources and setup commands. Generic OpenZyme docs MUST clearly distinguish optional examples from Kernel/Standard ownership.

#### Scenario: Vertical source moved but docs use old package names
- **WHEN** current documentation still directs users to `openzyme-tools`, `openzyme-pipeline` AOX APIs or Host-internal AOX modules after extraction
- **THEN** source-to-document drift qualification fails

#### Scenario: Product inventory is current
- **WHEN** the EnzymeDesign manifest, built wheels, package READMEs, product deployment guide and qualification registry enumerate the same exact capabilities
- **THEN** the product documentation alignment requirement is satisfied

### Requirement: Product non-live qualification closes the external readiness catalog
EnzymeDesign product qualification MUST compare the exact selected Adapter/Plugin/Driver composition and declared operations against the external readiness catalog. It MUST execute the base profile and every explicitly enabled optional profile through deterministic recording Ports, including required failure/reconcile fixtures, while prohibiting real network, credential, Git service, container, SSH, scheduler, HPC and scientific-program effects.

#### Scenario: Full Distribution mounts but one Adapter operation is uncataloged
- **WHEN** product qualification finds a selected external operation absent from all profiles
- **THEN** readiness closure fails even if runtime mounting and the HMMER/Vina fake-runner slice pass

### Requirement: Product reports disclose mounted, exercised and substituted surfaces
Every product qualification report MUST list, per selected component and operation, whether it was declaration-verified, runtime-mounted, non-live exercised, backed by a deterministic substitute, real-subject qualified, cut over or observed live. Aggregate summaries MUST state that fake/no-op external Ports do not prove real environment availability.

#### Scenario: Reporting application is mounted with a no-op renderer
- **WHEN** the product scenario mounts Reporting but does not generate and render a real report artifact
- **THEN** the report records the mount and substitute separately and does not claim Reporting product E2E completion

#### Scenario: HMMER formal chain uses a recording runner
- **WHEN** the real Driver/Compute lifecycle completes against a deterministic runner result
- **THEN** the report claims the internal formal chain and separately records that `hmmbuild`/`hmmsearch` binaries were not executed

+## ADDED Requirements

### Requirement: Real qualification batches preserve profile closure
EnzymeDesign MUST define Batch 1 as `base`, `research-provider`, `hpc-primary`, `hmmer` and `docking`, and Batch 2 as `alphafold`. Each batch MUST have an independent identity closure, dry-plan digest, occurrence authorization, budget, receipt set and verdict. An unresolved optional profile MUST remain explicitly blocked rather than disappearing from the claimed batch, and Batch 2 state MUST NOT weaken or broaden Batch 1 evidence.

#### Scenario: AlphaFold resources are unresolved
- **WHEN** Batch 1 closes while AlphaFold image, model or database identity remains missing
- **THEN** Batch 1 may be adjudicated for its exact profiles and Batch 2 remains `blocked_identity`

#### Scenario: One Batch 1 optional profile is incomplete
- **WHEN** docking lacks one required exact operation receipt
- **THEN** docking remains unqualified and no Batch 1 claim states that all five profiles qualified

### Requirement: Qualified runtime cutover advertises only the adopted profile closure
The current EnzymeDesign cutover MUST adopt and advertise only the exact Batch 1 profiles `base`, `research-provider`, `hpc-primary`, `hmmer` and `docking`. AlphaFold MUST remain a visible deferred optional profile with `qualified=false`, `adopted=false`, `cutover=false` and no effective affordance. Batch 1 adoption MUST NOT erase or promote the Batch 2 verdict.

#### Scenario: Product catalog still declares AlphaFold after Batch 1 cutover
- **WHEN** the structural Distribution contains the AlphaFold Plugin and Driver but the deployment has no AlphaFold adopted facts
- **THEN** inspection reports it as mounted/deferred while affordance resolution exposes no qualified AlphaFold route

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
