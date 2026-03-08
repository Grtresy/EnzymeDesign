# mcp-enzyme-design-knowledge

## ADDED Requirements

### Requirement: Knowledge server exposes curated enzyme design resources
系统 MUST 以稳定的资源标识暴露经整理的酶设计知识对象，而不是把原始外部检索结果直接作为长期知识库内容。

最小资源集合至少包括：

- `enzyme://knowledge/enzyme-design/heuristics/{category}`
- `enzyme://knowledge/enzyme-design/cases/{case_id}`
- `enzyme://knowledge/enzyme-design/protocols/{protocol_name}`

资源内容至少必须能够表达：

- 稳定的知识对象 id
- 适用范围或分类
- 结构化正文内容
- `confidence`
- `source_refs`
- `last_reviewed_at` 或等价审核时间

#### Scenario: Host can read curated heuristic resources
- **WHEN** knowledge server 中已经存在某个酶设计启发式类别的知识条目
- **THEN** `resources/list` 返回对应的稳定 `enzyme://knowledge/enzyme-design/heuristics/{category}` URI
- **THEN** `resources/read` 返回的内容包含知识条目 id、推荐内容、confidence 和 source_refs

### Requirement: Knowledge tools return scoped and traceable results
系统 MUST 提供面向 enzyme design 场景的结构化知识检索 tools，并返回可被 Host 持久化引用的知识对象。

最小 tool surface 至少包括：

- `query_design_heuristics`
- `find_similar_cases`
- `get_enzyme_design_constraints`

每个 tool 的结果至少必须包含：

- 匹配到的知识对象 id
- 简要结论或推荐
- `confidence`
- `source_refs`
- 可选的适用条件、排除条件和相似度/排序分数

#### Scenario: Constraint query returns evidence-backed recommendations
- **WHEN** 调用方基于某个酶设计目标、底物特征或结构上下文调用 `get_enzyme_design_constraints`
- **THEN** 系统返回结构化约束建议列表，而不是仅返回自由文本段落
- **THEN** 每条建议都带有可追溯的 `source_refs` 与 `confidence`

### Requirement: Knowledge scope is bounded to enzyme design and reviewed provenance
系统 MUST 将知识库范围限制在 enzyme design 相关的启发式、案例、协议和约束建议，不得把未审核的通用生物信息检索结果直接提升为长期知识对象。

系统至少必须支持以下边界控制：

- 区分“外部检索结果”和“内部知识对象”
- 拒绝缺少来源引用的知识入库
- 记录知识对象的审核状态或审核时间
- 允许调用方按酶家族、底物类型、反应类别或等价维度做范围过滤

#### Scenario: Unreviewed external snippets are not promoted into curated knowledge
- **WHEN** 调用方尝试把没有明确来源引用或未经审核的外部文本片段写入酶设计知识库
- **THEN** 系统拒绝将该内容作为长期知识对象暴露
- **THEN** Host 仍可将其视为临时 research evidence，而不是稳定 knowledge resource

### Requirement: Knowledge results are reusable in episode state and decision trace
系统 MUST 返回稳定的知识引用，使 Host、runtime 和 `mcp-project-memory` 能把知识消费结果写入 episode 状态与决策记录。

最小可复用引用至少包括：

- `knowledge_ref` 或等价稳定资源 URI
- 被命中的知识对象 id
- tool 查询上下文摘要

#### Scenario: Host persists knowledge references alongside a planning decision
- **WHEN** agent 使用某条酶设计启发式或参考案例形成下一步规划
- **THEN** knowledge server 的响应中包含稳定 `knowledge_ref` 或等价资源定位信息
- **THEN** Host 可以将该引用写入 episode state 或 decision trace，而不需要复制整段知识正文
