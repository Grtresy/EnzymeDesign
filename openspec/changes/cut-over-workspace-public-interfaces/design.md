## Context

前序 changes 将 current work product truth从 artifact catalog迁到独立 agent Git workspace、immutable publication、revision/path handoff、executor HPC workspace、external job/result和 scientific deliverable。若 Host API、tool catalog、Pipeline SDK、restore context、events或 Web UI继续呈现 `artifact.*`、`artifacts.*`、`artifact_index`、`HpcStageRef`，模型和客户端仍会依赖已经退出 current architecture 的万能概念，并迫使 runtime维持 hidden reader/fallback。

本 change 是一次协调的 breaking public-contract cutover。它不负责迁移历史 bytes，也不物理删除 artifact schema/storage；迁移专用 reader在后续 historical migration完成前可留在离线 operator路径，但不得进入 current Host、agent、SDK或 UI surface。

## Goals / Non-Goals

**Goals:**

- 使 files、Git status、private/published revisions、reports、scientific deliverables、external jobs和 capability lease facts成为唯一 current public work-product vocabulary。
- 在同一 contract epoch内同步切换 Host workspace projection、CLI、model-visible tools、SDK、`world.inspect`、restore context、events、evals和 Web UI。
- 删除所有 current `artifact.*`、`artifacts.*`、`scientific.artifact.*`、`hpc.stage_artifact` schema和 `artifacts/artifact_index` projection。
- 通过显式 public contract version和catalog digest拒绝 stale clients；不以字段缺失触发 legacy读取。
- 保持 authority、approval、task terminal、runtime drain、effect certainty、secret/path redaction和 bounded projection语义。

**Non-Goals:**

- 不在本 change 中迁移 legacy artifact bytes/FKs，也不删除 artifact tables、blob roots或 archived source。
- 不自动 publish、commit、merge、sync、stage HPC input、完成 task、解决 approval或运行 recipient。
- 除 owning executor 的专门授权 workspace view 可返回其自身 login alias 与 workspace path 外，不把 Host path、Git credential、private ref ACL、SSH target、Slurm job id、其他 remote directory 或 raw logs 暴露给客户端。
- 不为旧 UI、旧 SDK或旧 agent prompt保留 compatibility projection、tool alias或 silent translation。
- 不改变 Git/LFS、workspace、publication、external job或 scientific deliverable各自的 canonical owner。

## Decisions

### 1. 使用一个协调的 public contract epoch，而不是逐端点渐进兼容

Host 定义 closed `file_workspace_public@1` contract，并将其 identity绑定到 API media/schema version、tool catalog digest、SDK contract version、restore-context version、event schema set和 UI build compatibility。session bootstrap与 workspace response明确投影该 contract；current mutation/read requests必须声明受支持 contract或使用由同一 Host提供的 CLI/SDK版本。

采用单一 epoch是因为 tools、projection和 restore context必须互相一致。若先删 tool而 UI仍读 artifact，或 SDK仍生成 stage descriptor，系统会产生无法由 agent修复的跨表面漂移。不同组件版本不匹配时返回 closed `public_contract_stale` / `workspace_schema_unsupported`，不得尝试旧字段或旧 tool。

保持产品 V3 session/task/runtime语义，但把 workspace public payload作为显式 breaking schema；不以路径版本号暗示 task/runtime也重写。

### 2. Workspace projection按 owner分区，不再构造通用目录 catalog

新的 projection 至少包含以下 bounded sections：

- `workspace`: agent member、workspace generation、clean/dirty/untracked/conflict状态和 bounded file tree/changed paths；
- `revisions`: current private commit/ref facts和可见的 immutable `PublishedRevision` history；
- `publications`: publication id、commit/tree、publisher、supersedes、path manifest摘要和 LFS closure状态；
- `reports`: report lifecycle与 exact published revision/path source；
- `scientific_deliverables`: role、attempt/selection/closure、revision/path、blob/LFS identity和 verifier状态；
- `external_jobs`: opaque job/result handles、workspace generation/revision、lifecycle/effect/reconciliation facts；
- `executor_workspace`: 仅 owning executor 可见的自身 HPC workspace id/generation、login alias 与 workspace path；普通 agent、共享 projection 和 execution/job section 不含该 locator；
- `leases`: capability lease scope、generation、expiry/revocation等安全事实，不含 token或 credential。

Projection不提供 `artifacts`、`artifact_index`、storage URI、Host local path或 runner-private locator。owning executor 的专门 section 是唯一 remote workspace locator 例外，且不能泄露另一 agent 的 path、raw job handle 或 transport state。大文件状态来自 Git/LFS pointer/object closure，不创建新的通用 asset catalog。文件树只描述拥有者可见 workspace和 authorized publication paths，且继续受 size/count/text budgets约束。

### 3. Model-visible tool与 Pipeline SDK只保留原生工作面和显式 control-plane effects

普通文件读写、目录操作、搜索和 Git操作在 agent clone内通过 OS/shell/Git/Git LFS完成。Model-visible catalog只为需要 Host authority的动作提供 typed tools，例如 workspace inspect/publish、publication lookup、protocol/task/report、scientific control、external-job lifecycle和 lease inspection。

