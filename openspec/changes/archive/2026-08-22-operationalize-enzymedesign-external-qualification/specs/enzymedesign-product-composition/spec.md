## ADDED Requirements

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
