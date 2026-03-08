## ADDED Requirements

### Requirement: Host agent 持续决定下一步行动
The system MUST 提供一个 host 级别的 agent workflow，它能够加载活跃的项目和 episode 上下文，并在每一轮根据目标、observations 和人类反馈决定下一步行动。

该 workflow 至少必须能够决定：

- 是否需要补充信息或提出澄清问题
- 是否需要生成或修订 working plan
- 是否需要调用受控工具动作
- 是否需要请求人类审批或反馈
- 是否应继续、暂停或结束当前 episode

该 workflow 还必须满足：

- 支持从配置选择启发式 backend 或真实 LLM backend
- 当启用真实 LLM backend 时，通过类型化 adapter 和结构化 sidecar 响应生成设计契约、候选动作、动作选择、澄清中断和 observation 摘要
- 将本轮决策所使用的 backend、provider、model 和 fallback 状态写入 working state 或决策记录

#### 场景：agent 根据上下文决定先澄清而不是直接执行
- **WHEN** 一个活跃 episode 的目标缺少关键输入，用户从 host 界面启动 workflow
- **THEN** host agent 进入待澄清状态并返回结构化的问题或缺失信息项
- **THEN** system 不会在缺少必要上下文时直接冻结一个可执行计划并开始执行

#### 场景：配置了 sidecar backend 的 agent 使用真实 LLM 生成下一步动作
- **WHEN** 一个活跃 episode 启用了 LLM backend，用户从 host 界面启动 workflow
- **THEN** host agent 通过类型化 adapter 调用 sidecar 生成候选动作并选择下一步动作
- **THEN** 该轮 agent state 或 decision trace 记录当前 backend、provider 和 model 元数据

### Requirement: Host agent 将计划作为可修订的动态工件维护
The system MUST 将计划表示为 agent state 中的动态工件，而不是执行前一次冻结的唯一真源。

agent state 必须至少能够表示：

- `design_contract`
- `working_plan`
- `candidate_actions`
- `selected_action`
- `observations`
- `human_feedback`
- `approval_requests`
- `decision_log`
- `termination_status`

#### 场景：观察结果触发 working plan 修订
- **WHEN** agent 在一次工具调用后收到新的 observation，发现当前 working plan 假设不再成立
- **THEN** host agent 可以修订 working plan 并选择新的下一步动作
- **THEN** 修订行为被记录为 agent trace 的一部分，而不是要求用户先手工导入新计划

### Requirement: Host agent 可基于 agent 决策触发受控工具调用
The system MUST 允许 agent workflow 决定何时调用哪个工具以及使用哪些参数，但所有实际工具调用必须仍通过共享 runtime 的受控执行边界完成。

系统必须至少记录：

- 被选中的动作类型
- 目标工具和参数提议
- 动作发起原因
- 产生的运行 id、manifest 引用和 observations

#### 场景：agent 决定调用工具并消费结果继续推理
- **WHEN** agent 判断下一步需要运行一个预处理或 HPC 工具
- **THEN** shared runtime 代表 agent 以受控方式执行该工具并持久化 manifest
- **THEN** 工具结果被回写为 observation，供后续决策节点继续使用

### Requirement: Host agent 将人类反馈建模为一等 workflow 中断点
The system MUST 支持 agent 在 workflow 中请求人类反馈、审批或澄清，并在反馈提交后从持久化状态恢复继续执行。

支持的反馈类型至少包括：

- 审批 proposed action 或 working plan
- 回答 agent 的澄清问题
- 拒绝当前提议并要求替代方案
- 提供新的约束或目标修订

#### 场景：agent 请求人类审批后恢复继续
- **WHEN** agent 生成一个需要人工门控的动作提议
- **THEN** system 持久化待审批状态并向 host 界面暴露待处理项
- **THEN** 用户提交反馈后，agent workflow 从该中断点恢复并继续推进

### Requirement: Host agent 保留可审计的决策谱系
The system MUST 将 agent workflow 的关键状态转换保留为 episode 范围的可审计记录，而不仅仅是保留计划草案版本。

最小可审计对象至少包括：

- 设计契约快照
- working plan 修订
- selected action 记录
- observation 引用
- human feedback 记录
- approval decision
- termination reason

#### 场景：用户追溯为什么 agent 改变了行动路径
- **WHEN** 一个 episode 在多轮 observation 和人类反馈后产生与最初不同的行动路径
- **THEN** 用户可以查看该 episode 的 agent trace
- **THEN** trace 能解释是哪次 observation 或反馈导致了 selected action 或 working plan 的变化

### Requirement: Host agent 对需要门控的动作进入结构化 approval / safety gate
The system MUST 支持 agent 提出动作后，由 runtime 策略层判断该动作是否需要审批或安全门控，并在需要时进入结构化 interrupt state，而不是直接执行。

每个 gate 至少必须记录：

- `gate_id`
- `action_id`
- `action_revision`
- `action_type`
- 已提议参数或不可变 action snapshot 引用
- `risk_level`
- `policy_reason`
- `required_feedback_type`
- `status`

