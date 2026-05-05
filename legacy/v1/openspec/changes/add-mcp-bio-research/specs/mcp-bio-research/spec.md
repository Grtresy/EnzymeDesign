## ADDED Requirements

### Requirement: Bio research server exposes stable research evidence resources
系统 MUST 通过稳定的 `enzyme://research/...` URI 暴露外部研究证据对象，而不是只返回一次性文本结果。

最小资源集合至少包括：

- `enzyme://research/paper/{paper_ref}`
- `enzyme://research/structure/{structure_ref}`
- `enzyme://research/annotation/{annotation_ref}`

每个资源至少必须包含：

- 稳定的 `evidence_ref` 或等价 evidence id
- `source_system`
- 外部来源记录 id
- 标题或对象名称
- 结构化摘要或结构化注释内容
- `source_refs`
- `fetched_at`
- `query_context_summary`

#### Scenario: Listed paper evidence can be read back through a stable resource URI
- **WHEN** 调用方通过 research tool 命中了某篇论文并收到 `paper_ref`
- **THEN** `resources/read` 可以通过 `enzyme://research/paper/{paper_ref}` 读取该论文的规范化 evidence 内容
- **THEN** 返回内容包含 `source_system`、来源记录 id、摘要、`source_refs` 和 `query_context_summary`

### Requirement: Bio research tools return structured and filterable evidence
系统 MUST 提供面向 enzyme design 场景的结构化 research tools，并允许调用方按目标范围过滤检索。

最小 tool surface 至少包括：

- `search_literature`
- `search_structure_records`
- `query_biological_annotations`

这些 tools 的输入至少必须支持以下字段中的一个或多个：

- enzyme family / protein name
- substrate or ligand context
- reaction or function keywords
- organism or taxonomy scope
- result limit / ranking controls

每个 tool 的结果至少必须包含：

- `evidence_ref`
- `resource_uri`
- `evidence_type`
- 简要结论或摘要
- `source_system`
- `source_refs`
- `score`、`confidence` 或等价排序字段
- 可选的 `provider` 或等价来源适配标识，但不得要求 Host 直接依赖 provider-specific tool 名称

#### Scenario: Literature search returns scoped paper evidence instead of free text
- **WHEN** 调用方使用 enzyme family、substrate 和 reaction 关键词调用 `search_literature`
- **THEN** 系统返回结构化论文 evidence 列表，而不是仅返回不可追溯的自由文本段落
- **THEN** 每条结果都带有 `evidence_ref`、`resource_uri`、`source_system`、摘要和排序字段

#### Scenario: Structure search returns PDB-scoped evidence
- **WHEN** 调用方基于某个蛋白名称或功能关键词调用 `search_structure_records`
- **THEN** 系统返回结构化的结构命中结果，包括 PDB/RCSB 或等价来源标识
- **THEN** 每条结果都可以通过稳定的 structure resource URI 再次读取

### Requirement: Bio research capability supports a broad provider registry with provider-aware detail
系统 MUST 允许 `mcp-bio-research` 在统一 evidence envelope 之下接入广覆盖 provider registry，优先覆盖当前仓库已整理的 research API 来源。`pubmed-mcp`、`arxiv-mcp` 这类外部 MCP 能力 MAY 作为后续扩展接入，但不属于当前 change 的必须实现范围。

该能力至少必须满足：

- summary 层不要求一次性把所有 provider-specific tools 常驻暴露给 Host
- inspect 后的 detail contract 可以暴露 provider-aware tools、provider allowlist / preference controls 或等价 expert surface
- 不同 provider 的原始差异最终仍需归一化到统一 evidence envelope 和 `evidence_ref`

#### Scenario: Agent inspects bio research and sees provider-aware expert surface
- **WHEN** Host 或 agent inspect `mcp-bio-research` 的 detail contract
- **THEN** detail contract 可包含 provider-aware tools 或 provider controls，而不仅限于最小高层 research tools
- **THEN** 这些能力只在 inspect 后的当前决策窗口内可见，而不会默认常驻初始上下文

### Requirement: Bio research evidence remains bounded to external research context
系统 MUST 将 research 结果标记为外部、未审核 evidence，而不是长期知识对象或 canonical workflow state。

该边界至少必须满足：

- research 结果带有 `evidence_kind=external_research` 或等价标记
- research 结果带有 `review_status=unreviewed` 或等价审核状态
- 服务不得把检索结果直接暴露为 `enzyme://knowledge/...` 资源
- 服务不得提供生成 `knowledge_ref` 或写入 curated knowledge 的 tool surface
- 服务不得要求 Host 复制整段原文才能保留引用关系

#### Scenario: External research result is not promoted into curated knowledge
- **WHEN** 调用方读取某条由 `mcp-bio-research` 返回的论文或注释 evidence
- **THEN** 该结果被标识为外部 research evidence，而不是 enzyme design knowledge object
- **THEN** Host 可以记录它的 `evidence_ref`，但不会把它误当成已审核的长期知识资源

