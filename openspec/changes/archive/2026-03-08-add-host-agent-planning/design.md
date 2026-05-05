## 背景

代码库已经拥有共享的 host runtime、轻量的 Web 和 CLI 界面，以及面向预处理和 HPC 的工具执行边界。当前 MVP 的优势是工作区状态清晰、执行可恢复、运行与报告制品有规范化落点；但它的主要局限也很明显：系统仍然围绕“先确认一个固定计划，再由确定性执行器顺序执行”的模型组织。

这与 `docs/OpenZyme架构设计.md` 描述的 Host Agent 形态不一致。你希望的系统不是一个“LLM 只负责起草计划”的 planner，而是一个持续做决策的 host agent：它需要根据 episode 目标、工具观察结果和人类反馈，动态决定下一步做什么，必要时改写计划、请求澄清、调用工具，或停下来等待审批。

因此，这次 change 的设计不应再把 LangGraph 仅仅作为“计划起草器 + 执行后评估器”，而应把它定义为 Host 的主工作流引擎。共享 runtime 仍然保留状态持久化、工具适配和可审计性职责，但决策流应由 LLM 驱动的图状态机掌控。

## 目标 / 非目标

**目标：**
- 将 Host Agent 设计为一个持续运行的决策闭环，而不是单次计划生成器。
- 让 LLM 能基于 episode 上下文、执行观察和人类反馈持续决定：
  - 是否需要补充信息
  - 是否需要调用工具
  - 是否需要请求审批
  - 是否需要修订当前计划
  - 是否应该结束当前 episode
- 用 LangGraph 表达可恢复的 agent 工作流状态，而不仅是一次性 draft/approve/replan 生命周期。
- 保留共享 runtime 作为规范状态、工具调用、运行清单和报告元数据的统一服务层。
- 保留 Web Host 作为主要人机界面，但使其承载“反馈与决策中断点”，而不是静态计划控制台。

**非目标：**
- 不在这次改动中实现完整的多 agent 编队或远程 agent 网络。
- 不把全部业务逻辑迁移到新的 MCP server 中。
- 不放弃现有的运行清单、报告和工作区制品语义。
- 不允许无约束的自由执行；高成本、高风险或破坏性动作仍需显式策略和人工门控。
- 不要求首个版本就具备复杂对话 UX；重点是决策流和状态模型，而不是完整聊天产品体验。

## 决策

### 1. 让 LangGraph 成为 Host 的主决策引擎，而不是仅用于规划

**决策：** 在 `packages/enzyme-host-runtime` 中实现 LangGraph 驱动的 Host Agent 工作流，使图负责持续决策，而不仅在执行前生成草案。

图的职责至少包括：
- 从 episode 目标和工作区状态初始化 agent state
- 决定下一步是澄清、规划、执行工具、评估观察还是请求人类反馈
- 在观察结果或反馈到来后修订计划
- 在满足终止条件时结束当前轮次

Host 的核心循环应从“draft a plan, then execute deterministically”转向：

`decide -> act -> observe -> revise -> ask/approve -> continue or stop`

**理由：** 这才符合架构文档中“Host 是真正的 agent”的定义。若 LLM 只能在起草计划时参与，那么系统仍然只是一个计划导入器外加执行器，而不是 agent。

**考虑过的替代方案：**
- 把 LangGraph 限定为规划器：实现简单，但无法表达持续决策。
- 在 Web 层做交互式决策，在 runtime 仅做执行：会让浏览器成为真实编排源，破坏共享语义。

### 2. 将“计划”降级为动态工件，而不是执行唯一真源

**决策：** 计划仍然存在，但它是 agent state 的一部分，是动态可修订工件，而不是执行前一次冻结的唯一输入。

新的状态模型中应区分：
- `current_objective`
- `design_contract`
- `working_plan`
- `candidate_actions`
- `selected_action`
- `observations`
- `human_feedback`
- `approval_requests`
- `decision_log`
- `termination_status`

