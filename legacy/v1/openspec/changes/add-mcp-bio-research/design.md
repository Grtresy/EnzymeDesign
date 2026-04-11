## Context

当前仓库已经把 Host agent 主线铺到可持续决策的状态：`packages/enzyme-host-runtime` 负责 agent workflow、`mcp-project-memory` 负责 canonical state、Web Host 和 CLI 负责跨入口恢复与操作。但这条主线目前几乎只消费用户输入、工具 observation 和启发式/LLM 推理结果，缺少一个稳定的外部生物研究证据入口。

`docs/OpenZyme架构设计.md` 已经把 `mcp-bio-research` 定义为 Phase 2 组件，职责是封装 PubMed、Semantic Scholar、UniProt、RCSB/PDB 等 research 检索与结构化抽取。与此同时，`mcp-enzyme-design-knowledge` 被放在更后面的 Phase 3，用于沉淀已审核知识。这意味着本次设计必须先把“外部 research evidence”与“长期 knowledge object”分层，而不是把两者混成一个服务。

现在又新增了 `add-host-capability-discovery` 这个 companion change，用来解决“不能把所有 MCP 的完整 schema 一次性塞给 agent”的问题。`mcp-bio-research` 正是最容易触发该问题的 MCP 之一，因为它背后会聚合多个 docs/API 与本地数据库来源。因此这次设计需要把 bio research 明确建模成一个通过 capability discovery 按需展开的 MCP，而不是一个默认全量可见的 tool bundle。

## Goals / Non-Goals

**Goals:**
- 新增独立的 `mcp-bio-research` 服务，用统一 MCP 边界承接 literature、structure 和 annotation research。
- 为 research 结果定义稳定的 evidence 引用、resource URI 和 prompt surface，使 Host 能复用这些结果而不复制整段原文。
- 让 `mcp-bio-research` 作为首批 capability discovery 接入对象，默认只暴露 summary，按需返回 detail contract。
- 让 Host agent 可以把 research 检索当成一种受控 workflow 动作，并把 evidence refs 写入 canonical state / decision trace。
- 保持 `mcp-project-memory` 作为 workflow 状态真源，保持 `mcp-enzyme-design-knowledge` 作为后续 curated knowledge 层。
- 为外部 provider/API 适配保留可替换边界，并提供假实现支持离线测试。
- 明确 `pubmed-mcp`、`arxiv-mcp` 一类组件若被采用，应作为 provider / ingestion connector 落在 `mcp-bio-research` 之下，并可通过 inspect 后的 detail contract 以 provider-aware 形式受控暴露；但它们属于后续扩展，不在当前 change 的实现范围内。
- 尽可能把当前 `docs/API` 中已整理的来源纳入 provider registry，让模型在 research 域内有更强的信息源选择空间。
- 允许 `mcp-bio-research` 在 research 域内通过 bounded LLM/sub-agent 进行 query decomposition、provider planning 和结果融合。

**Non-Goals:**
- 不在本变更中实现 enzyme design 知识审核、规则沉淀或 `enzyme://knowledge/...` 长期知识资源。
- 不把外部 research 服务变成另一个项目状态数据库，也不让它持有 agent workflow 状态。
- 不在本变更中实现结构 workbench UI、iframe 集成或复杂人工标注交互。
- 不绕过 `add-host-capability-discovery`，把 bio research 的全量工具契约直接常驻注入 agent 上下文。
- 不设计成 MCP server 之间直接互相调用；research evidence 到 curated knowledge 的沉淀应由 Host、skill 或独立 curation workflow 编排。
- 不让 `mcp-bio-research` 内部的 LLM/sub-agent 升级为 Host 级 workflow planner；其职责只限于 research 域内的 source selection、query planning、routing 和 fusion。

## Decisions

### 1. `mcp-bio-research` 作为独立 Python MCP app 落在 `apps/`

`mcp-bio-research` 将作为一个新的 Python app 放在 `apps/` 下，复用仓库当前对 MCP Python SDK、`uv` workspace 和测试布局的既有模式，而不是额外引入 Node app 或把 research 能力塞进 Host runtime。

这样做的原因是：

- 当前 monorepo 的 MCP server 主体都在 Python 侧，维护与测试路径一致。
- research 能力本身是外部 API 聚合与结构化抽取，更接近 MCP service，而不是 Host 内部实现细节。
- 独立 app 可以被 Host、CLI、未来的 MCP Apps 和批处理脚本复用，而不是绑死在某一个宿主入口。

备选方案：

