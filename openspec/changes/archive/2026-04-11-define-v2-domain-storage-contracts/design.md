## Context

`docs/OpenZyme V2 LangChain重写蓝图.md` 将 Phase A 的首要任务定义为先锁定 `domain model` 与 `DB schema`。当前主线仓库中的 V2 目录仅有保留用 README，尚未形成任何可被 graph、API、UI 共享的 typed contract，因此最容易出现的问题不是功能缺失，而是多个子系统同时定义不同的实体、状态枚举和存储 ownership。

这个 change 负责先把“状态真源”部分固定下来。它不实现 graph 节点，不实现 API，也不细化 Phase C 的研究/设计领域对象，但要为这些后续 change 提供稳定依赖。

## Goals / Non-Goals

**Goals:**

- 定义 V2 的核心业务实体和稳定 ID 体系。
- 明确 relational store、LangGraph checkpointer 和 artifact store 的职责边界。
- 为 Phase B 最小主链提供可直接消费的持久化关系和 ownership 规则。
- 让后续 graph、API 和 UI change 复用同一套 domain vocabulary。

**Non-Goals:**

- 不实现任何实际数据库迁移或 ORM 代码。
- 不定义 research evidence、candidate comparison 等 Phase C 细节模型。
- 不修改 `mcp-hpc-runner` 或其既有 spec。
- 不定义前端 read model 或 Host API wire format。

## Decisions

### 1. 以 episode 为 workflow 主体，以 project 为业务容器

V2 的核心实体分为两层：

- `Project`：长期业务容器，承载项目级元数据与归档视角；
- `Episode`：一次可恢复 workflow run 的业务主体，对应一个 LangGraph thread；
- 其下关联 `Decision`、`Approval`、`Run`、`ArtifactRecord` 和 `ReportRecord` 等记录。

采用这种层次是因为蓝图已明确 `thread_id = episode_id`，因此 episode 必须成为业务状态与执行状态的共同锚点；project 继续作为用户可见的长期组织单位。

备选方案：

- 直接以 project 作为 workflow 线程主体；
- 只保留 episode，不建 project。

不采用的原因是前者会让多轮 workflow 与项目视角纠缠，后者会削弱产品层组织能力。

### 2. 所有跨层引用使用稳定对象 ID，而不是路径或临时句柄

本 change 要求核心实体至少具备稳定的对象标识，并通过外键或等价引用关联，而不是依赖文件路径、checkpoint key 或前端临时句柄进行跨层绑定。

这样做可以确保：

- graph checkpoint、API 响应、UI projection 和 artifact index 共享同一套引用；
- 恢复、审批和 artifact 回看都能使用稳定 ID 进行关联；
- 后续迁移或新增 projection 时无需重定义主键语义。

### 3. 关系库存业务真状态，checkpointer 存图执行态，artifact store 存大对象

持久化职责固定为三层：

- relational store：`projects`、`episodes`、`decisions`、`approvals`、`runs`、`artifact_records`、`reports` 等业务记录；
- LangGraph checkpointer：当前 phase、节点局部 state、pending interrupt、checkpoint lineage 等 durable execution state；
- artifact store：日志、结构文件、报告文件、下载缓存和其他大对象。

这一定义直接对应蓝图的状态真源设计，可避免把 graph 内部状态错误地下沉到关系库，也避免把业务审计留在 checkpointer 黑盒里。

备选方案：

- 所有状态都进关系库；
- 所有状态都从 event/checkpoint 重建。

不采用的原因是两者都会显著提高实现复杂度或削弱解释性。

### 4. 关系库保持规范化业务表，read model 另行投影

本 change 只定义 canonical business tables，不把前端 read model 直接固化为主表结构。前端友好视图由后续 `define-v2-host-ui-contracts` change 单独定义 projection/read model。

这样可以：

- 保持业务真状态稳定；
- 避免为首版 UI 便利性提前污染 schema；
- 让 read model 随 UI 迭代而调整，而核心表结构保持保守。

### 5. 为 Phase C 预留扩展关联，但不提前细化领域细节

`EvidenceRecord`、`CandidateRecord` 等对象在本 change 中只需要保留“可与 episode / decision 关联”的扩展位约束，不在此刻锁死字段级结构。

这样既能给后续 change 留出位置，也能避免在没有 Phase C 设计前硬编码错误模型。

## Risks / Trade-offs

- [过早冻结实体名词] -> 先只锁定 Phase A/B 必需的核心实体，把 Phase C 细节留作扩展点。
- [关系库与 checkpointer 的分界不清] -> 在 spec 中显式写出“哪些状态必须进入哪一层”，避免实现时按方便落表。
- [read model 需求反推主 schema] -> 将 projection 明确留给后续 Host/UI contract change，避免本 change 混入界面优化字段。

## Migration Plan

- 先在本 change 中完成 domain 和 storage specs；
- 后续 `define-v2-graph-state-contracts` 以 episode ID 和 phase/state ownership 为前提继续定义 graph state；
- 最后由 `define-v2-host-ui-contracts` 基于本 change 的实体和存储边界定义 API 与 read model。

## Open Questions

- 无阻塞实现的开放问题；Phase C 细节故意延后，不在本 change 内解决。
