# Requirement evidence audit

本文件把本 change 的全部 162 个 delta requirements 映射到当前代码、owner-local
测试和文档。映射单位是 spec owner bundle：同一小节列出的每条 requirement 都必须同时由该小节的
source、test 和 document 三类直接证据支持；任一引用缺失或最终 gate 失败，该小节全部恢复为
`unproven`。场景级跨层证明另由本文末尾的 architecture qualification family closure 提供。

2026-08-21 的单独授权覆盖本机旧空部署删除与 EnzymeDesign fresh activation；证据见
`operator/device-fresh-install-20260821.md`。删除前缺少完整 `@2` 逐路径 inventory/occurrence log，正式 reset
receipt 不能追认，`18.9` 仍未勾选。Provider、SSH、Slurm、HPC、容器和 live campaign 未执行。

## enzymedesign-product-composition

直接证据：

- source：`packages/enzymedesign-distribution/src/enzymedesign_distribution/composition.py`、
  `distributions/enzymedesign/openzyme-composition.toml`、`packages/enzymedesign-aox/`、
  `packages/enzymedesign-hmmer/`、`packages/enzymedesign-vina/`、
  `packages/enzymedesign-docking-preprocess/` 与 `packages/enzymedesign-aox-executor/`；
- tests：`packages/enzymedesign-distribution/tests/test_distribution.py`、各
  `packages/enzymedesign-*/tests/` 以及
  `apps/openzyme-host-api/tests/architecture_qualification/scenarios/test_composition_profiles.py`；
- docs：`docs/v3/enzymedesign-distribution.md`、`docs/v3/01-target-architecture.md` 和
  `docs/OpenZyme架构设计.md`。

Requirements proven：

1. EnzymeDesign is a distinct explicit product Distribution.
2. Enzyme-specific scientific contracts belong to EnzymeDesign.
3. Biological research and sequence analysis are vertical Plugins.
4. Structure, docking and preprocessing are vertical Plugins.
5. Generic pipeline SDK and AOX calculation code are physically separated.
6. Vertical Host, worker, route and UI surfaces register through manifests.
7. EnzymeDesign consumes only public OpenZyme seams.
8. EnzymeDesign has product-level non-live qualification.
9. EnzymeDesign code and documentation form one product boundary.

## file-workspace-cutover-assurance

直接证据：

- source：`scripts/architecture_qualification_runner.py`、
  `scripts/test_gate/authoritative_runner.py`、
  `apps/openzyme-host-api/src/openzyme_host_api/architecture_qualification_report.py`；
- tests：`apps/openzyme-host-api/tests/architecture_qualification/test_final_harness.py`、
  `packages/openzyme-kernel/tests/test_test_gate_authoritative.py`、
  `packages/openzyme-kernel/tests/test_test_gate_replay.py`；
- docs：`docs/v3/architecture-qualification/README.md`、`docs/v3/test-gate.md` 和本 change
  `tasks.md`/`completion-evidence.md`。

Requirements proven：

1. Change completion markers follow current authoritative evidence.
2. Qualification covers current behavior and forbidden outcomes.
3. Architecture qualification uses production composition and declared ports.
4. Scientific and UI acceptance uses direct current tests.
5. Final evidence is source-bound and generated in one closed order.
6. Full mainline and strict OpenSpec are necessary but not individually sufficient.
7. Archive is an evidence consequence rather than an operator shortcut.

## file-workspace-deployment-proof

直接证据：

- source：`packages/openzyme-store-sqlite/src/openzyme_store_sqlite/deployment_proof.py`、
  `device_fresh_reset.py`、
  `offline_cutover.py`、`offline_cutover_planning.py`、`offline_cutover_apply.py` 和
  `packages/openzyme-kernel/src/openzyme_kernel/deployment_activation.py`；
- tests：`packages/openzyme-store-sqlite/tests/test_deployment_proof.py`、
  `test_offline_cutover_contract.py`、`test_offline_cutover_planning.py`、
  `test_offline_cutover_apply.py`、`test_device_fresh_reset.py`、
  `packages/openzyme-kernel/tests/test_deployment_activation.py` 和
  `test_wheel_qualification_profiles.py`；