“已确认计划”可以继续存在，但它表示某个时刻被人类批准的工作方案快照，而不是整个系统未来所有动作的唯一脚本。
runtime 必须允许两种受控执行入口并存：

- 兼容模式：执行一个 confirmed plan 快照
- agent 模式：执行一个已批准的 action snapshot

因此，“没有 confirmed plan 就绝不允许提交任何工作”不再是通用规则；只有在既没有可执行 action snapshot、也没有可执行 confirmed plan 快照时，runtime 才应返回验证错误。

**理由：** 真正的 agent 会在运行过程中根据观察修订策略。把计划固定为单一 `confirmed plan` 会把系统重新拉回传统 workflow engine。

**考虑过的替代方案：**
- 继续把 confirmed plan 作为执行真源：最接近当前实现，但无法表达动态修订。
- 完全取消计划概念：会削弱可审计性和人类审阅能力。

### 3. 让 LLM 参与工具调用决策，但保留工具执行的受控适配边界

**决策：** Agent 图节点可以决定“调用哪个工具、带什么参数、为什么调用、是否需要继续”，但实际工具调用仍通过共享 runtime 的受控适配器执行。

边界应是：
- **LLM / Graph**：决定调用意图、行动顺序、参数提议、是否继续
- **Runtime service layer**：验证动作、执行工具、记录 manifest、落地报告和状态

也就是说，不再要求图只能在执行前后运行；图可以直接触发受控工具节点。但图不能绕过 runtime 直接操作底层后端。

**理由：** 这样既保留了 agent 的决策权，也保留了现有执行基础设施的可控性、可测试性和审计性。

**考虑过的替代方案：**
- 让图完全不能触发工具：LLM 没有实际行动能力。
- 让图直接调用 provider SDK 或 shell：会绕过已有的工作区与 manifest 语义。

### 4. 将人类反馈建模为图中的一等中断点

**决策：** 人类反馈不应只出现在“批准草案”这个单一动作里，而应成为图状态机中的 interrupt / approval / clarification 节点。

系统至少要支持以下反馈类型：
- 审批某个 proposed action 或 working plan
- 回答 agent 提出的澄清问题
- 拒绝某个动作并要求替代方案
- 在观察结果后给出新的约束或目标修订

Web Host 和 CLI 都应能够恢复这些待反馈状态，并把反馈回写到规范 episode state 中，再由图继续执行。

**理由：** 你预想的系统显然不是“人类只在计划确认前点击一次 approve”。人类应是闭环中的主动参与者。

**考虑过的替代方案：**
- 仅保留 plan approval：太窄，无法覆盖澄清和运行中的策略调整。
- 让反馈仅存在于 UI 会话内：会丢失跨界面恢复能力。

### 5. 将执行结果建模为 observations，而不仅是重新规划证据

**决策：** 工具执行结果、运行状态、失败原因、制品可用性和报告元数据应统一进入 `observations` / `execution evidence` 层，供 agent 下一轮决策消费。

这些观察不仅用于“失败后是否重规划”，还用于：
- 判断是否继续调用后续工具
- 判断是否需要切换策略
- 判断是否请求人工反馈
- 判断是否满足终止条件

因此，执行证据不再只是规划器的附属输入，而是 agent 循环中的核心观察数据。

**理由：** 如果 observation 只能在“失败后触发 replanning”时使用，那么系统仍然是线性的 planning/execution 二段式。

**考虑过的替代方案：**
- 将观察保留给单独的 replanning 模块：会割裂 agent 闭环。

### 6. 用版本化 agent state 保留决策谱系，而不只保留草案版本

**决策：** 需要保留的不只是“计划草案版本”，而是更广义的 agent 决策谱系。最小可审计对象应包括：
- 设计契约快照
- working plan 修订
- 每次 selected action
- 工具观察结果引用
- 人类反馈记录
- 审批请求与审批结果
- 终止原因

