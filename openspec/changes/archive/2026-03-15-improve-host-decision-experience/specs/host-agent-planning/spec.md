## MODIFIED Requirements

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
- 用户可读的审批说明或等价字段，用简单语言解释为什么这个动作现在需要人工确认
- 当前信任策略结果或等价字段，用来说明该动作是被自动放行、要求审批，还是被策略阻断

如果 `selected_action` 在 gate 处于 pending 期间发生变化，系统必须使旧 gate 进入失效或 superseded 状态，而不是继续拿它解锁新的动作。

系统还 MUST 支持对“不需要审批”的动作保留可解释的策略判断结果，使用户能够理解为什么某个动作可以直接继续。

该策略模型 MUST 支持项目级配置更细的规则，而不只是少量固定档位。

#### 场景：高成本动作在执行前进入审批门控
- **WHEN** agent 选择一个高成本 HPC 动作作为下一步行动
- **THEN** runtime 创建一个待审批 gate 并阻止动作立即执行
- **THEN** agent workflow 进入等待审批的 interrupt state，直到用户批准或拒绝
- **THEN** gate 记录里包含面向用户的简单审批说明，而不只是内部策略字段

#### 场景：待审批期间动作修订不会复用旧 gate
- **WHEN** agent 为某个 pending gate 对应的 `selected_action` 生成了新的 action revision
- **THEN** 旧 gate 被标记为 stale、superseded 或等价失效状态
- **THEN** runtime 只允许新的 action revision 创建并消费新的 gate

#### 场景：低风险动作被自动放行时仍可解释
- **WHEN** agent 选择一个低风险且符合自动放行策略的动作
- **THEN** runtime 不创建 pending gate 也可以继续执行
- **THEN** canonical state 仍保留该动作为何可以直接继续的策略说明

### Requirement: Host agent 以有界的自动推进语义运行
The system MUST 在持续决策与可观察性之间保持明确边界，避免 agent 在缺少终止条件时无界循环。

首个版本至少必须满足：

- 每次受控工具动作完成后，workflow 必须重新评估是否终止、请求反馈、升级处理或进入下一步动作
- 连续自动推进必须受 `max_decision_rounds`、`max_auto_actions` 或等价预算约束
- 当 workflow 暂停、停止或升级时，canonical state 必须显式表达稳定的终止或暂停语义，而不是只留下零散状态片段

稳定语义至少必须覆盖：

- `completed`
- `failed`
- `needs_input`
- `awaiting_approval`
- `blocked`
- `max_turns_exceeded`
- `escalated`

对于每个非继续执行状态，系统还 MUST 提供：

- 停止或暂停原因摘要
- 建议的下一步动作或等价提示
- 是否需要用户立即介入

#### 场景：agent 在预算耗尽时停止而不是无界循环
- **WHEN** agent 连续多轮都无法获得足够 observation 来完成目标，且已达到自动推进预算
- **THEN** workflow 进入显式终止或待反馈状态，而不是继续无限地产生 candidate actions
- **THEN** canonical state 明确记录 `max_turns_exceeded` 或等价原因
- **THEN** 用户可以看到建议的下一步动作，例如补充输入、调整约束或人工接管

#### 场景：系统在缺少必要输入时明确停在等待输入
- **WHEN** workflow 发现继续执行前缺少关键输入
- **THEN** system 将状态标记为 `needs_input` 或等价语义，而不是只留下空的 selected action
- **THEN** 用户可以看到系统当前缺什么，以及补齐后可以继续做什么

#### 场景：系统在无法可靠继续时升级处理
- **WHEN** workflow 多次尝试后仍无法在当前预算和策略下给出可靠下一步
- **THEN** system 可以进入 `escalated` 或等价状态
- **THEN** canonical state 说明为什么需要人工升级处理，而不是表现为普通失败

## ADDED Requirements

### Requirement: Host agent 发布结构化进度摘要
The system MUST 为活跃 workflow 生成结构化进度摘要，帮助用户快速理解“已经做了什么、现在卡在哪里、接下来准备做什么”。

该进度摘要至少必须包括：

- 当前阶段或当前关注点
- 最近完成的关键动作或里程碑
- 当前等待中的事项
- 建议的下一步动作
- 当前是否建议用户介入

系统 MUST 优先提供可行动的进度，而不是伪精确的百分比或不可靠的剩余时间承诺。

首版系统 MUST NOT 要求 progress summary 提供“预计还需多久”的明确字段。

#### 场景：用户查看一个等待审批的 workflow
- **WHEN** workflow 因待审批 gate 暂停
- **THEN** 进度摘要清楚说明系统已经完成了什么
- **THEN** 进度摘要说明当前卡在审批，而不是泛泛地显示“进行中”
- **THEN** 进度摘要给出用户下一步应执行的动作

#### 场景：工具执行完成后进度摘要前移
- **WHEN** 某个受控工具动作成功完成并生成新的 observation
- **THEN** progress summary 更新最近完成事项和当前关注点
- **THEN** 后续界面读取到的是同一份更新后的摘要

### Requirement: Host agent 提供双层决策解释
The system MUST 为关键决策、暂停点和终止点提供两层解释，而不是只保留原始 trace 或内部策略字段。

两层解释至少包括：

- 面向用户的简明解释，说明发生了什么、为什么重要、建议怎么做；首版固定使用中文
- 面向调试和审计的技术解释，说明相关 observation、策略、预算或 gate 原因

这些解释至少必须覆盖：

- 当前 selected action 为什么被选中
- workflow 为什么暂停或停止
- 某个动作为什么需要审批，或为什么可以直接继续

#### 场景：selected action 带有易懂解释
- **WHEN** agent 选择一个新的 tool action 作为下一步
- **THEN** canonical state 同时保存简明解释和技术解释
- **THEN** 用户可以快速理解为什么选这个动作，而不必先阅读完整 decision trace

#### 场景：workflow 停下时用户能看懂原因
- **WHEN** workflow 进入 `blocked`、`needs_input`、`awaiting_approval` 或 `max_turns_exceeded`
- **THEN** 系统提供面向用户的简单说明
- **THEN** 系统同时保留面向调试的技术原因，以便审计和问题排查