### Requirement: Bio research server supports provider adapters without breaking unified evidence semantics
系统 MAY 在服务内部通过 provider adapter 或 ingestion connector 对接 `pubmed-mcp`、`arxiv-mcp` 或等价外部来源，并 MAY 在 inspect 后以 provider-aware 形式暴露 expert surface；但 MUST 保持统一的 evidence semantics 和可归一化输出。对于 `pubmed-mcp`、`arxiv-mcp`，当前 change 只要求预留兼容边界，不要求完成实际接入。

该边界至少必须满足：

- Host 至少始终可以通过统一的 `search_literature`、`search_structure_records`、`query_biological_annotations` 使用 research capability
- provider-specific 集成细节被收敛到 server 的 adapter / provider registry 层
- 若 inspect 后暴露 provider-aware tool surface，返回结果中的 provider 信息仍须能映射回统一 evidence envelope，而不是形成另一套不兼容结果模型

#### Scenario: Host consumes literature evidence without depending on pubmed-specific tool names
- **WHEN** `mcp-bio-research` 内部通过 `pubmed-mcp`、`arxiv-mcp` 或等价来源完成 literature 检索
- **THEN** Host 仍通过统一的 `search_literature` surface 获取结果
- **THEN** 返回内容可包含来源 provenance，但不会要求 Host 直接改为调用 provider-specific MCP

#### Scenario: Current implementation can ship without pubmed-mcp and arxiv-mcp adapters
- **WHEN** 当前 change 的实现仅覆盖仓库内已整理的 research API provider，而尚未接入 `pubmed-mcp`、`arxiv-mcp`
- **THEN** `mcp-bio-research` 仍满足当前 change 的必需实现范围
- **THEN** 后续新增这两个 adapter 时，不需要改变统一 evidence envelope 的核心语义

### Requirement: Bio research server may use bounded internal planning for provider routing
系统 MAY 在 research 域内使用 LLM 或 sub-agent 进行 provider planning、query decomposition、query rewriting 和 result fusion，但 MUST 把这类规划限制在 research 域内，而不是升级为 Host 级 workflow planner。

该边界至少必须满足：

- internal planning 不直接写入长期知识对象
- internal planning 不持有 canonical workflow state
- internal planning 不替 Host 决定 episode 的全局业务下一步
- 服务在 planner 不可用时可以退回 deterministic routing policy 或等价 fallback
- 结果或调试信息中至少能体现 selected providers、routing summary 或等价审计摘要

#### Scenario: Server uses planner to route one research request across multiple providers
- **WHEN** 调用方发起一次 literature 检索，且 server 开启 bounded planner
- **THEN** server 可以先做 query decomposition 与 provider selection，再调用多个 provider
- **THEN** 返回结果仍归一化为统一 evidence 列表，并带有足够的 provenance 或 routing 摘要供审计

### Requirement: Bio research server exposes reusable prompts for evidence summarization
系统 MUST 暴露面向 research evidence 的 prompts，使 Host 或其它调用方能够基于已命中的 evidence refs 生成一致的摘要上下文。

最小 prompt surface 至少包括：

- 文献摘要 prompt
- 结构命中比较 prompt
- 注释结果归纳 prompt

这些 prompts 至少必须支持：

- 输入 evidence refs
- 输入查询目标或设计问题
- 输出建议的摘要结构或分析维度

#### Scenario: Host requests a literature summary prompt for selected papers
- **WHEN** 调用方已经拿到一组 paper evidence refs，并请求文献摘要 prompt
- **THEN** research server 返回面向这些 evidence refs 的结构化 prompt 模板
- **THEN** 该 prompt 明确包含查询目标或设计问题，而不是通用无上下文模板

### Requirement: Bio research results are reusable in episode state and decision trace
系统 MUST 返回可被 Host、runtime 和 `mcp-project-memory` 持久化引用的 evidence 标识，而不是要求调用方内嵌整段 research 正文。

每条 research 结果至少必须包含：

- `evidence_ref`
- `resource_uri`
- `query_context_summary`
- `source_refs`

#### Scenario: Host records research evidence refs alongside a planning decision
- **WHEN** agent 使用 research result 支持某次 planning 或 action selection
- **THEN** `mcp-bio-research` 的响应中包含稳定 `evidence_ref` 与 `resource_uri`
- **THEN** Host 可以把这些引用写入 episode state 或 decision trace，而不需要复制整段论文摘要或注释正文

### Requirement: Bio research capability is onboarded through Host capability discovery
系统 MUST 允许 `mcp-bio-research` 通过 Host capability discovery 机制被 agent 发现和按需展开，而不是默认在每轮初始上下文中暴露其完整 tool schema。

该能力至少必须支持：

- 提供可用于生成或覆盖 capability summary 的用途说明
- 提供可用于 inspect detail contract 的稳定 capability handle
- 在 detail contract 中暴露 research 相关 tools/resources/prompts 的压缩版调用说明，而不是原始文档全文

#### Scenario: Agent sees a lightweight bio research summary before inspecting details
- **WHEN** Host 为 agent 准备可见的 MCP capability registry
- **THEN** `mcp-bio-research` 先以轻量 summary 进入 registry，说明适用场景、返回类型和使用提示
- **THEN** 只有在 agent 或 runtime 显式 inspect 该 capability 后，bio research 的具体 tools/resources/prompts 才会进入当前决策窗口