- docs：`docs/v3/deployment-composition-operator-guide.md`、
  `docs/v3/file-workspace-migration.md`、`docs/v3/compatibility-sunset.md`。

Requirements proven：

1. Deployment completion proof is an exact tagged union.
2. Fresh installation has one deterministic bootstrap receipt.
3. Offline removal requires one complete closed ledger.
4. Startup proof verification is read-only and diagnostically complete.
5. Device fresh-install reset deletes only an exact OpenZyme inventory.
6. Destructive reset requires quiescence and has no fabricated rollback.
7. Reset receipt and bootstrap receipt remain distinct evidence.
8. Deployment proof includes component wheel installation closure.
9. Offline cutover has a one-way activation boundary.

## file-workspace-public-interfaces

直接证据：

- source：`apps/openzyme-host-api/src/openzyme_host_api/file_workspace_v2.py`、
  `v2_app.py`、`packages/openzyme-client/src/openzyme_client/v2.py`、
  `apps/openzyme-web-ui/src/file_workspace_v2_state.js` 和
  `extension_renderer_loader.js`；
- tests：`apps/openzyme-host-api/tests/test_v2_app.py`、
  `packages/openzyme-client/tests/test_v2_client.py`、
  `apps/openzyme-host-cli/tests/test_v2_client.py`、
  `apps/openzyme-web-ui/tests/core_shell_v2.test.js`；
- docs：`docs/v3/04-public-interfaces.md`、`docs/v3/compatibility-sunset.md` 和
  `docs/v3/workflow-packs/README.md`。

Requirements proven：

1. Current public work products use one explicit file-workspace contract.
2. Workspace projection is partitioned by typed owner.
3. Declared and effective model-visible tool catalogs are separate.
4. Workspace tools expose structured local and remote operations.
5. Restore, reflection, prompts, and events preserve the exact current schema.
6. Web UI renders file, revision, publication, and job truth directly.
7. Artifact-era sessions do not receive an online compatibility mode.
8. Public cutover errors are fail-closed and strategy-neutral.

## openzyme-capability-resolution

直接证据：

- source：`packages/openzyme-contracts/src/openzyme_contracts/capabilities.py`、
  `packages/openzyme-kernel/src/openzyme_kernel/catalog.py`、`binding.py`、`affordance.py`、
  `runtime_capability_gateway.py`；
- tests：`packages/openzyme-kernel/tests/test_binding.py`、`test_affordance.py`、
  `test_runtime_capability_gateway.py`、`test_session_composition.py`；
- docs：`docs/v3/03-capability-engines.md`、
  `docs/v3/extension-composition-manifest-reference.md`。

Requirements proven：

1. Four capability fact classes are distinct.
2. Capability dependencies use contracts rather than package names.
3. Declared tool catalog is derived from activated manifests.
4. Tool affordance is resolved per subject and turn.
5. Target-bound route selection is explicit.
6. Dispatch revalidates the exact affordance.
7. Capability inspection is safe and actionable.
8. Capability identities use layered digests.
9. Capability resolution and documentation share one contract.

## openzyme-compute-plugin

直接证据：

- source：`packages/openzyme-compute/src/openzyme_compute/lifecycle.py`、`contracts.py`、
  `runtime_contributions.py`、`workspace_revision_executions.py`，以及
  `packages/openzyme-execution-contracts/`、`packages/openzyme-execution-sdk/`；
- tests：`packages/openzyme-compute/tests/test_compute_lifecycle.py`、
  `test_compute_contracts.py`、`test_component_manifest.py`、
  `apps/mcp-hpc-runner/tests/test_workspace_revision_job_wire.py`；
- docs：`packages/openzyme-compute/README.md`、
  `docs/v3/execution-pipeline-docs/workspace-revision-jobs.md`。

Requirements proven：