删除 `artifact.*`、`artifacts.*`、`scientific.artifact.*`、`hpc.stage_artifact`和 `sandbox.file.*` compatibility authoring。Pipeline SDK删除 artifact helper与 stage/fetch descriptor；普通 pipeline代码直接使用 workspace paths和原生库，external job调用绑定 committed revision/workspace generation。Unknown old tool name返回 non-retryable stale-contract error，而不是映射到新 tool。

不采用“保留旧 tool但在内部转换”的方案，因为它会继续让 prompts、saved tool calls和 third-party clients生成 artifact identity，形成事实上永久的 compatibility writer。

### 4. Restore、reflection、prompt和 event使用相同 schema manifest

Tool reflection、agent system prompt、workflow manifest、saved runtime context和 continuation resume均固定 `file_workspace_public@1` 与 exact tool catalog digest。恢复时 Host先验证 session contract、SDK digest和 saved tool-call schemas；artifact-era context不能在 current runtime中继续执行，返回显式 unsupported/stale结果。

新 event只表达 typed owner动作，例如 workspace generation、revision commit/publication、report publication、scientific deliverable、external job/result和 lease lifecycle。`artifact.recorded` 等旧 event不投影为 current event，也不被 reducer翻译。历史 event只能由迁移/审计工具读取。

### 5. Web UI按工作流对象展示，不能回退到 artifact tree

UI将 output panel拆为 workspace files/Git status、publication history、reports、scientific deliverables、external jobs/HPC workspace和 lease facts。文件 detail显示 revision/path/blob或 LFS OID/size、publisher和 handoff；job detail只显示 opaque run/job handle与 safe lifecycle。UI state reducer严格验证 schema contract，遇到 artifact-era payload显示明确的 upgrade/unsupported状态，不尝试从 `artifacts`重建文件树。

UI build与 Host contract不匹配时启动失败或进入不可操作错误页；不得部分启用会发旧 tool/API payload的 controls。

### 6. Legacy sessions退出 current runtime，而不是获得 hidden per-session fallback

activation前必须将仍采用 artifact public contract的 session分类为：已关闭并等待 historical import，或显式不支持恢复。它们不得在 current runtime下接收 message、drain、approval、tool或 workspace mutation。Operator可在后续 migration中读取 legacy schema，但 public product不提供 per-session artifact compatibility mode。

选择显式阻断而不是双版本 Host，是为了保证 current product只有一个工具面和一个 work-product truth。历史可读性由 Git/LFS import receipt负责，不由在线 fallback负责。

### 7. Public errors本身是 closed contract

以下情况必须给出 bounded、non-retryable或 reconciliation-aware错误：contract/version/catalog mismatch、artifact-era session、unknown removed tool、missing publication/ref、private-source publication或execution的dirty revision、LFS closure failure、lease/fence失效和 job effect unknown。错误不得建议 artifact工具、自动 materialize/register/stage、自动 publish/merge或 backend fallback。

## Risks / Trade-offs

- [协调切换会让旧客户端立即不可用] → 通过明确 contract manifest、CLI/UI版本预检和 quiescent activation窗口提前发现；不以 hidden compatibility延长双重真相。
- [bounded file tree不能展示所有文件] → 提供稳定分页/continuation和 exact revision/path查询；不恢复全量 artifact index。
- [artifact-era session无法在线恢复] → activation前分类并冻结，由 historical migration保留 bytes/lineage；current runtime直接报告 unsupported schema。
- [工具重命名导致 saved continuation无法重放] → restore先验证 tool catalog digest，旧 context显式终止为 stale contract，不重新解释调用意图。
- [Git/LFS状态可能包含敏感路径或大文本] → projection继续使用 path allowlist、secret scanning、count/size budgets和 Host-private raw diagnostics。
- [组件分阶段部署造成短暂版本漂移] → Host、CLI、SDK、UI和 catalog作为同一 release train验收；不允许混合版本进入可操作状态。

## Migration Plan

1. 验证 repository/workspace/LFS/publication、capability lease、file sandbox、executor HPC workspace、revision job、revision/path handoff和 scientific deliverable changes均已完成，且 current writer不再创建 artifact records。
2. 在 disabled contract epoch下实现新 projection、tool catalog、CLI/SDK、restore/event schema和 UI；运行 contract fixture和完整 UI/eval回归，不对 current session开放。
3. 枚举所有 active/nonterminal session、continuation、pending approval、external execution和 UI client。先使工作 quiescent，再将 artifact-era session关闭/冻结或显式标记 unsupported；不得自动转换 saved calls。
4. 原子启用 `file_workspace_public@1`、新 catalog digest和相应 Host/CLI/SDK/UI build。旧 endpoints/fields/tool names在同一 release失效；不存在 dual projection或 alias窗口。
5. 验证 public responses/events/prompts/restore/UI bundle中没有 artifact catalog、stage ref、Host path或 job private handle，并验证 stale client得到 closed错误。
6. activation前失败时保持旧 release未切换并修正；activation后只做 forward repair，不重新启用 artifact public surface。
7. 保留的 legacy readers只能由 `migrate-historical-artifacts-to-git-lfs` 的离线 operator入口调用；完成历史迁移后由 removal change连同 runtime/schema一起删除。

## Open Questions

无。产品选择已由 1A、2A、3A、4A、5A、6B 固定；public contract采用一次性 breaking cutover，旧客户端和 artifact-era session均不获得 fallback。