计划版本仍然可以保留，但应成为整体 agent trace 的一个子集，而不是唯一版本对象。

**理由：** 对一个持续决策 agent 来说，真正需要回答的问题是“为什么在这个时刻选择了这个动作”，而不是“哪个草案替换了哪个草案”。

**考虑过的替代方案：**
- 仅保留 draft lineage：无法解释运行时决策和人类反馈如何改变行为。

### 7. Web Host 展示的是 agent workflow，不只是 planning workflow

**决策：** Web Host 应升级为 agent-aware host，至少展示：
- 当前 episode 目标
- 当前 agent state 摘要
- 当前 working plan / selected action
- 最近 observations / run lineage
- 待审批 / 待澄清 / 待反馈项
- 人类可以提交的反馈动作
- 当前报告与制品摘要

它仍然是轻量适配层，但它适配的是“agent 工作流状态”，而不只是 draft/approve/replan 三个 planning 按钮。

**理由：** 如果 UI 只展示规划状态，那么用户看到的仍然是 workflow console，而不是 host agent。

**考虑过的替代方案：**
- 保持 Web Host 只显示计划和运行：无法支撑人机协同闭环。

### 8. 将模型访问隔离在类型化 agent adapter 后面，但测试覆盖整个决策循环

**决策：** LLM provider 访问仍通过适配器边界隔离，但适配器不应只暴露 `draft_plan()` 这类窄接口，而应支持 agent 决策相关能力，例如：
- 生成或修订 design contract
- 产生 candidate actions
- 选择下一步动作
- 总结 observations
- 形成澄清问题或审批请求

测试中应使用 fake adapter 驱动整个决策图，验证：
- 连续多轮决策
- 工具调用后的状态推进
- 人类反馈恢复
- 失败后的策略修订

**理由：** 如果适配器抽象仍然只围绕“计划起草”，那实现层自然会继续收缩成 planner。

### 9. 将 approval / safety gate 作为 runtime 中的显式策略层

**决策：** agent 可以提出动作，但不能直接越过门控策略执行高成本、高风险或外部副作用动作。Host runtime 必须在图和执行边界之间提供显式的 approval / safety gate。

至少要支持以下门控类别：
- GPU / 长时 HPC 任务
- 会造成明显费用放大的批量搜索或批处理
- 向外部系统写入数据或导出交付物
- 涉及敏感序列、高风险用途或策略白名单之外的动作

门控状态必须是结构化的，至少包括：
- `gate_id`
- `action_type`
- `risk_level`
- `policy_reason`
- `required_feedback_type`
- `status`（`pending`、`approved`、`rejected`、`expired`）
- `resolved_by`
- `resolved_at`

agent graph 的语义应是：
- 先提出动作
- 由 runtime 策略层判断是否需要门控
- 若需要，则进入 interrupt state 并等待反馈
- 若不需要，则进入受控执行

**理由：** 架构文档明确要求 approval & safety gates，但这不等于把所有执行都改回硬编码流程。正确边界是“agent 决策动作，runtime 决定该动作能否直接执行”。

**考虑过的替代方案：**
- 让 agent 自己决定是否需要审批：不可靠，也不利于策略统一。
- 对所有动作都要求审批：会把 agent 退化为人工驱动向导。

### 10. 将 session / interrupt state 定义为一等可恢复状态

**决策：** 持久化模型必须显式区分 agent 的长期 working state 和宿主入口需要恢复的 session / interrupt state，而不是把所有内容混成一个 planning record。

最小 session / interrupt 模型应至少包括：
- `session_id`
- `episode_id`
- `active_revision` 或 `active_state_version`
- `pending_interrupts`
- `last_selected_action`
- `last_observation_refs`
- `awaiting_feedback`
- `resume_token` 或等价恢复锚点
- `updated_at`

其中 `pending_interrupts` 应能表达：
- clarification request
- approval request
- tool execution blocked by policy
- external run awaiting completion
- user-directed pause