1. Revision-bound formal compute is an optional Plugin.
2. Compute admission binds an exact immutable revision and route.
3. ExecutionWorkloadSpec is typed and provider-neutral.
4. Compute composes with Kernel ControlledOperation.
5. Compute providers and routes are capability-resolved.
6. Generic execution SDK is domain-free.
7. Runner wire contracts are narrow and independently deployable.
8. Compute results are opaque bounded and non-terminal.
9. Compute implementation and documentation align.

## openzyme-extension-composition

直接证据：

- source：`packages/openzyme-extension-spi/src/openzyme_extension_spi/manifests.py`、
  `manifest_codec.py`、`discovery.py`、`composition_config.py`，以及
  `packages/openzyme-kernel/src/openzyme_kernel/activation.py`、`extension_mount.py`、
  `session_composition.py`、`offline_plugin_change.py`；
- tests：`packages/openzyme-extension-spi/tests/test_manifests.py`、
  `test_manifest_codec.py`、`test_discovery.py`、`test_composition_config.py`、
  `packages/openzyme-kernel/tests/test_activation.py`、`test_extension_mount.py`、
  `test_offline_plugin_change.py`；
- docs：`docs/v3/extension-composition-manifest-reference.md`、
  `docs/v3/plugin-authoring-guide.md`。

Requirements proven：

1. Entry points locate implementations but never activate capabilities.
2. Manifests distinguish Adapter, Plugin, Driver and Distribution.
3. Plugin manifests are closed and digest-bound.
4. Composition produces deterministic layered bundle identities.
5. Capability dependencies resolve as a closed acyclic graph.
6. Registration catalogs reject every canonical collision.
7. Activation state distinguishes absent, invalid and resource-degraded Plugins.
8. Deployment activation and Session pin exact composition.
9. Extension state and migrations have exclusive namespaces.
10. Atomic Plugin participation uses a restricted short Unit of Work.
11. Plugin upgrade and removal are explicit offline operations.
12. Composition failures are structured and secret-safe.

## openzyme-extension-spi

直接证据：

- source：`packages/openzyme-extension-spi/src/openzyme_extension_spi/application.py`、
  `contributions.py`、`drivers.py`、`protocols.py`、`transactions.py`；
- tests：`packages/openzyme-extension-spi/tests/test_application_spi.py`、
  `test_manifests.py`、`test_discovery.py`；
- docs：`packages/openzyme-extension-spi/README.md`、`docs/v3/plugin-authoring-guide.md`。

Requirements proven：

1. Kernel Adapter Plugin Driver and Distribution are distinct contracts.
2. Extension SPI is implementation-free.
3. Plugins use narrow Kernel application services.
4. Plugin contributions are typed and closed.
5. Drivers remain subordinate to Plugins.
6. SPI and documentation move together.

## openzyme-hpc-plugin

直接证据：

- source：`packages/openzyme-hpc/src/openzyme_hpc/inventory.py`、`qualification.py`、
  `routes.py`、`workspace_application.py`、`workspace_lifecycle.py`、
  `packages/openzyme-hpc-ssh/src/`、`packages/openzyme-hpc-slurm/src/` 和
  `apps/mcp-hpc-runner/src/mcp_hpc_runner/workspace_revision_jobs.py`；
- tests：`packages/openzyme-hpc/tests/`、`packages/openzyme-hpc-ssh/tests/`、
  `packages/openzyme-hpc-slurm/tests/`、`apps/mcp-hpc-runner/tests/`；
- docs：`packages/openzyme-hpc/README.md`、
  `docs/v3/07-runtime-hpc-reliability.md`、`apps/mcp-hpc-runner/README.md`。

Requirements proven：

1. HPC target and executor workspace semantics are Plugin-owned.
2. HPC owns resource inventory and route contribution.
3. HPC workspace tools are explicit and owner-bound.
4. SSH filesystem transfer and Slurm are separate Adapters.
5. Login file credentials exclude scheduler authority.
6. HPC workspace lifecycle uses controlled effects and settlement.
7. HPC runner and public projection remain narrow.
8. HPC implementation and documentation align.

