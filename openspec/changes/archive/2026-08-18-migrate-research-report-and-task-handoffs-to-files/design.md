## Context

research dossier、检索 source snapshot、超大 tool result、report body 与 task evidence 当前可能同时存在于 `EngineDocument` 内容和 generic artifact alias 中。独立 Git workspace 与显式 publication 建立后，可交付工作物料应只有一个共享身份：不可变 `PublishedRevision` 中的 exact path 及其 Git/LFS object identity。task、protocol、report status、controlled operation 与 scientific selection 等结构化控制状态仍由数据库拥有，不能退化为文件约定。

本 change 位于 file workspace、Git LFS 与 workspace publication 之后。producer 在自己的 clone 中自由组织内容、commit 并显式 publish；recipient 使用原生 Git/Git LFS fetch exact immutable publication ref，再自行选择 merge、rebase、cherry-pick、copy 或只读检查。Host 不代理文件 bytes，也不自动更新 recipient clone。

在本次明确排序且统一后验验证的连续迁移中，源码实现先消费 `revision_path_handoff_source_only_dependency_gate@1`。该 gate 绑定 C1 正式 receipt、C2--C5 当前 source-only gate 与关键 domain/service/migration identity，并列出全部延后验收；它固定 `acceptance_proven=false`、`final_source_revision_bound=false`、`production_effect_authorized=false`、`live_authorized=false`，唯一作用是允许继续修改源码、编写延后执行的测试和同步文档。它不得作为 capability lease、credential、publication、handoff、report、task evidence、runtime/live 或外部 effect 的 authority，也不得被提升为最终 prerequisite 或 acceptance receipt。

## Goals / Non-Goals

**Goals:**

- 以 closed `RevisionPathRef` 表达 research、large tool result、report 与 protocol handoff 的不可变文件身份。
- 让需要持久交付的内容写入 producer workspace、commit 并 publish，停止 generic artifact aliases 和重复内容 identity。
- 让 protocol payload 只携带有界 typed refs，不复制大文件 bytes。
- 将 `task.finish` evidence 迁移到 closed typed union，拒绝 mutable path、branch、URL 和 `artifact:<id>`。
- 保留 `report.publish` 作为报告业务动作，同时强制其 body 绑定 exact published file，并与 `workspace.publish` 分离。
- 保持 agent 对何时 fetch、如何整合、是否继续任务的策略自由。

**Non-Goals:**

- 不自动 publish dirty/private workspace，不自动 commit、push、merge或解决 Git 冲突。
- 不因为 handoff、fetch、report publication 或 external-job terminal 而运行 recipient、完成 task 或结束 scientific attempt。
- 不在 protocol、task、report row 或 event 中复制 file bytes。
- 不迁移 scientific deliverable 的 role/selection/attempt 语义；由 `migrate-scientific-deliverables-to-files` 处理。
- 不物理删除 legacy artifact/EngineDocument storage；最终删除由后续 migration/removal changes 完成。

## Decisions

### 1. 使用 closed `RevisionPathRef` 作为通用文件 handoff identity

`RevisionPathRef@1` 至少绑定：`publication_id`、repository binding version、published commit/tree identity、normalized repository-relative path、entry kind，以及该 entry 的 exact Git object identity。普通文件绑定 blob OID 与 byte size；LFS 文件同时绑定 pointer blob OID、LFS OID 与 size；目录绑定 tree OID 和 bounded path-manifest digest。

consumer 必须通过 `publication_id` 解析 canonical `PublishedRevision`，并核对 ref 中冗余 identity。path 必须规范化、非空、不得绝对化或包含 traversal；symlink/submodule 只能按 repository publication policy 的显式 entry kind 处理，不能跟随到 revision 外部。

只使用 branch/path、URL 或 mutable workspace path 无法抵抗 ref movement；只使用 content digest 又丢失 repository/path/provenance，因此不采用。

### 2. 可交付 research 与 large tool result 先成为文件，再成为 publication

researcher 将 source snapshots、notes、citations、analysis、dossier 与需持久交付的 tool outputs 写入自己的 clone。短小即时 tool response 可以留在当前 turn/message，但任何需要跨 agent、跨 turn、report 或 task evidence 使用的大内容必须落入文件、clean commit 并显式 publish。

`EngineDocument` 若暂时保留，只能作为有界检索/索引 metadata 并引用 exact `RevisionPathRef`；它不能保存另一份 authoritative deliverable bytes，也不能被 recipient 当作独立 handoff identity。generic artifact alias writer停止。

备选的“同一内容同时写 EngineDocument 与 artifact/file”会维持双重真相，故不采用。

### 3. Protocol payload 只传 bounded typed refs

protocol handoff 使用版本化 payload，包含 producer、recipient、purpose 和有界 `RevisionPathRef` 列表；不内嵌文件 bytes、unbounded tool output、Host path、remote workspace path、credential、raw branch 或任意 URL。`protocol.send` 仍只持久化消息并排队 wakeup signal，不 fetch、merge、执行 recipient 或改变 task terminal status。

recipient 收到 handoff 后使用原生 Git fetch exact immutable publication ref，验证 commit/path/object identity，再自行决定如何读取或整合。Host 不提供 materialize/download gateway，也不因 fetch 失败改用 artifact/EngineDocument bytes。

### 4. `task.finish` 接受 closed evidence union

`TaskEvidenceRef@1` 是 closed discriminated union，允许：`RevisionPathRef`、`ReportRef`、`ControlledOperationResultRef` 与后续定义的 `ScientificDeliverableRef`。每种 variant 都必须解析到 canonical immutable owner，并与当前 project/session/task 的授权关系一致。