如果 `selected_action` 在 gate 处于 pending 期间发生变化，系统必须使旧 gate 进入失效或 superseded 状态，而不是继续拿它解锁新的动作。

#### 场景：高成本动作在执行前进入审批门控
- **WHEN** agent 选择一个高成本 HPC 动作作为下一步行动
- **THEN** runtime 创建一个待审批 gate 并阻止动作立即执行
- **THEN** agent workflow 进入等待审批的 interrupt state，直到用户批准或拒绝

#### 场景：待审批期间动作修订不会复用旧 gate
- **WHEN** agent 为某个 pending gate 对应的 `selected_action` 生成了新的 action revision
- **THEN** 旧 gate 被标记为 stale、superseded 或等价失效状态
- **THEN** runtime 只允许新的 action revision 创建并消费新的 gate

### Requirement: Host agent 支持可恢复的 session / interrupt state
The system MUST 将 agent workflow 的中断点建模为可恢复状态，以支持长任务恢复、跨界面恢复和持续工作会话。

interrupt state 至少必须能够表达：

- clarification request
- approval request
- external run pending
- user-directed pause
- blocked-by-policy

每个 interrupt 至少必须绑定：

- `interrupt_id`
- `active_state_version`
- `resume_token`
- `created_at` / `updated_at`

恢复语义必须保证：

- `resume_token` 只能成功消费一次或表现为幂等 continue
- 使用旧 `active_state_version` 的恢复请求会被拒绝为 stale
- 成功恢复后会生成新的 state version 或新的恢复锚点

#### 场景：agent workflow 在 CLI 与 Web Host 之间恢复同一个中断点
- **WHEN** 一个 episode 在 CLI 中进入待澄清 interrupt state
- **THEN** Web Host 随后读取该 episode 时可以显示相同的待澄清项和恢复锚点
- **THEN** 用户在 Web Host 提交反馈后，workflow 从该中断点继续推进

### Requirement: Host agent 以有界的自动推进语义运行
The system MUST 在持续决策与可观察性之间保持明确边界，避免 agent 在缺少终止条件时无界循环。

首个版本至少必须满足：

- 每次受控工具动作完成后，workflow 必须重新评估是否终止、请求反馈或进入下一步动作
- 连续自动推进必须受 `max_decision_rounds`、`max_auto_actions` 或等价预算约束
- 当预算耗尽或缺少继续所需信息时，`termination_status` 或 interrupt state 必须显式反映 `needs_input`、`blocked`、`max_turns_exceeded` 或等价原因

#### 场景：agent 在预算耗尽时停止而不是无界循环
- **WHEN** agent 连续多轮都无法获得足够 observation 来完成目标，且已达到自动推进预算
- **THEN** workflow 进入显式终止或待反馈状态，而不是继续无限地产生 candidate actions
- **THEN** 用户可以从 agent state 中看到停止原因和下一步所需输入

### Requirement: Host agent 对模型输出执行结构化校验与受控降级
系统 MUST 在任何 LLM 生成的设计契约、working plan、candidate actions、selected action、clarification interrupt 或 observation summary 写入 canonical agent state 之前完成结构化校验。

当 sidecar 调用失败、provider 返回无效结构或模型输出无法映射到本地类型时，系统 MUST 执行以下两种路径之一：

- 在允许降级时，记录错误原因并回退到启发式 adapter 完成当前操作
- 在不允许降级时，停止自动推进并把 workflow 置为 `blocked`、`needs_input` 或等价的可恢复状态

系统 MUST NOT 基于未通过校验的模型输出直接触发工具执行或覆盖已有 canonical agent state。

#### 场景：无效的模型输出不会直接触发工具执行
- **WHEN** sidecar 返回的候选动作中包含无法通过本地类型校验的工具参数
- **THEN** Host agent 拒绝把该结果写入 canonical agent state
- **THEN** workflow 要么回退到启发式 adapter，要么进入结构化阻断状态，而不是继续执行该工具动作

### Requirement: Host agent 将 backend provenance 作为可审计状态的一部分持久化
系统 MUST 把每次关键模型决策的 backend provenance 持久化到 episode 范围的规范状态中，而不仅仅在日志输出里打印。

至少以下对象在由 LLM backend 生成或修改时必须带有 provenance 元数据：

- `design_contract`
- `working_plan`
- `selected_action`
- `decision_trace`
- `observations` 的摘要记录

这些 provenance 元数据至少必须标识：

- adapter/backend 类型
- sidecar 名称或版本
- provider 名称
- model 名称
- 是否发生 fallback

#### 场景：用户可以追溯某次动作选择来自哪个模型 backend
- **WHEN** 用户在 Web Host 或 CLI 中查看某个 episode 的 selected action 与 decision trace
- **THEN** 规范状态中包含该动作对应的 backend/provider/model/fallback 元数据
- **THEN** 用户可以区分该动作来自真实 LLM 决策还是启发式降级结果
