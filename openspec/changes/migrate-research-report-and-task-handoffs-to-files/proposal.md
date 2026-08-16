## Why

research dossier、超大 tool result、report content 和 task evidence 当前分散在 EngineDocument 与 generic artifact aliases 中，导致同一内容存在两套身份。文件化 workspace 应让所有可交付工作物料以 published revision/path 交换，而结构化控制状态继续留在数据库。

## What Changes

- 在这次明确排序、统一后验验证的连续迁移中，先使用 `revision_path_handoff_source_only_dependency_gate@1` 继续源码迁移；该 gate 固定 `acceptance_proven=false`，不替代 C2--C5 最终 receipts，也不授权任何 publication、protocol delivery、task transition、credential、Git/LFS I/O、live 或外部 effect。
- researcher 将检索结果、source snapshots、分析笔记和 dossier 写入自己的 clone，并通过 explicit publication 交付 executor/reporter。
- executor/report writer 直接读取 fetched published files；protocol payload 只携带 bounded publication/revision/path refs，不复制文件 bytes。
- tool result 大内容、research dossier 和 report draft/final content 停止创建 artifact aliases；需要持久交付的内容写入 workspace file 并 commit。
- `task.finish` evidence 从 `artifact:<id>` 迁移到 closed typed refs，如 publication path、report、controlled-operation result 或 scientific deliverable；裸 mutable path/branch/URL 不可作为完成证据。
- `report.publish` 继续是报告业务动作，但其内容身份必须绑定 exact published file；它不等价于 `workspace.publish`，也不偷偷发布 dirty workspace。
- 任何 handoff 都不自动 merge、运行 recipient 或完成 task。

## Capabilities

### New Capabilities
- `revision-path-handoff`: 定义 research、tool result、report、protocol 和 task evidence 通过 published revision/path 交付的合同。

### Modified Capabilities

## Impact

影响 harness、deep research、EngineDocument consumers、protocol/task board、report drafts/publication、workspace projection、prompts、Host API 和 Web UI。科学 attempt/deliverable 在后续独立 change 中迁移。