Web Host 和 CLI 都应从同一个持久化 interrupt state 恢复，而不是各自维护“当前停在什么地方”的私有变量。

**理由：** 架构文档明确要求长任务恢复、跨界面恢复和类似 Claude Code 的持续工作体验。没有 session / interrupt 模型，workflow 只能停留在单轮请求响应。

**考虑过的替代方案：**
- 只保留 decision trace，不保留恢复锚点：可审计但不可恢复。
- 让 UI 自己记住当前 interrupt：无法跨入口一致恢复。

### 11. 将 mcp-project-memory 扩展为 agent workflow 的规范数据契约

**决策：** `mcp-project-memory` 必须为 agent workflow 暴露稳定资源和 mutation tools，而不能只复用现有 `state` / `plan` 文件并让 Host 自己约定私有结构。

最小新增资源至少包括：
- `agent-state`
- `decision-log`
- `feedback-log`
- `approval-gates`
- `interrupts`
- `session`

最小新增写入边界至少包括：
- 写入 agent working state
- 追加 feedback / approval
- upsert gate
- 写入 / 解决 interrupt
- 提交 continue / resume

这些写入必须支持 `active_state_version`、`resume_token` 或等价的乐观并发字段。

**理由：** 如果没有规范数据契约，跨 Web / CLI 的恢复只会停留在口头约定，runtime 与 UI 很快就会演化出各自的私有状态解释器。

**考虑过的替代方案：**
- 把所有 agent 状态继续塞进单个 `state.json`：短期省事，但会让 gate、interrupt 和 feedback 的结构化访问变脆。
- 让 host runtime 自己维护恢复状态：会破坏“项目内存是规范真源”的架构边界。

### 12. 将 approval gate 绑定到不可变 action snapshot

**决策：** 每个需要门控的动作都必须先生成稳定的 `action_id` 与 `action_revision`，gate 必须引用这个不可变快照，而不是仅引用“当前 selected action”的类型。

如果 pending gate 存在期间 agent 修订了 `selected_action`，则旧 gate 必须进入 `stale`、`superseded` 或等价失效状态，新动作必须申请新的 gate。

**理由：** 计划和动作都是可修订工件。如果 gate 不绑定到快照，审批链路就可能批准旧参数，却放行新参数。

**考虑过的替代方案：**
- gate 只记录动作类型：无法区分同一类型但不同参数或不同 revision 的动作。
- 让 UI 在审批时自行比对动作是否变化：不可靠，而且会把安全语义分散到界面层。

### 13. 将 interrupt 恢复定义为版本校验 + 幂等 continue

**决策：** 所有 continue / resolve interrupt 操作都必须携带 `active_state_version` 与 `resume_token` 或等价字段。runtime 只接受第一个匹配当前版本的恢复请求；后续重复请求要么返回相同的幂等结果，要么返回结构化 stale-state 错误，但绝不能重复提交动作。

UI 的职责不是猜测哪个恢复请求成功，而是在收到 stale-state 后刷新规范状态并重新渲染。

**理由：** Web Host 与 CLI 都能恢复同一个 interrupt，这天然引入并发提交。没有版本校验，就会产生重复工具调用、重复审批或状态回退。

**考虑过的替代方案：**
- 用“最后写入者获胜”覆盖状态：最容易实现，但会导致不可审计的重复执行。
- 完全禁止多入口恢复：违背这次 change 的核心目标。

### 14. 将自动推进限制在有界、可观察的预算内

**决策：** 首个版本允许 agent 连续推进多个决策轮次，但必须受 `max_decision_rounds`、`max_auto_actions` 或等价预算约束，并且每次受控工具动作后都要重新评估是否终止、请求反馈或继续。

预算耗尽、信息不足或策略阻塞时，workflow 必须显式写入 `termination_status` 或 pending interrupt，而不是继续空转。