## openzyme-kernel-boundary

直接证据：

- source：`packages/openzyme-contracts/src/openzyme_contracts/`、
  `packages/openzyme-kernel/src/openzyme_kernel/coordination_application.py`、
  `authority_application.py`、`controlled_operation_application.py`、`runtime_turns.py`、
  `publication_application.py`、`workspace_operations.py`、`finish_validation.py`；
- tests：`packages/openzyme-contracts/tests/`、
  `packages/openzyme-kernel/tests/test_coordination_application.py`、
  `test_authority_application.py`、`test_controlled_operation_application.py`、
  `test_runtime_turns.py`、`test_publication_application.py`、
  `test_workspace_operations.py`、`test_finish_validation.py`、
  `test_architecture_inventory.py`；
- docs：`docs/v3/00-harness-doctrine.md`、`docs/v3/01-target-architecture.md`、
  `docs/v3/02-control-plane.md`。

Requirements proven：

1. Contracts wheel is implementation-free.
2. Kernel owns canonical collaboration truth.
3. Kernel owns generic authority and reliability semantics.
4. Kernel owns extension and capability resolution truth.
5. Kernel owns runtime coordination but not runtime mechanism.
6. Kernel owns Git-shaped immutable handoff semantics.
7. Kernel owns Workspace Runtime contracts but not mechanisms.
8. Kernel owns one generic controlled-operation lifecycle.
9. Kernel tool and invocation contracts are domain-neutral.
10. Finish validation is extension-aware and Kernel-controlled.
11. Kernel dependency direction is mechanically enforced.

## openzyme-layered-qualification

直接证据：

- source：`docs/v3/architecture-qualification/invariant-registry.json`、
  `scripts/v3_architecture_qualification.py`、`scripts/architecture_qualification_runner.py`、
  `scripts/qualify-openzyme-contract-wheels.py`；
- tests：`apps/openzyme-host-api/tests/architecture_qualification/`、
  `packages/openzyme-kernel/tests/test_wheel_qualification_profiles.py`；
- docs：`docs/v3/architecture-qualification/README.md`、
  `docs/v3/architecture/source-document-traceability.json`。

Requirements proven：

1. Qualification has three closed composition profiles.
2. Kernel qualification uses only fake infrastructure Ports.
3. Standard qualification uses the real Plugin-free Distribution.
4. EnzymeDesign qualification uses the real product Distribution.
5. Source, pyproject and wheel gates prove dependency direction.
6. Plugin removability and composition integrity are executable tests.
7. Capability inventory route and affordance behavior are executable tests.
8. Workspace Runtime behavior is qualified locally and remotely.
9. Existing V3 invariants remain equivalent across the split.
10. Implementation-documentation traceability is a release gate.
11. Qualification evidence is source-bound, non-live and non-authoritative for product state.
12. Completion requires implementation and documentation, not artifacts alone.

## openzyme-reporting-extension

直接证据：

- source：`packages/openzyme-reporting/src/openzyme_reporting/application.py`、`lifecycle.py`、
  `publication.py`、`projection.py`、`runtime_contributions.py`、`transaction.py`；
- tests：`packages/openzyme-reporting/tests/test_reporting_plugin.py`、
  `test_reporting_contracts.py`、`test_sqlite_transaction_integration.py`；
- docs：`docs/v3/reporting-extension.md`、`packages/openzyme-reporting/README.md`。

Requirements proven：

1. Reporting owns report-specific state and policy.
2. Report content is file-native and revision-bound.
3. Renderers and format validators are extension components.
4. Report lifecycle is separate from workspace publication and Task terminal.
5. Reporting validator is bounded and read-only for Core.
6. Reporting projection is namespaced and bounded.
7. Reporting failures preserve exact phase and no fallback.
8. Reporting source and documentation move out of Core together.

## openzyme-research-extension

直接证据：

- source：`packages/openzyme-research/src/openzyme_research/runtime.py`、`services.py`、
  `provider_runtime.py`、`packages/openzyme-research-tavily/src/` 和
  `packages/openzyme-science-research/src/`；
