> 统一整改证据解释见 [final-acceptance-policy.md](../close-file-workspace-cutover-verification-gaps/evidence/final-acceptance-policy.md)；source-only gate、旧 receipt 和 PostHog telemetry 均不构成最终 acceptance。

## 1. 前置 change source-only gate

- [x] 1.1 纯读取核验 C1 immutable acceptance；对尚待最终统一验收的 C2 绑定当前 source/schema/policy/interface identity 与 deferred acceptance，固定 `acceptance_proven=false`，不把 source snapshot 当作 capability、credential 或 production authority。
- [x] 1.2 对尚待最终统一验收的 C3/C4 绑定独立 clone、generation、clean checkpoint、frozen publication intent、whole-tree manifest、immutable `PublishedRevision` 与 explicit fetch 的当前源码接口；禁止据此 provision、publish、执行 Git I/O 或宣称验收闭合。
- [x] 1.3 对尚待最终统一验收的 C5 绑定 standard LFS transport、actual-byte closure、published pins、quota/retention/GC 与 native client contract 的当前源码接口；不得启动 writer/client、传输对象、运行 GC delete 或把接口快照当作正式 receipt。
- [x] 1.4 生成 `revision_path_handoff_source_only_dependency_gate@1`，绑定 C1 receipt、C2--C5 source gates、当前 commit 与关键接口 digests；仅允许继续源码、延后测试和文档，不授权 publication、protocol delivery、task transition、credential、Git/LFS I/O、live/effect，最终 prerequisite receipt 延后至统一验收重建。

## 2. RevisionPathRef 与 closed evidence schemas

- [x] 2.1 在 domain 中实现版本化 `RevisionPathRef@1`，绑定 publication、repository binding、commit/tree、normalized path、entry kind，以及 Git blob、LFS pointer/OID/size 或 tree/path-manifest identity。
- [x] 2.2 实现 path normalization、entry/object lookup 和 authorization validator，覆盖 absolute/traversal、symlink/submodule escape、mutable branch/private ref/URL/Host/HPC path 与 identity drift。
- [x] 2.3 实现 closed `TaskEvidenceRef@1` discriminated union，限定 `RevisionPathRef`、`ReportRef`、`ControlledOperationResultRef`、`ScientificDeliverableRef`，并拒绝 unknown variant、free-form digest 和 `artifact:<id>`。
- [x] 2.4 增加 revision-path/task-evidence repositories、migrations、immutable/foreign-owner constraints 与 bounded serializers，公共 projection 不暴露 bytes、credential、internal remote locator 或 remote absolute path。

## 3. Research 与 large tool result 文件化

- [x] 3.1 将 research source snapshots、citations、notes、analysis 与 dossier writer 切换为 researcher clone 内的 versioned layout和 ordinary files，要求 clean commit + explicit publication 后才能跨 agent 交付。
- [x] 3.2 将需跨 turn/agent/report/task 持久化的 large tool result 写入 producer workspace file，并让 tool response 返回 bounded local status或 published `RevisionPathRef`，不创建 generic artifact alias。
- [x] 3.3 将 `EngineDocument` 收缩为 bounded index/metadata + exact revision-path reference，停止写入第二份 authoritative dossier/tool-result bytes，并增加 dual-writer forbidden tests。
- [x] 3.4 更新 research providers、prompts、restore context 与 workspace projection consumers，使 current path只识别 revision/file identity，missing ref 时不读取 legacy artifact/EngineDocument bytes。

## 4. Protocol handoff 与 recipient Git 消费

- [x] 4.1 实现 bounded versioned protocol handoff payload，限定 producer、recipient、purpose 与有限 `RevisionPathRef` 列表，拒绝 embedded bytes、unbounded tool output、credential、branch、URL 和 raw paths。
- [x] 4.2 将 `protocol.send` 与 inbox/event serializers切换为 exact refs，证明发送只持久化 message/wakeup，不 fetch、merge、同步运行 recipient 或改变 task terminal state。
- [x] 4.3 实现 recipient native Git/Git LFS exact-publication fetch 与 commit/tree/path/object verification，不提供 Host materialize/download gateway或 alternate-ref fallback。
- [x] 4.4 增加已有 `PublishedRevision` handoff 回归：producer 当前 workspace 即使 dirty/untracked，validator 只检查 immutable publication/path且不得读取、拒绝或修改 producer 当前 tree。
- [x] 4.5 增加 recipient inspect/merge/rebase/cherry-pick/conflict flows，保证 integration strategy由agent选择，Git冲突不触发自动merge、revision substitution、task completion或 synchronous run。

## 5. Report 文件身份与业务 publication

- [x] 5.1 将 report draft/final body writer迁入 reporter clone file，数据库只保留 bounded report metadata/status 与 exact typed content refs，不创建 report artifact alias。
- [x] 5.2 修改 `report.publish` 使其只接受 authorized published `RevisionPathRef`，重验 publication/commit/path/object/media type/report owner，并证明它不读取dirty workspace、不push ref、不调用`workspace.publish`。
- [x] 5.3 实现 report revision/supersession：内容修改必须先形成新clean publication，再创建新report version；既有report body identity保持immutable。
- [x] 5.4 更新 Host API、events、workspace report projection 与 Web UI/report consumers，使 report business publication 和 workspace publication 始终显示为两个独立动作和状态。

## 6. task.finish typed evidence cutover

- [x] 6.1 将 `task.finish` schema/service/repository切换为 `TaskEvidenceRef@1`，在同一事务验证project/session/task ownership和canonical immutable owner后写入terminal decision。
- [x] 6.2 删除 current `artifact:<id>`、bare workspace path、branch、private ref、URL、Host/HPC path 和 free-form digest evidence authoring/compatibility parser，stale caller返回明确schema error。
- [x] 6.3 更新 task board、protocol wakeup、controlled-operation/report/scientific consumers，证明 evidence availability、report publication和job terminal均不会机械完成、失败、阻塞或恢复task。
- [x] 6.4 增加 exact replay、variant/owner drift、missing publication/path、LFS identity mismatch、stale writer 与 transaction rollback tests，保证零partial evidence或task terminal mutation。

## 7. 验证、架构文档与 change receipt

- [x] 7.1 运行 RevisionPathRef/path security、research/tool writers、protocol handoff/native fetch、dirty-producer immutable handoff、report.publish、task.finish union与no-auto-transition focused tests及 touched Python/TypeScript lint/test/build，并保存exact results。（整改登记：[GAP-HANDOFF-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
- [x] 7.2 同步 `docs/OpenZyme架构设计.md`、相关 `docs/v3/` control-plane/public-interface/report/runtime 文档、`docs/v3/execution-pipeline-docs/README.md` 与 `docs/v3/harness-complexity-audit.md`，明确 revision/path 单一交付真相、report双publish动作和 task authority。
- [x] 7.3 运行 `DO_NOT_TRACK=1 openspec validate migrate-research-report-and-task-handoffs-to-files --strict`、`git diff --check`、forbidden artifact/bytes-payload/fallback audit 与 `./scripts/check-mainline.sh`，确认无 live/provider/HPC effect。
- [x] 7.4 生成并 pure-verify `migrate-research-report-and-task-handoffs-to-files` change receipt，绑定 prerequisite receipts、source/schema/migration digests、writer cutover inventory、focused/mainline/docs results及 `implementation_complete=true`；receipt 不得完成 task、publish report或授予scientific authority。（整改登记：[GAP-HANDOFF-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)、[GAP-RECEIPT-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
