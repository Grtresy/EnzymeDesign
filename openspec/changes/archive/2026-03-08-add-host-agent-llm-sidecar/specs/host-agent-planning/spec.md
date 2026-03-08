## MODIFIED Requirements

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

#### Scenario: 配置了 sidecar backend 的 agent 使用真实 LLM 生成下一步动作
- **WHEN** 一个活跃 episode 启用了 LLM backend，用户从 host 界面启动 workflow
- **THEN** host agent 通过类型化 adapter 调用 sidecar 生成候选动作并选择下一步动作
- **THEN** 该轮 agent state 或 decision trace 记录当前 backend、provider 和 model 元数据

## ADDED Requirements

### Requirement: Host agent 对模型输出执行结构化校验与受控降级
系统 MUST 在任何 LLM 生成的设计契约、working plan、candidate actions、selected action、clarification interrupt 或 observation summary 写入 canonical agent state 之前完成结构化校验。

当 sidecar 调用失败、provider 返回无效结构或模型输出无法映射到本地类型时，系统 MUST 执行以下两种路径之一：

- 在允许降级时，记录错误原因并回退到启发式 adapter 完成当前操作
- 在不允许降级时，停止自动推进并把 workflow 置为 `blocked`、`needs_input` 或等价的可恢复状态

系统 MUST NOT 基于未通过校验的模型输出直接触发工具执行或覆盖已有 canonical agent state。

#### Scenario: 无效的模型输出不会直接触发工具执行
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

#### Scenario: 用户可以追溯某次动作选择来自哪个模型 backend
- **WHEN** 用户在 Web Host 或 CLI 中查看某个 episode 的 selected action 与 decision trace
- **THEN** 规范状态中包含该动作对应的 backend/provider/model/fallback 元数据
- **THEN** 用户可以区分该动作来自真实 LLM 决策还是启发式降级结果