- 直接在 `packages/enzyme-host-runtime` 中内嵌 research client。
- 做成第二个 Node service，与 `pi-ai-sidecar` 同类管理。

不采用的原因：

- 内嵌 runtime 会模糊 Host 与 MCP server 的边界，并让其它入口难以复用。
- Node 版本不会带来显著收益，但会引入第二套生态和测试复杂度。

### 2. Research 结果采用“可引用 evidence snapshot”，而不是仅做实时透传

如果 research server 只返回实时搜索结果文本，Host 无法稳定复用这些结果，也很难在 decision trace 中追溯某次决策到底引用了哪份 evidence。因此首版返回结果必须带稳定 `evidence_ref` 和可再次读取的 `resource_uri`。

实现上采用“read-through evidence snapshot”模型：

- tools 负责调用外部 provider，并把命中的 paper/structure/annotation 规范化为 evidence 对象。
- 每个命中对象生成稳定 `evidence_ref`。
- `resources/read` 通过 `enzyme://research/...` URI 读取该 evidence 的规范化快照。

这里的 snapshot 只服务于 research evidence 可追溯性，不承担 workflow 状态真源职责。Host 仍只在 `mcp-project-memory` 中持久化 `evidence_refs`、query context 和 decision trace。

备选方案：

- tools 只返回自由文本摘要，不生成 evidence refs。
- resources 直接按外部 provider id 实时 fetch，不保留快照语义。

不采用的原因：

- 只返回文本会让 evidence 无法被后续状态与测试稳定引用。
- 纯实时 fetch 会让同一个 URI 在时间上漂移，不利于审计与回放。

### 3. 默认按 evidence 类型组织 research 语义，但 inspect 后允许 provider-aware detail contract

默认 tool surface 按调用意图分成三类：

- `search_literature`
- `search_structure_records`
- `query_biological_annotations`

这样做的目的是让 summary 层保持紧凑，让 Host/agent 默认先表达“我要什么 evidence”，而不是一上来面对十几个 provider-specific tools。

但考虑到本变更希望接入尽可能多的 provider，并允许模型更主动地选择来源，detail contract 不必局限于这三个抽象工具。inspect 后可以按需暴露：

- provider-aware literature tools
- provider allowlist / preference controls
- source selection hints
- expert-only provider-specific surfaces

这样可以兼顾两件事：

- summary 层避免一开始就把所有 provider 工具塞进上下文
- detail 层在需要时仍保留 provider 差异与能力上限

备选方案：

- 完全只暴露 `search_literature`、`search_structure_records`、`query_biological_annotations` 三个高层工具。
- 从一开始就把 `search_pubmed`、`search_semantic_scholar`、`query_uniprot` 等所有 provider-specific tools 常驻暴露给 Host。

不采用的原因：

- 只保留高层语义会压扁 provider 差异，限制模型利用不同来源特点。
- 全量常驻暴露则会让上下文和 tool contract 膨胀过快。

### 3.5 `mcp-bio-research` 通过 capability discovery 对 agent 暴露，而不是直接全量暴露

`mcp-bio-research` 的实现要默认接入 `add-host-capability-discovery` 提供的 Host registry / inspect 流程：

- summary 层只告诉 agent：这个 capability 适合查文献、结构、注释 evidence，会返回 `evidence_ref`、摘要和 `resource_uri`；
- detail contract 才展开默认 research tools、provider-aware expert tools、routing knobs 及相关 prompts/resources 的压缩版调用说明；
- Host 在当前 decision scope 内临时暴露 detail contract，scope 结束后恢复 summary-only。

这样做的原因是：

- bio research 很容易演化成一个内部封装许多数据源的“胖 MCP”，最需要 capability discovery 的上下文裁剪；
- 这让 `mcp-bio-research` 可以成为 capability discovery 的首批验证对象，而不是后续再返工接入。

备选方案：

- 先直接把 bio research 的完整 schema 暴露给 agent，等 discovery 机制完成后再回头收敛。

不采用的原因：

- 会造成两次接口形态切换；
- 容易把 provider/source 级复杂度过早暴露给 LLM。

### 4. 明确区分 external research evidence 与 curated knowledge

`mcp-bio-research` 返回的对象统一标记为 external/unreviewed evidence，并且不暴露 `enzyme://knowledge/...` 资源。Host 在状态里记录这些对象时，也只应写入 `evidence_refs` 或 observations，不得直接当作 `knowledge_refs`。

这样做的原因是：