裸 path、mutable branch、private ref、URL、Host path、remote HPC path、`artifact:<id>`、free-form digest 或无法解析的 legacy token 被拒绝。`task.finish` 记录 agent 的业务终态决定和 typed evidence，但不把 evidence 的存在自动解释为科学正确、报告已发布或 external effect 成功。

### 5. `report.publish` 绑定 exact published file，但不执行 workspace publication

report writer 在自己的 clone 中生成 draft/final file，显式 commit 并调用 `workspace.publish`。随后 `report.publish` 接受 exact `RevisionPathRef` 作为 report body identity，验证 publication、path、object bytes、允许的文件类型和 report ownership，再创建或更新报告业务记录及事件。

`report.publish` 不读取 dirty workspace、不 push private ref、不创建 `PublishedRevision`、不自动修正 path，也不把整个 repository 变成 report。报告修订必须先产生新的 published revision/path，再创建新的 report version或显式 supersession；既有 published report body identity不可变。

将两个 publish 合并会混淆 team file truth 与报告业务状态，因此保持两个显式动作。

### 6. Handoff 与消费完全不产生隐式业务推进

创建 publication、发送 ref、fetch revision、读取 file、发布 report 或取得 controlled-operation result 都只提供事实。它们不自动 merge recipient clone，不启动 recipient turn，不机械 complete/fail/block/cancel task，不结束 attempt，也不替 agent 选择下一步。既有 runtime signal、task/protocol 和 scientific owner继续拥有这些状态迁移。

### 7. Public projection 只暴露有界 identity 与安全 metadata

workspace、task、protocol 和 report projection 可以暴露 publication id、commit、normalized path、entry kind、safe size/digest 与业务状态；不得暴露 repository credential、Host path、internal remote physical locator、HPC remote path 或 file bytes。读取实际内容由已授权 agent 通过原生 Git/LFS 完成。

## Risks / Trade-offs

- [producer publish 后又修改 local file，recipient误读 mutable bytes] → handoff 始终绑定 immutable publication/commit/object identity，recipient从 exact ref 验证而不是读取 producer workspace。
- [handoff payload 携带大量 refs 造成 context/state 膨胀] → schema 对 ref 数量、path 长度、metadata 和诊断设置固定上限；大型目录使用 tree/path-manifest identity。
- [report 需要两个显式 publish 动作] → UI/tooling 展示清楚的 `workspace.publish` 前置状态和随后 `report.publish`，但不合并 authority 或自动执行。
- [EngineDocument 与文件迁移期间出现双 writer] → 逐 consumer 切换后一次性关闭旧 content writer；允许只读迁移检查，不允许 current runtime择一读取。
- [recipient fetch 或 merge 冲突] → 将 Git 错误直接返回给 agent，保持其选择 merge/rebase/cherry-pick/copy 的自由，不自动解决或 fallback。
- [typed evidence 只证明 identity，不证明科学质量] → task/scientific/report owner保留各自验证与终态规则，projection 不把 ref 存在提升为验收通过。

## Migration Plan

1. 先记录非验收的 source-only dependency gate，以当前 C2--C5 源码接口继续本 change；最终统一验收必须重新绑定正式前置 receipts、最终 source revision 和本 change 全部验证结果。该 gate 不开放 production writer、publication、protocol delivery、task transition、Git/LFS I/O、live 或外部 effect。
2. 完成 repository binding、capability lease、独立 workspaces、Git LFS 与 explicit `workspace.publish`；这些前置 change 向 capsule 提供原生文件/Git工具。所有 handoff producer/consumer 必须能 fetch exact publication；统一删除 legacy sandbox/artifact surface 必须在本 change 停止相关 writer 后进行。
3. 引入 versioned `RevisionPathRef@1` 与 `TaskEvidenceRef@1` schema、repository validation 和 bounded public projection；对 path traversal、identity drift、unauthorized publication 和 LFS mismatch fail closed。
4. 将 research source snapshot、notes、dossier 与 persistent large tool result writers迁入 workspace files；停止创建对应 generic artifact alias，EngineDocument 仅保留有界索引/ref metadata。
5. 将 protocol payload 与 recipient consumers切换为 bounded revision/path refs和原生 Git fetch。切换后删除 artifact/content bytes payload reader，不保留缺字段 fallback。
6. 将 report draft/final body迁入 reporter workspace；要求先 `workspace.publish`，再由 `report.publish` 绑定 exact published file。验证 report 修订与 stale/dirty path rejection。
7. 将 `task.finish` evidence writer/validator切换为 closed typed union；任何 current `artifact:<id>`、bare path/branch/URL caller使 cutover gate失败。
8. 更新 projection/event/UI consumers所需的 typed identity，但 public artifact tree 的最终删除由 `cut-over-workspace-public-interfaces` 完成。current writer在本 change 后不得继续制造新 artifact alias。
9. 旧内容保持冻结只读，等待历史 Git/LFS migration；不得 dual-write、backfill成 current publication或让 legacy bytes满足新 handoff。
10. 回滚仅在新 typed refs 尚未成为 current writer前允许整套版本回退。切换后采用前向修复并保留已发布 Git/LFS bytes；runtime不得在新 ref解析失败时读取 legacy artifact或EngineDocument副本。

## Open Questions

无未决产品问题。每类文件的 repository layout、允许 media type 与 payload 数量上限属于版本化 binding/schema 配置，必须在 rollout 前固定并测试，不允许运行时猜测。
