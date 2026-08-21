# V3 Compatibility Sunset

## 当前决策

当前源码唯一的在线公共工作区合同是 `file_workspace_public@2`。`file_workspace_public@1`
及其 media type、事件、restore/continuation 和工具目录只能由显式离线历史 reader 解释；它们不进入
普通 Host、CLI、UI、SDK、Plugin mount 或 Session 组合。

文件工作区切换是 breaking release。当前产品 surface 中，下列旧边界为 `RETIRED`：

- generic artifact domain/repository/projection/storage 和 mutation writer；
- artifact tool、event、API/media、CLI/UI state 和 SDK module；
- artifact materialize/register/stage/fetch/publication helper；
- runner-facing catalog/staging payload 和 Host local path 输入；
- fresh-install 中的 artifact-era migration chain；
- `/v1`、`/v2` 产品路由和旧 workspace activation shape。

`RETIRED` 表示不得恢复 current caller、alias 或 translation。历史 OpenSpec、Git history、
冻结 receipt 和离线 operator 可以保留旧名字，但必须位于 normal import、entrypoint、tool
discovery、Host route 和 active DocumentRegistry 之外。

## 防回归审计

仓库审计命令：

```bash
uv run python scripts/audit-v3-compat-callers.py
```

静态删除 gate 还扫描 current app/package source、package exports/entrypoints、final SQLite
manifest、tool catalog、generated public schema 和 UI bundle。offline operator 和历史归档必须
使用显式 allowlist，不能因为目录名相似而进入产品扫描面。

零 caller 只是仓库事实，不是生产 deployment receipt。物理 storage 删除还必须满足
[file-workspace-migration.md](file-workspace-migration.md) 中的 exact historical migration、
backup、quiescence、schema rebuild 和 storage-zero gate。

## Closed error 语义

新请求或 saved continuation 使用旧工具/catalog/media/schema 时，返回不可重试的 removed
surface 或 stale-context error，并保留安全的原始 contract identity。禁止：

- 把旧工具自动改名为新工具；
- 合成 revision/path ref；
- 把 old database 当作 fresh database；
- 因 current code “不用了”就跳过 receipt；
- 通过 feature flag、empty count、backup 或 operator assertion 恢复旧路径。

普通 startup 面向 old/incomplete deployment 只暴露中性、不可重试且无 mutation 的部署错误，不重新导出
已删除领域模型。稳定分类至少区分：

- `legacy_schema_unsupported`：旧或未知 schema，要求 fresh reset 或另行授权的 offline cutover；
- `legacy_removal_incomplete`：同一 removal/cutover ledger 未闭合，只能继续 exact forward repair；
- `deployment_proof_missing` / `deployment_proof_invalid`：缺失或漂移的 bootstrap/cutover proof；
- `deployment_composition_mismatch`：Adapter/Extension/catalog/workspace backend 或 installed-wheel identity 漂移；
- `session_composition_upgrade_required`：Session pin/binding/inventory 与 active epoch 不一致。

所有 startup rejection 都在打开 repository writer、Plugin runtime、route、worker 或外部 effect surface 前发生，
返回 stable phase、safe expected/observed identity、`mutation_applied=false`、`effect_certainty=no_effect` 和
`fallback_performed=false`。系统不得尝试旧 reader、补写 proof、自动 migration、切换 Distribution 或忽略 optional
Plugin 的完整性错误。只有 optional Plugin 明确 absent/inactive 或 resource-degraded 且其 manifest closure 无错误时，
对应工具可以保持不可用而 deployment 继续启动。

## 保留的非兼容层

以下不是旧 artifact compatibility：

- `ControlledOperationExecution` 的 provider/effect lifecycle；
- revision-bound external job/result 和 opaque runner handle；
- agent capsule/persistent workspace 的受监督进程隔离；
- research source、report、scientific attempt 和 immutable published file；
- standalone historical Git/LFS verifier。

这些边界继续存在，但不得承载旧字段、catalog reference 或 silent fallback。