- Phase 2 的 research 检索与 Phase 3 的知识沉淀是不同职责。
- 直接把外部检索结果提升为知识对象，会绕过审核边界并污染长期上下文。
- `mcp-enzyme-design-knowledge` 后续可以消费这些 evidence 作为审核输入，但不应在本变更里被合并。

### 5. Host integration 通过“capability inspect + research action + observation/evidence refs”接入，而不是新建旁路状态模型

`host-agent-planning` 的变更限定为两层：

- agent 先通过 Host capability discovery 判断并 inspect `mcp-bio-research`；
- 然后再选择一种 research action，请求外部文献/结构/注释 evidence；
- runtime 把 research 结果整形成 observations 和 `evidence_refs`，写回 canonical state / decision trace。

这意味着 research 结果进入 Host 的路径与其它受控工具动作一致，只是输出更偏 evidence/observation，而不是 run manifest 或 HPC artifact。这样可以最大化复用现有 agent workflow、UI 恢复和 decision logging 语义。

备选方案：

- 在 agent state 中新增一套仅供 research 使用的私有缓存模型。
- 让 Web Host/CLI 直接调用 research server，并在前端或 CLI 本地维护结果。

不采用的原因：

- 私有缓存会产生第二份状态副本。
- 前端/CLI 直连会绕过共享 runtime 和 canonical trace，破坏跨入口一致性。

### 6. 使用广覆盖 provider registry + adapter + fake provider 组织外部依赖

`mcp-bio-research` 需要对接多个外部来源，因此不应把真实 API 调用写死在 server 逻辑里。服务内部采用 provider registry + adapter 层：

- literature adapter
- structure adapter
- annotation adapter
- fake adapter for tests

配置声明启用哪些 provider、base URL、timeouts、可选 API keys env 名称、默认 routing policy 和 planner 开关。测试默认使用 fake adapter，以保证单元测试和 contract 测试无需外网即可运行。

对于外部 literature provider，推荐进一步区分：

- PubMed / OpenAlex / Crossref：优先作为生物文献与学术元数据主来源
- arXiv：优先作为算法、模型、预印本和方法学补充来源
- Europe PMC / bioRxiv / medRxiv / Semantic Scholar：作为补充 literature 覆盖面
- `pubmed-mcp`、`arxiv-mcp` 若被采用，应通过 adapter 方式被 `mcp-bio-research` 吸收，并可在 inspect 后以 provider-aware surface 被受控使用；当前 change 先不实现这两个外部 MCP 的接入，仅保留接口与扩展位
- `rcsb_pdb`、`uniprot`、`interpro` 这类来源分别进入 structure / annotation provider 集合

当前目标不再是“最小 provider 集”，而是尽可能把仓库里已整理的 `docs/API` 来源纳入 provider registry；实现节奏可以分批，但设计上要把“广覆盖 provider + 统一 evidence envelope”作为首选方向。对于 `pubmed-mcp`、`arxiv-mcp`，本次只明确未来接入方式，不作为当前实现交付项。

### 6.5 在 research 域内允许 bounded LLM/sub-agent planner

考虑到不同 provider 的查询参数、覆盖面、召回质量和成本都不同，单靠静态规则很难在所有场景下取得理想效果。因此 `mcp-bio-research` 可以在 research 域内使用 bounded LLM/sub-agent planner，用于：

- query decomposition
- provider selection
- provider ordering / fan-out
- provider-specific query rewriting
- result fusion / reranking 辅助

但这层 planner 必须受以下约束：

- 不决定 episode 的全局业务下一步
- 不持有 canonical workflow state
- 不直接写入长期知识对象
- 不跨 MCP 承担 Host 级 orchestration
- 失败时可以退回 deterministic routing policy
- 最好记录 routing reason、selected providers 或等价审计摘要

### 7. Research evidence 到 curated knowledge 的交接由上层 workflow 编排，而不是 MCP 互调

`mcp-bio-research` 与 `mcp-enzyme-design-knowledge` 的关系应是上下游，而不是直接互调。推荐链路如下：

```text
external sources
  -> provider adapters / ingestion connectors
  -> mcp-bio-research
  -> evidence_ref
  -> Host / skill / curation workflow
  -> mcp-enzyme-design-knowledge
  -> knowledge_ref
```

Phase 2 范围内只需要保证：

- research evidence 可以稳定生成 `evidence_ref`
- Host 可以把 `evidence_refs` 写入 canonical state / decision trace
- evidence 内容保留 `source_refs`、`review_status=unreviewed` 和 query context
- provider registry、routing policy 和 bounded planner 仅服务于 research 域，不越权进入 knowledge 写入或 Host workflow 真源