**理由：** 不给自动推进设置预算，系统很容易在 observation 不充分时进入无休止循环；而每个动作后回到显式检查点，才能让 Web / CLI / 测试共享一致语义。

**考虑过的替代方案：**
- 强制每个动作后都必须人工确认：过于保守，会把 agent 退化为手动向导。
- 允许无限自动推进直到模型自己停下：不可控，也难以测试。

## 风险 / 权衡

- **[Agent 过度自由，导致不可控行为]** -> 将决策权交给图，但把实际工具执行、策略校验、审批门控和资源限制保留在 runtime service 层。
- **[状态模型过度膨胀，难以恢复]** -> 定义最小可恢复 agent state，优先覆盖 objective、working plan、selected action、observations、feedback 和 approval。
- **[Web Host 承担过多编排逻辑]** -> 所有状态推进都必须通过共享 runtime / graph 服务完成，UI 只提交事件和呈现状态。
- **[测试变脆]** -> 用 fake adapter 和 fake tool observations 测试图级行为，不把测试绑定到实时模型输出。
- **[现有确定性执行语义被打散]** -> 保留底层执行适配器、run manifest 和报告语义，只把“何时执行什么”交还给 agent graph。
- **[审批策略散落在 UI 或 prompt 中]** -> 将 approval / safety gate 保持在 runtime 策略层，并把判定结果结构化持久化。
- **[workflow 可审计但不可恢复]** -> 除 decision trace 外，单独定义 session / interrupt 恢复锚点。
- **[旧 gate 批准了新动作]** -> gate 必须绑定 `action_id` / `action_revision`，动作修订后旧 gate 立即失效。
- **[CLI 与 Web 并发恢复导致重复执行]** -> 所有恢复路径都要求 `resume_token` + `state_version` 校验，并保证 continue 幂等。

## 迁移计划

1. 将 `planning/` 重新定义为 `agent workflow` 模块，覆盖图状态、决策节点、反馈节点和观察节点。
2. 扩展共享 runtime 服务，使其暴露“继续 agent workflow”“提交人类反馈”“执行受控工具动作”“恢复中断状态”等接口，而不是只暴露 draft/approve/replan。
3. 将执行适配器保留为受控边界，但允许图节点通过 runtime 调用它们。
4. 将 episode 范围持久化从“planning revision”扩展为“agent trace + working state”。
5. 更新 Web Host，使其显示待处理问题、待审批动作、最近 observations 和当前 working plan，而不是以手工确认 plan 为中心。
6. 更新 CLI，使其能调试 agent state、恢复中断、提交反馈和驱动单步继续。
7. 增加 approval / safety gate 策略层，并定义需要审批的动作分类和状态转换。
8. 扩展 `mcp-project-memory` 的 canonical resources 和 mutation tools，承载 agent state、feedback、gates、interrupts 和带版本校验的恢复锚点。
9. 增加 session / interrupt 持久化模型，要求 continue / resolve 使用 `state_version` 与 `resume_token`。
10. 要求 gate 绑定不可变 action snapshot，并在 action revision 变化时使旧 gate 失效。
11. 用假模型和假工具覆盖连续决策、反馈恢复、policy gating、stale resume 和 observation-driven revision。

**回滚：** 如需回退，可将 agent workflow 重新收窄为“draft/approve/replan”模式，同时保留已经引入的状态模型、工具适配边界和 Web/CLI 宿主结构。

## 待解决问题

- 哪些动作需要强制审批，哪些动作可以由 agent 自动继续？
- working plan 的粒度应该是“完整计划快照”，还是“下一步动作队列 + 长程意图”？
- 人类反馈应如何分类和序列化，才能同时支持 Web 与 CLI 的恢复式交互？
- approval policy 是声明式规则集、代码策略对象，还是两者结合？
- 外部长任务等待中的 interrupt 是否需要单独的 scheduler / watcher，还是由宿主轮询恢复即可？
