## Why

当前 Host agent 已经具备持续决策、项目状态持久化和 LLM sidecar 能力，但缺少稳定的外部生物研究证据入口。若继续让 agent 只依赖用户输入、临时 prompt 上下文或未结构化的外部检索结果，就无法为后续的设计约束、案例对比和知识沉淀提供可追溯的 research evidence。

与此同时，如果直接把 `mcp-bio-research` 的完整 tools/resources/prompts 契约一次性暴露给 agent，又会把刚刚识别出的 MCP 上下文膨胀问题重新带回来。因此该 change 需要明确依赖并接入 `add-host-capability-discovery`：先让 Host 暴露 bio research 的 capability summary，再按需展开 detail contract。

本变更的定位是 Phase 2 的 research evidence 能力，而不是 Phase 3 的长期知识沉淀能力。与此同时，考虑到当前仓库已经整理了较多外部 API 资料，且 research 请求在不同来源上的参数形态差异很大，本变更不再仅追求“最小 provider 集”，而是希望优先把 `docs/API` 中现有来源纳入 `mcp-bio-research` 的 provider registry，由 server 内部完成 planning、路由和归一化。`pubmed-mcp`、`arxiv-mcp` 保留为后续可选扩展，但不在当前 change 的实现范围内。

## What Changes

- 新增一个独立的 `mcp-bio-research` MCP server，用于统一封装当前 `docs/API` 下已整理来源，并完成结构化 evidence 抽取。
- 为 research server 定义两层 research surface：summary 层保持轻量 capability 说明；detail contract 在 inspect 后暴露更细粒度的 provider-aware tools、routing 选项或 expert surface。
- 将 `mcp-bio-research` 作为首批接入 Host capability discovery 的 MCP 之一：默认只向 agent 暴露 summary，只有在 agent 判断需要该能力时才按需展开 detail contract。
- 让 research 结果以“临时、可追溯的 evidence”形式返回，而不是直接提升为长期知识对象；为后续 Phase 3 的 `mcp-enzyme-design-knowledge` curated knowledge 流程提供上游输入。
- 明确 research 结果至少携带来源标识、摘要、筛选条件和可持久化引用，便于 Host runtime 与 `mcp-project-memory` 把它们写入 decision trace 或 episode state。
- 允许 `mcp-bio-research` 在 research 域内使用 bounded LLM/sub-agent 做 provider planning、query decomposition、routing 和结果融合，但不负责长期知识审核、项目状态真源或 Host 级 workflow 编排。

## Capabilities

### New Capabilities
- `mcp-bio-research`: 提供面向 enzyme design 场景的外部研究检索、结构化证据抽取和稳定资源引用能力。

### Modified Capabilities
- `host-agent-planning`: 扩展 agent workflow 对 research evidence 的消费边界，使其能够基于结构化外部研究结果形成或修订下一步决策。

## Impact

- 在 `apps/` 下新增 `mcp-bio-research` 服务项目及其测试。
- `packages/enzyme-host-runtime` 需要在 `add-host-capability-discovery` 提供的 capability registry / inspect 机制之上接入 bio research 的 summary 与 detail contract，并支持 inspect 后的 provider-aware research surface 消费。
- Web Host / CLI 可能需要补充 research evidence 摘要或引用展示，但不改变其作为 Host 入口的职责。
- 后续 `mcp-enzyme-design-knowledge` 可以复用该 server 的输出作为 reviewed knowledge 的上游输入，而不是直接耦合外部检索；真正的 `evidence_ref -> knowledge_ref` 沉淀应由 Phase 3 的 Host / skill / curation workflow 编排。
- 依赖层面将引入广覆盖的 provider registry、provider adapter/API 适配、可选 sampling / planner 支持以及本地测试假实现。`pubmed-mcp`、`arxiv-mcp` 的接入策略在本次设计中保留说明，但当前实现先不落地。
