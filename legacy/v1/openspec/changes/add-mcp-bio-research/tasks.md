## 1. Research Server Scaffold

- [ ] 1.1 在 `apps/` 下新增 `mcp-bio-research` 项目，补齐 `pyproject.toml`、`src/` 布局、README 与测试目录
- [ ] 1.2 定义 research server 的配置模型、provider adapter 接口和 fake provider，实现离线可跑的基础服务入口
- [ ] 1.2.1 建立广覆盖 provider registry，优先覆盖当前 `docs/API` 中已整理来源，并为 `pubmed-mcp`、`arxiv-mcp` 预留后续接入策略
- [ ] 1.2.2 为每个 provider 定义 capability matrix、query translation 策略和 fallback 行为
- [ ] 1.3 为 `paper`、`structure`、`annotation` evidence 定义统一 envelope、`evidence_ref` 生成规则和稳定 resource URI

## 2. Capability Discovery Onboarding

- [ ] 2.1 依赖 `add-host-capability-discovery` 的 registry / inspect 机制，为 `mcp-bio-research` 提供 capability summary 所需的元数据或 override 配置
- [ ] 2.2 定义 bio research 的 detail contract 形态，确保只在 inspect 后向当前 decision scope 暴露 provider-aware tools/resources/prompts 或 routing controls
- [ ] 2.3 增加回归保护，确保 `mcp-bio-research` 不会默认把全量 schema 常驻注入 agent 上下文

## 3. MCP Research Surface

- [ ] 3.1 实现 `search_literature` tool，支持 enzyme family / substrate / reaction / organism 等范围过滤并返回结构化 paper evidence
- [ ] 3.2 实现 `search_structure_records` 和 `query_biological_annotations` tools，返回结构化 structure / annotation evidence
- [ ] 3.3 实现 `enzyme://research/paper/{ref}`、`enzyme://research/structure/{ref}`、`enzyme://research/annotation/{ref}` 的 `resources/read`
- [ ] 3.4 实现面向 evidence refs 的 research prompt surface，覆盖文献摘要、结构对比或注释归纳场景
- [ ] 3.5 设计并实现 provider-aware expert surface，使模型在 inspect 后可以受控地选择来源或设置 provider 偏好
- [ ] 3.6 实现 query translation、provider fan-out、dedupe / merge 和统一排序逻辑

## 4. Host Workflow Integration

- [ ] 4.1 在 `packages/enzyme-host-runtime` 中增加经 capability inspect 触发的 research action 类型化表示和 runtime 执行入口
- [ ] 4.2 将 `mcp-bio-research` 的结果映射为 observations、`evidence_refs` 和查询上下文摘要，并写回 canonical agent state / decision trace
- [ ] 4.3 确保 Host 只把这些结果视为 external research evidence，而不是直接写成 `knowledge_refs` 或长期知识对象
- [ ] 4.4 明确 Host 与 `mcp-bio-research` 的分工：Host 保留 workflow 控制权，`mcp-bio-research` 只负责 research 域内 planning / routing / fusion

## 5. Verification

- [ ] 5.1 为 `mcp-bio-research` 增加 server/tool/resource 测试，覆盖结构化返回、范围过滤、稳定 evidence refs 和错误映射
- [ ] 5.2 为 Host runtime 增加研究动作集成测试，验证 agent 可以先 inspect bio research capability，再检索 evidence 并修订 working plan 或 selected action
- [ ] 5.3 增加回归测试，验证 external research evidence 进入 decision trace 时不会被误提升为 curated knowledge
- [ ] 5.4 增加 capability discovery 相关测试，验证 bio research detail contract 只在 inspect 后的当前 decision scope 可见
- [ ] 5.5 增加 provider routing / planner 测试，验证 planner 只在 research 域内工作，且 fallback 与 audit 摘要可用

## 6. Documentation

- [ ] 6.1 更新仓库开发文档，说明 `mcp-bio-research` 的职责边界、capability discovery 接入方式、provider registry、bounded planner 约束、fake provider 和本地调试命令
- [ ] 6.2 更新示例工作区或 playground 文档，说明如何在 Host workflow 中通过 summary -> inspect -> research action 启用 research evidence 流程
- [ ] 6.3 明确记录与 Phase 3 `mcp-enzyme-design-knowledge` 和 knowledge curation workflow / skill 的边界：本 change 只产出 `evidence_ref`，不负责生成 `knowledge_ref`
- [ ] 6.4 在设计和开发文档中明确标注：`pubmed-mcp`、`arxiv-mcp` 属于未来扩展位，本次 change 先不实现
