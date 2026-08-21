# 拆分前行为测试语义处置账本

## 证据边界

本账本覆盖提交 `5548ca85b0b581584379b4810e0777a6d97683b6` 中删除的旧测试 surface。它按行为
不变量而不是文件数量映射新 owner；删除一个旧文件不要求创建一个同名新文件，但每个仍受支持的行为必须有
当前 source 的 owner-local 测试，明确退休的行为必须有 absence/closed-schema 负例，真实外部行为必须留在显式
live gate。测试 helper、`conftest.py` 和 frozen provider fixture 不单独形成产品不变量。

处置状态只有四种：

- `preserved`：不变量保留，由新 owner 的测试直接证明；
- `moved`：能力迁至 Adapter/Plugin/Product Plugin，由新 owner 测试证明；
- `retired`：旧 surface 被删除，由 import/catalog/schema/route absence 负例证明；
- `live-gated`：非 live 架构不声称外部可达，留给明确 opt-in 的后续资格。

## 语义映射

| 旧行为包/代表测试 | 处置 | 当前 owner 与直接测试 | 保留或退休的语义 |
| --- | --- | --- | --- |
| `openzyme-core/test_task_board.py`、`test_lane_manager.py`、`test_protocols.py`、Host `test_api.py` | preserved | `openzyme-kernel/tests/test_task_application.py`、`test_collaboration_application.py`、`test_protocol_application.py`；`openzyme-standard/tests/test_standard_v2_host.py` | Task/Dependency、Lane、delegation/inbox、显式 `task.finish`；消息入口不隐式 drain 或完成 Task |
| `test_agent_capability_*`、Host `test_security.py` | preserved | Kernel `test_authority_application.py`、`test_authority_lease_application.py`、`test_runtime_capability_gateway.py`；Store `test_authority_entity_codec.py` | authority lease、generation/fence、operation scope、stale writer rejection；旧 `AgentCapabilityLease` 公共命名退休 |
| `test_agent_scheduler.py`、`test_runtime_commands.py`、`test_agent_runtime_settlements.py`、`test_agent_retirement_runtime_races.py` | preserved | Kernel `test_runtime_coordination_application.py`、`test_runtime_turns.py`、`test_coordination_application.py`；Standard `test_message_ingress_sqlite.py` | durable signal、bounded drain、claim lease、process epoch、retirement fence、runtime terminal 不等于 Task terminal |
| `test_mutation_quiescence.py`、`test_mutation_settlement.py`、`test_durable_events.py`、`test_failure_diagnostics.py` | preserved | Kernel `test_controlled_operation_application.py`、`test_composition_diagnostics.py`、`test_workspace_operations.py`；Contracts `test_reliability.py` | effect certainty、quiescence、durable event/failure、earliest cause、zero redispatch/fallback |
| `test_agent_git_workspaces.py`、`test_repository_binding_*`、`test_repository_credentials.py`、`test_repository_retention.py` | moved | Contracts `test_repository_bindings.py`、`test_workspace_*`；Git/LFS Adapter `test_agent_workspaces.py`、`test_credential_*`、`test_repository_*`、`test_ref_policy.py` | Git-shaped identity 暂保留；provision/credential/ref/LFS/retention mechanism 由 Adapter 拥有 |
| Host `test_repository_native_clients.py`、`test_repository_operations.py`、`test_repository_transport.py`、`test_repository_preflight_security.py`、`test_repository_runtime_pin.py` | retired/moved | Git/LFS Adapter `test_clone.py`、`test_client_qualification.py`、`test_revision_backend.py`、`test_publication_policy.py`；Kernel `test_architecture_inventory.py`、`test_compat_caller_audit.py` | `repository-service` 与旧 Host transport/runtime pin surface 退休；新的 repository mechanism 只经 Workspace/Publication Ports，不恢复第二 authority |
| Domain `test_revision_path_handoffs.py`、Core `test_report_publication.py`、`test_scientific_file_deliverables.py` | moved | Contracts `test_workspace_publications.py`；Kernel `test_publication_application.py`、`test_task_evidence_application.py`；Science `test_science_plugin.py`、`test_sqlite_transaction_integration.py` | immutable `PublishedRevision + RevisionPathRef`、verified byte、generic evidence、Science validator；publication/report/job 不自动完成 Task |
| `test_agent_capsule_image.py`、`test_sandbox_host.py` | moved | Podman Adapter `test_capsule_image.py`、`test_container_lifecycle.py`、`test_preflight.py`、`test_process_adapter.py`、`test_workspace_volumes.py` | process/image/isolation mechanism 离开 Kernel；bounded argv、no hidden fallback 与 cleanup receipt 保留 |
| Host/Core `test_executor_hpc_workspace_*`、`test_workspace_revision_execution_*`、旧 `openzyme-execution/test_workspace_revision_adapter.py` | moved | HPC `test_workspace_application.py`、`test_workspace_lifecycle.py`、`test_workspace_state_machine.py`、`test_workspace_tools.py`；Compute `test_compute_lifecycle.py`、`test_sqlite_restart_reconciliation.py`；runner `test_workspace_revision_job_wire.py` | opaque remote workspace、revision-bound job、scheduler/login 分离、response-loss reconcile、owner result handoff |
| Host `test_aox_*`、Core `test_scientific_attempt_lifecycle_architecture.py`、`test_scientific_workflow_contracts.py` | moved | EnzymeDesign AOX `test_architecture_qualification.py`、`test_file_bundle_finalizer.py`、`test_workflow_contracts.py`；AOX executor `test_aox_*`；Science `test_science_contracts.py` | AOX 固定科学语义归产品；generic Science 只拥有 attempt/selection/adoption/deliverable/validator lifecycle |
| Core `test_bio_research_tools.py`、Engines EBI HMMER fixture | moved | `enzymedesign-bio-providers/tests/test_plugin.py`、`enzymedesign-hmmer/tests/test_hmmer_plugin.py`、Distribution real product cross-layer test | bio/HMMER 不进入 Kernel；formal HMMER 经 capability route、Driver、Compute，raw shell 不成为正式证据 |
| Engines/Core `test_engines.py`、`test_deep_research.py`、Runtime `test_research_tools.py`、Research `test_adapters.py` | moved | Research `test_contracts.py`、`test_plugin_runtime.py`、`test_provider_runtime.py`；Tavily Adapter `test_adapter.py`、`test_component_manifest.py` | Research Plugin 拥有语义和 bounded orchestration；Tavily 只实现 provider Port；Core 无 `task.kind == research` planner |
| Core `test_report_publication.py` 的 report-specific lifecycle | moved | Reporting `test_reporting_contracts.py`、`test_reporting_plugin.py`、`test_sqlite_transaction_integration.py` | report draft/render/projection 属于 Reporting Plugin；Kernel 只保存 generic publication/evidence refs |
| Runtime `test_ai.py`、`test_limits.py`、`test_reliability.py`、`test_runtime_identity.py`、`test_settings.py`、`test_public_diagnostics.py` | moved | runtime SPI `test_runtime_spi.py`；LLM Adapter `test_runtime_adapter.py`、`test_component_manifest.py`；Kernel `test_runtime_turns.py`、`test_composition_diagnostics.py` | bounded turn/error fidelity 属 Kernel contract；provider/config/token/model mechanism 属 Adapter；无 provider fallback |
| Host/CLI/UI `test_api.py`、CLI `test_cli.py`/`test_receipts.py`、UI `file_workspace.test.js`/`state.test.js` | moved/retired | Host `test_v2_app.py`、Standard `test_standard_v2_host.py`；Client/CLI `test_v2_client.py`；当前 UI `client/controller/core_shell_v2/view` tests | 在线 surface 只接受 `file_workspace_public@2`；`@1` 和旧 artifact/repository 字段为 offline reader 或 closed-schema rejection |
| Core `test_migrations.py`、`test_offline_*`、`test_sqlite_uow.py` | moved | Store `test_migration_and_startup.py`、`test_offline_cutover_*`、`test_unit_of_work.py`、`test_device_fresh_reset.py`、owner startup/schema tests | SQLite/UoW/migration mechanism 归 Store；startup 不 opportunistically migrate；reset/cutover 只在 operator 授权 occurrence 中发生 |
| `preprocess-backend/tests/test_api.py` | moved | `enzymedesign-docking-preprocess/tests/test_preprocess_plugin.py` | RDKit/Meeko/Open Babel/Vina preprocess 是 EnzymeDesign Plugin，不是 generic Host API |
| Host/Research/Runtime 的 `integration/test_live_*`、`test_llm_connectivity.py`、`test_live_testing.py`、`test_live_token_ledger.py` | live-gated | 当前 non-live qualification 的 `no_live_effects` guard、architecture registry exclusions；后续单独授权的 provider/HPC qualification | 本 change 不声称 Provider、SSH、Slurm、HPC、Chrome 或容器真实可达；不把删除旧 live smoke 解释为 live 已通过 |
| 旧 helper：`conftest.py`、`agent_capability_test_support.py`、`repository_test_support.py` | retired | owner-local fixtures 与 typed test builders，另由 wheel/import/archive exposure gate 检查旧 package 不可导入 | helper 不拥有语义；不保留兼容 import 或旧 test-only authority |

## 产品级补充证明

`test_real_product_composition_runs_hmmer_and_vina_through_one_pinned_graph` 不是旧文件名的机械替代，而是闭合多组
跨层不变量：generic Host bootstrap、Session composition pin、root authority、真实 immutable publication、
publication-owned path verification、adopted HMMER/Vina inventory、effective affordance、exact route、mounted
Driver、durable Compute、声明式 fake runner、result validation、owner continuation 和 Science finish validator。
测试还断言 Task 的状态与 state version 均未被 tool/result/validator 自动改写。

架构资格层把两种证据分开：

- `wire-contract.enzymedesign-catalog` 只解析 exact manifests/catalogs，明确不声称 runtime mount；
- `identity-semantics.enzymedesign-product-cross-layer` 只运行上述真实产品节点。

## 剩余边界

本账本不替代 19.12 的 final gates，也不把当前 working-tree focused green 变成 admission evidence。真实 external
Provider/SSH/Slurm/HPC、部署 credential、target installation 和 live cutover 仍须后续单独授权。若最终
architecture qualification、wheel closure、mainline 或 strict OpenSpec 失败，对应 preserved/moved 条目必须恢复为
未证明，而不能凭本 Markdown 保持绿色。
