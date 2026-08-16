## Why

文件化 writer、public surface 和历史 Git/LFS 迁移完成后，继续保留 artifact domain、表、storage 和 compatibility readers 会维持双重真相并允许旧路径复活。用户已选择在本轮物理删除这些数据结构，而不是长期只读保留。

> **当前源码 gate（2026-08-17）：** `operator/source-only-removal-gate.json`
> 已绑定直接前置 `historical_artifact_migration_source_only_gate@1` 的精确摘要。
> 前 13 个正式 completion/acceptance receipt、历史全局迁移 receipt、fresh
> Git/LFS 回读、public epoch、静默期与备份证明均尚不存在，因此本阶段只允许
> 实现纯 removal manifest、准入校验和无副作用 dry-run 合同。该 gate 不授予
> migration authority，也不允许注册 destructive migration、删除 runtime/schema
> 或触碰 legacy storage。

## What Changes

- **BREAKING**：删除 `ArtifactKind`、`SessionArtifactRecord`、artifact repositories/services/tools/projections、artifact mutation writers、`HpcStageRef` 和 current compatibility adapters。
- 通过 forward database migration 物理 drop artifact tables、FKs、triggers、indexes、artifact materialization/publication/scientific artifact structures，并更新所有 current schemas。
- 在历史迁移 receipt 全量通过后，删除已迁移的 legacy artifact blob/storage objects；任何未映射或 digest 未闭合对象阻止删除。
- 从 controlled-operation、sandbox、research、report、scientific、HPC 和 UI current code 中删除 artifact fields及 fallback；结果只使用 revision/path/job/result typed identities。
- repository history、archived OpenSpec 和旧 migration source 可保留为开发历史，但不得创建 runtime table、reader、writer 或 current product surface。
- 删除后启动发现旧 schema/data 时直接报 unsupported migration state，不自动重建 artifact 表或走 legacy path。

## Capabilities

### New Capabilities
- `artifact-subsystem-removal`: 定义 artifact runtime/schema/storage 的物理删除、删除前证明和禁止复活合同。

### Modified Capabilities

## Impact

影响几乎全部 V3 domain/core/runtime/engines/pipeline/Host/UI/HPC 代码、数据库 migrations、tests、docs 和部署数据。执行前必须证明前 13 个 changes 的 writer cutover、历史迁移和 public-surface 验收全部完成。
