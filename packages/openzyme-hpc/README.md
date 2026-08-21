# openzyme-hpc

HPC target、inventory 与远端 workspace 语义插件。

显式 `openzyme_plugin_manifest@1` 当前贡献 `openzyme.hpc.target-inventory@1`、
`openzyme.hpc.workspace@1`、`openzyme.hpc.compute-route@1`，以及
`hpc-primary.workspace-runtime`、`hpc-primary.revision-job` 两条 declared route。entry point 只定位
manifest；只有 Distribution 明确选择、校验 exact digest 并挂载 runtime 后才能激活。

## 当前 contract owner

本包现在是 `ExecutorHpcWorkspace`、provision/cleanup intent+receipt、credential claim、target
qualification 及其 closed lifecycle enum/digest 的唯一代码 owner。旧
`openzyme_domain.executor_hpc_workspaces` 兼容模块与顶层别名已经删除；仓内生产 caller 已改用
`openzyme_hpc`。这些对象可在 Plugin 私有状态中保存 runner handle、login alias、remote root 等 owner-only
locator，但共享 projection 必须继续调用其 redacted view，绝不能把 locator/credential 公开给其他 Agent。

本包还拥有 immutable `TargetToolchainInventory`、`TargetCapabilityFact`、
`SoftwareQualificationReceipt`、`InventoryGeneration` 和独立 transient health observation；
inventory closure 可以投影为 Kernel `ResourceCapabilityFact`，但 health 不参与 inventory/release digest。
`SQLiteTargetInventoryRepository` 只使用 `openzyme_hpc_*` namespaced tables，按 target 执行单调 generation
与 predecessor CAS，并原子写入 qualification receipts 和 inventory closure；它不会在正常启动时创建表，
只有显式 offline migration 可调用 `install_hpc_inventory_schema_for_offline_migration()`。旧的 opaque
`toolchain_digest` 已从 target qualification、Compute source manifest、runner config/wire 中移除；这些边界
现在同时携带 positive `inventory_generation` 和 exact `inventory_digest`，后者是结构化 inventory 的 closure。

`TargetQualificationWorkflow` 只允许 operator/admin，使用一个必须由 Kernel
`ControlledOperation` 支撑的 Adapter Port 执行 version query 与 deterministic smoke；
`dispatch_in_doubt` 只 reconcile 同一 occurrence，未闭合时不发布 inventory。Agent/import/turn
都不能触发 probe。

HPC lifecycle 的 observation、credential、provision/cleanup Port、settlement proof 与纯状态机已由本包唯一拥有，
Host 的 concrete provisioner/credential provider 已直接消费这些 contracts。本包 manifest 还精确声明并实现
`hpc.workspace.request/inspect/verify/sync_source/fs.read/fs.list/fs.mutate/exec`、两条 capability route runtime、
`openzyme.hpc@1` bounded safe projection、`openzyme.hpc.renderer@1` 只读 renderer contract 和
`openzyme.hpc.worker@1` bounded worker。
完整 workspace application、SQLite repository、generation/provision/credential/sync/retention/cleanup writer
现在都由本包唯一实现。它们只消费 Plugin-owned repository、显式 UoW callback 与窄
`ExecutorHpcWorkspaceKernelFactsPort`；Host gateway 负责把 Session、authority、revision 和 repository binding
事实翻译到该 Port，Plugin 不 import Core repository。Host 的 tool bridge 会在每个 opaque-ID 调用重新读取
owner、local/remote generation、target qualification 和 operation authority，再调用注入的 Workspace Runtime
Port；Shell admission 明确拒绝 scheduler 命令，raw receipt 永不声称 publication、scientific evidence 或
Task finish。组件标记为 `target_implemented_not_cutover`；EnzymeDesign 可按 exact manifest/mounted surfaces
选择它，但不得仅因 wheel 已安装就把它视为某个 Session 已激活。SSH/SFTP/rsync 与 Slurm 分别位于
`openzyme-hpc-ssh`、`openzyme-hpc-slurm` Adapter；真实 target 仍需独立 qualification 和 live 授权。

## 目标边界

HPC Plugin 通过 narrow Kernel application services 和 Workspace Runtime Ports 管理 remote workspace
identity/lifecycle；SSH Adapter 实现远端 process/filesystem/transfer，Slurm Adapter 只实现 scheduler。
login/file credential 永不包含 scheduler authority。HMMER/Vina 只声明 software + execution capability
requirements，通过 resolved route 使用 HPC，不能 import 本包的 repository/service 或 SSH/Slurm internals。

任何 provision/cleanup/remote mutation 的响应丢失都保持 `dispatch_in_doubt` 并 reconcile，不自动重试、
换 target、转本地执行、发布文件、采用科学结果或完成 Task。

## Non-live contract verification

```bash
.venv/bin/pytest -q packages/openzyme-hpc/tests/test_inventory.py \
  packages/openzyme-hpc/tests/test_qualification.py \
  packages/openzyme-hpc/tests/test_sqlite_inventory.py \
  packages/openzyme-hpc/tests/test_workspace_tools.py \
  packages/openzyme-hpc/tests/test_workspace_application.py \
  packages/openzyme-hpc/tests/test_routes.py \
  apps/openzyme-host-api/tests/test_hpc_workspace_tool_application.py
```
