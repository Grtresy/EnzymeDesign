## 1. Agent Workflow Foundation

- [x] 1.1 将 `packages/enzyme-host-runtime/planning/` 重构为持续决策型 agent workflow 模块，覆盖 graph state、decision nodes、feedback nodes 和 observation nodes
- [x] 1.2 将模型适配器从单纯 `draft_plan` 接口扩展为支持 candidate actions、selected action、clarification、approval request 和 observation summarization
- [x] 1.3 定义可恢复的 agent state / trace 模型，覆盖 `working_plan`、`selected_action`、`observations`、`human_feedback`、`approval_requests` 和 `termination_status`

## 2. Runtime Integration

- [x] 2.1 扩展 `HostRuntime`，暴露启动/恢复 workflow、提交反馈、推进下一轮决策、触发受控工具动作和读取 agent state 的服务方法
- [x] 2.2 调整 episode 范围持久化，从仅保存 planning revision 扩展为保存 agent working state、decision trace 和 feedback log
- [x] 2.3 将工具执行结果统一整形成 observations，供 agent 后续决策消费，而不仅用于失败后的 replanning
- [x] 2.4 保留执行适配器和 manifest/report 语义，但将“何时执行什么”交由 agent workflow 决定
- [x] 2.5 添加统一的 approval / safety gate 策略层，判定哪些动作需要门控并持久化 gate 状态
- [x] 2.6 添加 session / interrupt 持久化和恢复边界，支持 pending interrupts、resume anchor 和跨入口恢复
- [x] 2.7 扩展 `apps/mcp-project-memory` 的 canonical resources 和 mutation tools，持久化 agent state、feedback log、approval gates、interrupts、session 和版本化 resume anchors
- [x] 2.8 调整 legacy runtime 执行入口，使其同时支持 confirmed plan snapshot 与已批准 action snapshot，并移除“没有 confirmed plan 就一律拒绝执行”的硬前提
- [x] 2.9 让 approval gate 绑定不可变 `action_id` / `action_revision`，并在动作修订后使旧 gate 失效
- [x] 2.10 为 continue / resolve interrupt 添加 `active_state_version` / `resume_token` 校验与幂等语义，避免 CLI 与 Web 并发恢复时重复执行

## 3. Web Host Workflow

- [x] 3.1 将 `apps/enzyme-web-host` 从 planning console 重构为 agent-aware host，支持恢复 workflow、中断点展示和反馈提交
- [x] 3.2 更新 Web Host 视图模型和模板，展示 agent state、working plan、selected action、observations、feedback items 和 decision trace 摘要
- [x] 3.3 将现有起草/批准式操作替换为启动 workflow、继续 workflow、提交澄清反馈和审批动作等 agent workflow 操作
- [x] 3.4 增加 approval / safety gate 展示与处理界面，明确显示风险原因、审批状态和可执行反馈
- [x] 3.5 增加 session / interrupt 恢复界面，展示 pending interrupts、恢复锚点和相关上下文

## 4. CLI Workflow

- [x] 4.1 为 `apps/enzyme-host-cli` 添加调试和恢复 agent workflow 的入口点，而不是只提供 draft/approve/history 命令
- [x] 4.2 支持通过 CLI 查看待处理反馈项、提交反馈、继续 workflow 和检查 observations / decision trace
- [x] 4.3 支持通过 CLI 查看和处理 approval / safety gates，并从 interrupt 恢复点继续 workflow

## 5. Verification

- [x] 5.1 使用 fake model adapter 添加 agent workflow 测试，覆盖连续多轮决策、工具调用、反馈中断和恢复
- [x] 5.2 扩展 runtime 集成测试，验证 agent state、decision trace、run manifests 和报告之间的规范关联
- [x] 5.3 更新 Web Host 和 CLI 测试，覆盖 workflow 恢复、反馈提交、observation-driven state change 和 approval gating
- [x] 5.4 增加 approval policy 和 interrupt recovery 测试，覆盖 gate 创建、审批结果回写和跨界面恢复
- [x] 5.5 为 `mcp-project-memory` 增加资源与 mutation tool 测试，覆盖 feedback log、approval gates、interrupts 和 session 资源读取
- [x] 5.6 增加 stale gate / stale resume 测试，验证旧 `action_revision` 或旧 `resume_token` 不会重复触发工具执行
- [x] 5.7 更新 Web Host 与 CLI 测试，覆盖 stale-state 错误后的刷新与恢复行为