- tests：`packages/openzyme-research/tests/test_plugin_runtime.py`、
  `test_provider_runtime.py`、`test_reference_composition.py`、
  `packages/openzyme-research-tavily/tests/`；
- docs：`docs/v3/research-extension.md`、`packages/openzyme-research/README.md`。

Requirements proven：

1. Research orchestration is a provider-neutral extension.
2. Kernel does not choose Research from Task kind.
3. Research provider adapters are independently selectable.
4. Research external calls use controlled-operation semantics.
5. Research evidence remains source-bound and non-terminal.
6. Durable Research work is handed off through published files.
7. Science-specific literature policy is optional and layered.
8. Research implementation and documentation are independently removable.

## openzyme-runtime-adapter

直接证据：

- source：`packages/openzyme-runtime-spi/src/openzyme_runtime_spi/`、
  `packages/openzyme-runtime-llm/src/openzyme_runtime_llm/adapter.py`、`provider.py`、
  `packages/openzyme-process-podman/src/openzyme_process_podman/`、
  `packages/openzyme-kernel/src/openzyme_kernel/runtime_turns.py`；
- tests：`packages/openzyme-runtime-spi/tests/test_runtime_spi.py`、
  `packages/openzyme-runtime-llm/tests/test_runtime_adapter.py`、
  `packages/openzyme-process-podman/tests/`、
  `packages/openzyme-kernel/tests/test_runtime_turns.py`；
- docs：`docs/v3/05-agent-runtime.md`、`packages/openzyme-runtime-llm/README.md`、
  `packages/openzyme-process-podman/README.md`。

Requirements proven：

1. Runtime SPI is independent from runtime implementations.
2. Runtime commands bind exact canonical coordination identity.
3. Runtime outcomes are closed proposals rather than canonical writes.
4. Outcome consumption is lease and fence protected.
5. LLM and provider behavior belongs to a replaceable adapter.
6. Process isolation belongs to a replaceable process Adapter.
7. Runtime failure observations preserve cause and effect facts.
8. Runtime completion remains separate from continuation and Task completion.

## openzyme-science-extension

直接证据：

- source：`packages/openzyme-science/src/openzyme_science/attempts.py`、
  `attempt_lifecycle.py`、`application.py`、`deliverables.py`、`file_deliverables.py`、
  `projection.py`、`transaction.py`、`runtime_contributions.py`；
- tests：`packages/openzyme-science/tests/test_science_plugin.py`、
  `test_science_contracts.py`、`test_sqlite_transaction_integration.py`；
- docs：`docs/v3/science-extension.md`、
  `docs/v3/08-failure-recovery-and-scientific-attempts.md`。

Requirements proven：

1. Scientific lifecycle is owned by an optional extension.
2. Scientific attempts preserve exact identity and owner.
3. Science state mutations use Kernel authority and extension transactions.
4. Scientific deliverables are immutable file references.
5. Formal scientific closure remains explicit and atomic.
6. Science finish validation does not own Task terminal.
7. Science projection is extension-namespaced and model-blind.
8. Science policies remain general rather than Enzyme-specific.
9. Science implementation and documentation share one owner map.

## openzyme-standard-composition

直接证据：

- source：`packages/openzyme-standard/src/openzyme_standard/composition.py`、
  `host_gateway.py`、`factories.py`、`runtime_admission.py`、
  `distributions/openzyme-standard/openzyme-composition.toml`；
- tests：`packages/openzyme-standard/tests/test_composition.py`、`test_factories.py`、
  `test_host_gateway.py`、`test_standard_v2_host.py`、
  `apps/openzyme-host-cli/tests/test_dependency_boundary.py`；
- docs：`packages/openzyme-standard/README.md`、
  `docs/v3/deployment-composition-operator-guide.md`。

Requirements proven：

