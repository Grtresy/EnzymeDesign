# 十四项 cutover change 的统一最终验收规则

本文件是十四个目标 change 的共同证据解释，不是 receipt，也不授予运行、删除或 live authority。

## 不构成 acceptance 的材料

- source-only dependency gate、implementation snapshot、接口存在性和名称扫描；
- 旧 source revision 上生成的 release/per-change/removal receipt；
- focused subset、单个 architecture scenario 或 isolated fixture 的 green；
- OpenSpec CLI 的 PostHog telemetry 成功、失败或网络噪声；
- live/provider/HPC 未运行这一事实本身。

旧 receipt 只作为 superseded history 保留到设备 reset；不能覆盖、改写或升级成新 receipt。PostHog
不进入任何 evidence digest，也不改变 `openspec status`、checkbox 或 strict validation 的本地结果。

## 当前直接证据入口

| 缺口 | 当前直接测试/门禁 |
| --- | --- |
| agent Git recovery | `packages/openzyme-core/tests/test_agent_git_workspaces.py` |
| workspace publication | `packages/openzyme-core/tests/test_agent_git_workspaces.py` |
| revision-path handoff cleanup | `packages/openzyme-core/tests/test_bio_research_tools.py` |
| workspace job wire/runner/Host/authority | `packages/openzyme-domain/tests/test_workspace_job_wire.py`; `apps/mcp-hpc-runner/tests/test_workspace_revision_job_wire.py`; `apps/openzyme-host-api/tests/test_workspace_revision_execution_boundary.py`; `packages/openzyme-core/tests/test_workspace_revision_execution_authority.py` |
| structured diagnostics | `packages/openzyme-core/tests/test_failure_diagnostics.py`; `scripts/audit-production-exceptions.py` |
| fresh/offline startup proof | `packages/openzyme-core/tests/test_migrations.py`; `packages/openzyme-core/tests/test_offline_removal_fixture.py` |
| scientific finalization | `packages/openzyme-core/tests/test_scientific_file_deliverables.py`; `apps/openzyme-host-api/tests/test_aox_file_bundle_finalizer.py` |
| public/UI cutover | `apps/openzyme-web-ui/tests/file_workspace.test.js`; `client.test.js`; `state.test.js`; `controller.test.js`; `view.test.js`; production build |
| retired surface | `scripts/audit-v3-compat-callers.py`; `packages/openzyme-core/tests/test_compat_caller_audit.py` |
| architecture composition | current 19-scenario `docs/v3/architecture-qualification/invariant-registry.json` and pure-verified full report |

这些入口只说明证据位置，不预先声明通过。最终 evidence map 必须记录 final source identity、exact command、
exit/result digest、未运行的 live gates和设备 fresh-reset proof。

## 重新完成与签发顺序

原 change 中恢复为 `[ ]` 的行为任务只在对应 direct tests、完整 non-live gate、architecture
qualification 和 mainline 都通过后重新勾选。最终 receipt 任务还必须等待设备精确 inventory、quiescence、
逐项删除、零残留扫描、fresh schema 初始化与 `DeviceFreshInstallResetReceipt` 独立验证。十四个
per-change receipts、release bundle 和 closure receipt 必须绑定同一 final source，并按 no-replace 顺序签发。