Phase 3 再由单独的 knowledge curation workflow / skill 负责：

- 从 `evidence_refs` 生成 heuristic / case / protocol draft
- 做筛选、冲突处理和审核
- 在通过审核后调用 `mcp-enzyme-design-knowledge` 生成正式 `knowledge_ref`

这样可以避免：

- `mcp-bio-research` 偷偷演化成长期知识库
- `mcp-enzyme-design-knowledge` 反过来承担在线 research 抓取
- 通过 MCP 互调把调度责任下沉到能力层

## Risks / Trade-offs

- [外部 research provider 结果不稳定或有速率限制] → 通过 adapter 层统一错误映射、超时和 fake provider，减少测试与主逻辑耦合。
- [evidence snapshot 设计不当会滑向“第二个状态真源”] → 限制 snapshot 只承载 research evidence 内容与 source provenance；workflow 状态仍只写 `mcp-project-memory`。
- [tool surface 过细会把 provider 细节过早泄漏到 Host] → 通过 capability discovery 的 summary/detail 两层控制曝光；默认 summary 紧凑，detail 才展开 provider-aware surface。
- [若绕过 capability discovery 直接暴露完整 schema，会把 bio research 变成新的上下文膨胀来源] → 以 summary/detail 两层形式接入，并把 detail contract 绑定到短生命周期 decision scope。
- [Host 直接消费外部 research 结果可能误伤 knowledge 边界] → 在 spec 和返回字段中强制 `external_research` / `unreviewed` 标记，并要求 Host 只记录 `evidence_refs`。
- [不同 source 的元数据结构差异大] → 先定义最小统一 evidence envelope，保留 provider-specific payload 在扩展字段中。
- [MCP 内部 planner 变成第二个 Host] → 约束其职责只在 research 域内做 routing/fusion，并增加 fallback 与审计摘要。

## Migration Plan

1. 在 `apps/` 下新增 `mcp-bio-research` 项目，搭建基础 server、配置模型和 fake provider。
2. 在 `add-host-capability-discovery` 提供的 registry/inspect 机制上，为 `mcp-bio-research` 增加 capability summary 与 detail contract 接入。
3. 建立广覆盖 provider registry，优先覆盖 `docs/API` 中现有来源，并为 `pubmed-mcp`、`arxiv-mcp` 预留后续接入方式说明。
4. 实现 evidence envelope、stable resource URI、默认 high-level tools 与 inspect 后的 provider-aware detail contract。
5. 在 research 域内增加 routing policy，并评估/实现 bounded LLM or sub-agent planner 与 fallback。
6. 在 `packages/enzyme-host-runtime` 中增加 inspect 后的 research action 执行与结果映射，写回 observations / `evidence_refs`。
7. 增加单元测试、MCP contract 测试和 runtime 集成测试，验证 Host 通过 discovery 机制消费 research evidence，provider-aware surface 受 inspect 控制，且不会把结果误当作 curated knowledge。
8. 更新开发文档与示例工作区，说明 provider registry、planner 约束、capability summary/detail 接入、`pubmed-mcp`/`arxiv-mcp` 的后续扩展位和后续 knowledge 集成边界。

回滚策略：

- 关闭或移除 `mcp-bio-research` 接入，Host 继续运行既有 workflow，但不再自动请求 research evidence。
- 已记录在 decision trace 中的 `evidence_refs` 保留为历史引用，不要求同步删除。

## Open Questions

- evidence snapshot 应落在 server 自身缓存目录还是项目工作区的可复用 artifact 路径，需要在实现时结合现有 workspace 结构收敛。
- literature / structure / annotation 三类 evidence 的统一排序字段最终采用 `score`、`confidence`，还是同时保留两者，需要在 adapter 抽象中明确。
- Web Host/CLI 首版是否要直接显示 research evidence 摘要，还是先只通过 decision trace / verbose 输出暴露引用，取决于实现阶段的 UI 范围控制。
- bio research 的 summary override 最终放在 Host registry 配置侧还是由 server 自带元数据提供，需要跟 capability discovery 的实现一并收敛。
- inspect 后的 provider-aware detail contract 应暴露到什么粒度，需要在“模型自由度”和“上下文可控性”之间进一步收敛。
- `pubmed-mcp`、`arxiv-mcp` 将来接入时，是仅作为内部 adapter，还是在 inspect 后暴露为 expert surface 的一部分，需要等当前 provider registry 落地后再收敛。
