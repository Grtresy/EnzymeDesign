## Why

文件化 writer、public surface 和历史 Git/LFS 迁移完成后，继续保留 artifact domain、表、storage 和 compatibility readers 会维持双重真相并允许旧路径复活。用户已选择在本轮物理删除这些数据结构，而不是长期只读保留。

> **当前 release gate：** `operator/source-only-removal-gate.json` 保留原文件名作为
> gate 审计槽，内容已升级为 `artifact_subsystem_removal_release_gate@4`。用户已授权
> 解析出的本地 deployment 执行数据迁移与 storage 删除；public epoch、静默、备份、
> historical inventory/global receipt 与 standalone verification 均已绑定。最终 DDL
> 仍须在 mutation 前重验 13 个正式 prerequisite receipts 与 non-mutating dry run。
> 实测 legacy storage deletion target set 为空；现有 repository-service Git/LFS 被明确
> 排除，绝无删除 authority。当前 exact manifest 已完成：final schema manifest、
> `offline_removal_complete` ledger、零 legacy structure/storage scan、数据库完整性与
> 正常启动均通过，原 removal authority 已消费且不可用于另一 deployment/manifest。

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
