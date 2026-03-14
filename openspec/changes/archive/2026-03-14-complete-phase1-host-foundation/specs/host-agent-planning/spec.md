## MODIFIED Requirements

### Requirement: Host agent 持续决定下一步行动
The system MUST 提供一个 host 级别的 agent workflow，它能够加载活跃的项目和 episode 上下文，并在每一轮根据目标、observations、人类反馈以及当前可见的 capability summaries 决定下一步行动。

该 workflow 至少必须能够决定：

- 是否需要补充信息或提出澄清问题
- 是否需要生成或修订 working plan
- 是否需要先查看某类 MCP capability 的详细契约
- 是否需要调用受控工具动作
- 是否需要请求人类审批或反馈
- 是否应继续、暂停或结束当前 episode

该 workflow 还必须满足：

- 支持从配置选择启发式 backend 或真实 LLM backend
- 默认基于 capability summary 判断是否需要某个 MCP，而不是假定一开始就拥有所有完整 tool schema
- 当判断某个 capability 相关时，可以通过 Host 请求单个 capability 的 detail contract
- 在 detail contract 可见的当前决策窗口内，再选择具体 tool、resource 或 prompt
- 将本轮决策所使用的 backend、provider、model 和 fallback 状态写入 working state 或决策记录

#### Scenario: agent 根据上下文决定先澄清而不是直接执行
- **WHEN** 一个活跃 episode 的目标缺少关键输入，用户从 host 界面启动 workflow
- **THEN** host agent 进入待澄清状态并返回结构化的问题或缺失信息项
- **THEN** system 不会在缺少必要上下文时直接冻结一个可执行计划并开始执行

#### Scenario: 配置了 sidecar backend 的 agent 使用 summary-detail 路径决定下一步动作
- **WHEN** 一个活跃 episode 启用了 LLM backend，用户从 host 界面启动 workflow
- **THEN** host agent 可以先基于 capability summaries 判断是否需要某类 MCP，再按需 inspect detail contract
- **THEN** 该轮 agent state 或 decision trace 记录当前 backend、provider、model 以及 capability inspect 与后续 tool 选择的关系

## ADDED Requirements

### Requirement: Host agent 将 capability inspect 与执行生命周期建模为显式 workflow transitions
The system MUST treat capability inspection, action execution, and observation ingestion as explicit workflow transitions rather than leaving them as opaque service-side side effects.

The workflow transition model MUST record at least:

- capability inspect before a concrete tool choice when detailed schema is required
- action execution started and action execution finished
- observation recorded after execution or external result ingestion
- the linkage between selected action, run identifier, manifest reference, and resulting observation

#### Scenario: Agent inspects a capability before selecting a concrete tool
- **WHEN** the agent decides a capability is relevant but does not yet have the detailed contract
- **THEN** the workflow records a capability-inspected transition before the concrete tool is chosen
- **THEN** later readers can see that the tool choice depended on an explicit inspect step

#### Scenario: Tool execution produces a workflow transition chain instead of an isolated manifest write
- **WHEN** the agent selects a concrete tool action and runtime executes it
- **THEN** the workflow records execution-started, execution-finished, and observation-recorded transitions linked to the same action and run lineage
- **THEN** the resulting observation can be traced back to the selected action without inferring the relationship from snapshot diffs alone
