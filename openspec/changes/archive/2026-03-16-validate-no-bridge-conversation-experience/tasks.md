## 1. Timeline View Model

- [x] 1.1 在 `apps/enzyme-web-host` 中整理一个基于 canonical snapshot 的 timeline view model，把 `plain_language_explanation`、`progress_summary`、`selected_action`、`pending_interrupts`、`approval_gates`、`runs` 和 `workflow_audit` 统一映射成可渲染的时间线项
- [x] 1.2 为时间线项补齐稳定的引用信息和类型区分，确保 gate、interrupt、run、selected action 等卡片都能追溯到对应的 canonical 对象
- [x] 1.3 如果现有 snapshot 字段不足以稳定生成时间线，在 `packages/enzyme-host-runtime` 中补最小必要的展示辅助字段，但不新增新的状态真源

## 2. Web Host Main Experience

- [x] 2.1 重组 `apps/enzyme-web-host` 首页主布局，让 conversation-style timeline 成为主操作区，而不是让分散的状态面板继续占据主视图
- [x] 2.2 把 pending gate、pending interrupt、selected action 和 recent run result 改造成嵌在时间线中的消息卡片
- [x] 2.3 把 approval、reject、feedback、continue、execute 等关键动作尽量嵌入对应卡片附近，减少“读一处、操作另一处”的割裂感
- [x] 2.4 保留 Trace / Debug / Raw State / Report 区域，但把它们明确降为辅助检查区，避免抢占主叙事区域
- [x] 2.5 为未来 `mcp-structure-workbench` 预留宿主接缝，例如可嵌入 richer app block 的区域、可表达“打开结构工作台”的卡片入口，以及可向下传递 project / episode / annotations 上下文的视图模型字段，但不提前实现 workbench 本体

## 3. No-Bridge Validation Guardrails

- [x] 3.1 确保首轮验证不新增自由文本 chat composer，也不引入新的浏览器侧 conversation state 持久化
- [x] 3.2 确保时间线刷新后可以仅凭共享 runtime 返回的 canonical snapshot 重建，不依赖额外 message 历史
- [x] 3.3 检查所有时间线里的交互动作仍然通过现有 runtime / HTTP 路由提交，而不是在前端私自推进 workflow

## 4. Verification

- [x] 4.1 为 Web Host 增加回归测试，覆盖 `awaiting_approval` 场景下的 narrative timeline 和 inline gate card 展示
- [x] 4.2 为 Web Host 增加回归测试，验证刷新页面后仍能从 canonical state 重建相同语义的主时间线
- [x] 4.3 为 Web Host 增加回归测试，验证 debug 信息仍然存在但不再占据主操作区域
- [x] 4.4 用现有 manual playground 走一轮真实 GLM + Web Host + HPC `fpocket` 体验，人工确认“无桥梁版本”已经能更自然地表达系统在做什么、为什么停下、下一步该做什么

## 5. Documentation

- [x] 5.1 更新 playground 或 Host 相关说明文档，明确这次验证的目标是“用现有 canonical state 验证更像对话的 Web 体验”，而不是实现新的 chat bridge
- [x] 5.2 用通俗语言记录这次验证想回答的核心问题、观察点和结论标准，方便后续决定是否进入 Phase 3 的对话桥梁层