1. OpenZyme Standard is an explicit official Distribution.
2. Plugin-free Standard remains productively usable.
3. SQLite is the Standard persistence adapter.
4. Git and Git LFS mechanisms are Standard Adapters.
5. Generic Host mounts only declared extension surfaces.
6. CLI and Core UI are thin contract clients.
7. Standard defaults are explicit and replaceable.
8. Standard selects one exact implementation per single-valued Adapter slot.
9. Standard installation closure excludes optional capabilities.
10. Standard implementation and documentation move together.

## openzyme-target-toolchain-inventory

直接证据：

- source：`packages/openzyme-hpc/src/openzyme_hpc/inventory.py`、`qualification.py`、
  `sqlite_inventory.py`、`routes.py` 和
  `packages/openzyme-hpc/src/openzyme_hpc/migrations/001_target_toolchain_inventory.sql`；
- tests：`packages/openzyme-hpc/tests/test_inventory.py`、`test_qualification.py`、
  `test_sqlite_inventory.py`、`test_routes.py`；
- docs：`docs/v3/03-capability-engines.md`、`packages/openzyme-hpc/README.md`。

Requirements proven：

1. Target inventory generations are immutable and structured.
2. Tool Plugins declare qualification specifications.
3. Qualification is operator-controlled and adapter-executed.
4. Qualification receipts bind the real execution environment.
5. Session inventory adoption is explicit and operator-owned.
6. Qualification validity and target health are separate.
7. Target inventory is namespaced and secret-safe.
8. Inventory implementation and documentation move together.

## openzyme-workspace-runtime

直接证据：

- source：`packages/openzyme-contracts/src/openzyme_contracts/workspace_runtime.py`、
  `packages/openzyme-kernel/src/openzyme_kernel/workspace_operations.py`、`workspace_tools.py`、
  `packages/openzyme-process-podman/src/openzyme_process_podman/filesystem.py`、`process.py`、
  `packages/openzyme-hpc/src/openzyme_hpc/workspace_application.py`、
  `packages/openzyme-hpc-ssh/src/`；
- tests：`packages/openzyme-kernel/tests/test_workspace_operations.py`、`test_workspace_tools.py`、
  `packages/openzyme-process-podman/tests/test_filesystem_adapter.py`、`test_process_adapter.py`、
  `packages/openzyme-hpc/tests/test_workspace_application.py`、`test_workspace_tools.py`、
  `packages/openzyme-hpc-ssh/tests/test_workspace_adapter.py`；
- docs：`docs/v3/03-capability-engines.md`、`docs/v3/07-runtime-hpc-reliability.md`。

Requirements proven：

1. Workspace runtime contracts are Kernel-owned and provider-neutral.
2. Local and HPC workspace lifecycles remain distinct.
3. Workspace filesystem operations are structured and root-confined.
4. Workspace process requests are explicit and bounded.
5. Workspace mutations and process execution use ControlledOperation.
6. Workspace transfer references are opaque and manifest-bound.
7. Revision sync materializes but does not integrate a revision.
8. Local and HPC model tools have separate governance.
9. HPC login/file operations never grant scheduler authority.
10. Raw workspace results remain private and non-terminal.
11. Workspace runtime documentation matches adapters and tools.

## Scenario-family closure

`docs/v3/architecture-qualification/invariant-registry.json` 固定 12 个 family、27 个 required
scenario；完整 diagnostic qualification 必须全部执行且每个 scenario/invariant 都为 `satisfied`：

| family | required scenarios |
| --- | ---: |
| authority-composition | 3 |
| boundary-scale | 2 |
| bounded-terminal-convergence | 1 |
| evidence-projection | 3 |
| identity-semantics | 3 |
| operator-retirement | 3 |
| reconciliation | 2 |
| restart-fencing | 1 |
| strategy-neutrality | 2 |
| supervisor-progress | 2 |
| wire-contract | 2 |
| world-fidelity | 3 |

最终 completion evidence 必须记录：27/27 scenario pass、27/27 invariant satisfied、零 skip/xfail、
零 undeclared external effect、零 not-run，以及独立 verifier 对同一 payload digest 的验证结果。mainline、
wheel、static architecture 与 strict OpenSpec 均为必要的互补证据，不能彼此替代。
