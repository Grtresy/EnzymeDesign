## ADDED Requirements

### Requirement: Host agent can request scoped bio research evidence as a workflow action
The system MUST 允许 host agent 在 workflow 中把外部 bio research 检索作为一种受控动作，而不是只在初始 prompt 中被动消费用户提供的背景信息。

该 research 动作至少必须能够表达：

- research 目标或问题陈述
- query terms 或结构化过滤条件
- 期望 evidence 类型（paper / structure / annotation）
- 结果数量或排序约束

runtime 在执行该动作后 MUST：

- 先通过 Host capability discovery 确认 `mcp-bio-research` 的 summary / detail contract，而不是假定该 MCP 的完整 tool schema 已常驻可见
- 调用 `mcp-bio-research` 而不是直接把外部 HTTP/API 调用硬编码到 agent prompt 中
- 将 research 结果整形成 observations 或等价 evidence 记录
- 把命中的 `evidence_ref`、`resource_uri` 和查询上下文摘要写回 canonical agent state 或 decision trace
- 允许 detail contract 在 inspect 后暴露 provider-aware controls，但 Host 仍通过受控的 research action 与 `mcp-bio-research` 交互，而不是直接接管 provider 级编排

#### Scenario: Agent searches literature before choosing a downstream tool action
- **WHEN** agent 判断当前目标缺少可靠的文献或结构背景，尚不足以直接选择下游预处理或 HPC 动作
- **THEN** workflow 可以先 inspect `mcp-bio-research` 的 detail contract，再生成一个 research action，请求其检索相关 literature 或结构 evidence
- **THEN** 检索结果以 observations 和 `evidence_ref` 的形式回写，供后续 action selection 使用

#### Scenario: Current workflow does not require pubmed-mcp or arxiv-mcp to exist
- **WHEN** 当前 change 的实现尚未接入 `pubmed-mcp`、`arxiv-mcp`
- **THEN** Host workflow 仍可通过 `mcp-bio-research` 的已实现 provider 获取 research evidence
- **THEN** 后续新增这两个 provider adapter 时，不要求改变 Host research action 的基本形态

### Requirement: Host agent keeps external research evidence distinct from curated knowledge
The system MUST 将外部 research evidence 与已审核的 enzyme design knowledge 明确区分，避免把一次性检索结果直接提升为长期知识真源。

当 agent 基于 research evidence 修订 working plan、selected action 或 decision trace 时，系统至少必须：

- 记录 `evidence_refs`
- 记录查询目标或查询上下文摘要
- 将这些结果视为 external research evidence，而不是 `knowledge_refs`
- 允许后续 `mcp-enzyme-design-knowledge` 单独复用这些 evidence 作为审核输入

#### Scenario: Agent revises the working plan based on external papers without creating new knowledge objects
- **WHEN** agent 读取若干篇外部论文 evidence 后决定调整约束、评估路径或下一步动作
- **THEN** decision trace 记录对应的 `evidence_refs` 和查询上下文
- **THEN** canonical agent state 不会把这些论文结果直接写成已审核的 enzyme design knowledge 条目
