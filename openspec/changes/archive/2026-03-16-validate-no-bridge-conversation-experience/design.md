## Context

当前 Web Host 已经具备一条可工作的主链路：可以加载项目、切换 episode、启动或继续 workflow、审批 gate、提交 feedback、执行 selected action，并查看 run 细节与报告。底层的 canonical state 也已经比较完整，尤其是这轮决策体验增强之后，runtime 已经能稳定提供：

- `stop_reason`
- `progress_summary`
- `plain_language_explanation`
- `technical_explanation`
- pending interrupts
- approval gates
- workflow audit
- selected action 与 run lineage

但现在的页面组织方式仍然偏“控制台”。用户通常要在多个 panel 之间来回看，自己拼出一条故事线：

- 系统刚刚做了什么
- 为什么停下
- 当前最重要的卡点是什么
- 现在最推荐我做什么
- 我操作完之后，系统会从哪里接着走

这次 change 的目标，不是新增一个 chat agent，也不是引入新的 message storage，而是用现有 canonical state 做一次更严格的展示层验证：如果把这些结构化状态重新组织成一条更连续的叙事时间线，用户是否已经会觉得“像在协作”，而不必马上引入新的对话桥梁层。

约束也很明确：

- canonical workflow state 仍然是唯一的业务真源
- 前端不新增私有 message 状态作为第二真源
- 所有动作仍通过共享 runtime 提交
- 首轮验证不增加自由输入的 chat composer

## Goals / Non-Goals

**Goals:**

- 用现有 canonical state 和现有 runtime，重组出一个更有连续感的 Web 主界面。
- 让用户进入页面后，第一眼看到的是“系统在讲什么”和“我现在该做什么”，而不是先看到多个分散的面板。
- 把 gate、interrupt、selected action、run result 这些关键节点改造成时间线里的消息卡片，让交互更自然。
- 保持 trace/debug/raw state 仍然存在，但退到辅助区域，不再抢占主操作区。
- 用最小实现成本验证一个核心判断：当前缺少的主要是“呈现方式”，还是“真的需要新的对话桥梁层”。

**Non-Goals:**

- 不引入新的 chat 输入框或自由文本对话入口。
- 不新增独立的聊天历史存储，也不把聊天历史变成 workflow 真源。
- 不让 Web Host 在前端本地私自推进 workflow 或缓存私有状态副本。
- 不在本次 change 中实现 NL intent parsing、message-to-intent 翻译或新的桥梁 agent。
- 不把 CLI 一起改造成 conversation-style shell；本次验证聚焦 Web Host。

## Decisions

### 1. 主界面改成“叙事时间线 + 可操作消息卡片”，而不是继续堆更多状态面板

决定：

- Web Host 的主区域改为 conversation-style timeline。
- 时间线中的每一项都来自现有 canonical data，而不是来自新的聊天记录。
- 时间线至少要能容纳这几类内容：
  - 当前系统总结消息
  - selected action 消息
  - pending interrupt / approval gate 消息
  - recent run result 消息
  - recent workflow audit 事件摘要

原因：

- 用户当前最缺的不是更多字段，而是一条容易顺着看的主线。
- 同样一组数据，如果放在分散面板中，用户需要自己拼接；如果按时间和因果关系重组，理解成本会低很多。

备选方案：

- 保持现有 panel 布局，只增加更多解释文案。

不选原因：

- 这只能让每块 panel 更完整，不能解决“整体没有连续感”的问题。

### 2. 时间线是“从 workflow state 渲染出来的视图”，不是新的消息系统

决定：

- 不新增新的 message 表或 message 资源。
- 时间线 item 由现有 snapshot 数据派生而来，例如：
  - `plain_language_explanation`
  - `progress_summary`
  - `selected_action`
  - `pending_interrupts`
  - `approval_gates`
  - `runs`
  - `workflow_audit`
- 每个关键 timeline item 都尽量带上对应的业务引用，例如 `gate_id`、`interrupt_id`、`run_id`、`action_id`。

原因：

- 这是“无桥梁版本验证”的核心边界。我们要验证的是：现有真源是否已经足够支撑更自然的体验。
- 如果这一步就引入新的消息存储，会把“展示问题”和“架构问题”混在一起，验证结果不干净。

备选方案：

- 新增一份浏览器专用 message timeline，并把每次状态变化翻译成消息后持久化。

不选原因：

- 这样会引入新的状态副本，很容易和 canonical state 漂移。
- 一旦消息本身可变，就会逐渐变成第二个解释层、甚至第二个控制平面。

### 3. 可操作项直接嵌在时间线卡片里，但动作提交路径不变

决定：

- approval、reject、submit feedback、continue、execute selected action 等操作，优先通过时间线里的卡片入口触发。
- 这些按钮和表单底层仍然调用现有 runtime API / HTTP route。
- 现有独立操作区可以保留，但从“主入口”降级为“辅助入口”。

原因：

- 真正让体验“像对话”的，不只是文案，而是“我在读到一条系统消息时，就能就地回应它”。
- 但响应动作不能绕开 runtime，否则就会破坏 workflow-first 边界。

备选方案：

- 只把说明放进时间线，所有操作仍然留在独立控制面板。

不选原因：

- 这仍然会让阅读和操作割裂，用户看完消息后还得跳去另一个区域处理。

### 4. Debug / Trace 留着，但明确退到二级区域

决定：

- `technical_explanation`、raw agent state、workflow audit 细节、provider/model/provenance、execution evidence 仍然保留。
- 这些内容放在 Debug / Trace 区域，不和主时间线抢主视觉层级。

原因：

- 这次 change 不是“去掉技术信息”，而是“把面向人决策的主视图和面向排障的次视图分开”。
- 对高级用户和开发调试来说，debug 信息仍然非常有价值。

备选方案：

- 为了更像聊天，把 raw/debug 信息直接拿掉。

不选原因：

- 这会牺牲当前 Host 的一个重要优势：可审计、可追踪、可排障。

### 5. 首轮验证不加自由输入 chat composer

决定：

- 首轮验证阶段不加入“给系统发自然语言消息”的输入框。
- 用户与系统的交互仍然通过结构化表单、按钮和现有 workflow action 完成。

原因：

- 如果一开始就放 chat composer，用户会自然期待自然语言驱动，这会把验证焦点从“展示层重组”转移到“桥梁层有没有做好”。
- 这次要先回答一个更基础的问题：只重做视图组织，能不能把体验显著拉近。

备选方案：

- 同步加入最小 chat composer，但只做文案解释。

不选原因：

- 用户会误以为这是半成品聊天系统，反而降低判断清晰度。

### 6. 用已有 playground 做手动验证闭环

决定：

- 继续使用已经准备好的 GLM + Web Host + HPC `fpocket` playground 作为手动验证入口。
- 优先验证这些典型状态：
  - `awaiting_approval`
  - 批准后执行
  - 执行完成后的 run / report 回流
  - 可选的 `blocked` 或 `needs_input`

原因：

- 这套 playground 已经能稳定把用户带到一个需要人工介入的真实节点，非常适合观察“是否更有协作感”。
- 不需要额外造一套脱离真实 runtime 的假页面。

### 7. 为未来 `mcp-structure-workbench` 预留宿主接缝，但不提前实现 workbench 本体

决定：

- 本次改造会在 Web Host 的页面组织和时间线卡片模型里，预留一个未来可承载 richer app block / workbench viewer 的宿主接缝。
- 这类接缝首版只需要满足：
  - 页面布局上存在一个未来可放置结构 workbench 的区域或插槽
  - timeline / action card 能表达“打开结构工作台”“查看结构上下文”这类入口
  - UI 层能够把 `project_id`、`episode_id`、`annotations` resource reference 或等价上下文继续向下传递
- 本次不会实现真正的 iframe 嵌入协议、不会新增假的 MCP transport，也不会实现 `mcp-structure-workbench` 的 viewer 本体。

原因：

- `docs/OpenZyme架构设计.md` 已经把 `mcp-structure-workbench` 定义为 Phase 2 的独立 MCP App，后续它需要在宿主里有自然的落位。
- 如果当前页面被写死为“只有纯文本卡片”，后续接入结构工作台时很容易再经历一次大改。
- 但如果现在就实现半套 workbench 集成，会把“无桥梁版本验证”的目标搞混，也会无端扩大范围。

备选方案：

- 这次完全不考虑 workbench，只把页面按当前文本时间线需求写死。

不选原因：

- 会让后续接入 `mcp-structure-workbench` 时缺乏宿主侧参考点，增加返工成本。

另一种备选方案：

- 现在就提前做 iframe 容器、假 route 和假 viewer 集成。

不选原因：

- 这会制造一套没有真实后端契约支撑的半成品接口，短期看像“有预留”，长期反而更容易误导后续实现。

### 8. 主时间线首版优先展示“高价值事件摘要”，不直接平铺全部 workflow audit

决定：

- 主时间线首版不严格按时间平铺所有 workflow audit 事件。
- 主时间线优先展示能帮助用户快速理解主线的高价值事件摘要，例如：
  - 系统开始处理目标
  - 选中了什么动作
  - 为什么停下
  - 需要用户做什么
  - 一次关键执行成功或失败
  - 产生了什么关键结果
  - 下一步准备做什么
- 完整的 workflow audit 继续保留在 Trace / Debug 区，供需要深入排查时查看。

原因：

- 用户在主区域要看的是“故事线”，不是“日志流”。
- 如果把所有 audit 事件原样搬进时间线，页面很容易重新退化成 debug 面板，只是换了一种排版。

备选方案：

- 主时间线严格展示全部 workflow audit，并完全按时间排序。

不选原因：

- 信息密度过高，会冲淡 stop reason、next step 和人工介入点这些真正高价值的信息。

### 9. run result 首版使用“摘要 + 关键字段 + 详情入口”的卡片粒度

决定：

- 时间线中的 run result 首版不只显示一句话，也不直接展开完整 manifest。
- 每张 run card 至少显示：
  - 工具名
  - 执行状态
  - 一句结果摘要
  - `run_id` 或等价可追踪标识
  - 1 到 3 个关键结果字段，例如主要产物、关键失败原因、是否生成 report / artifact
- 更完整的 manifest、artifact refs 和原始输出，继续放在 Run Detail 区域。

原因：

- 如果只有一句摘要，用户往往仍然不知道这次运行到底完成了什么。
- 如果直接把 manifest 全量摊在时间线里，会打断叙事节奏，让主时间线变得过重。

备选方案：

- 时间线里只放一句“某个工具已完成/失败”。

不选原因：

- 信息不足，用户仍然需要频繁跳转到 Run Detail 才能判断这次运行是否重要。

另一种备选方案：

- 时间线里直接展开 manifest 的关键 JSON 结构。

不选原因：

- 会让主时间线重新充满技术细节，削弱“像在协作”的体验目标。

### 10. 验证阶段加入非常轻量的“系统旁白”模板来统一口吻

决定：

- 在无桥梁版本验证阶段，加入非常轻量的系统旁白模板，用来统一不同 `stop_reason` 下的主文案口吻。
- 这些模板只负责“把已有事实说顺”，不新增新的事实来源。
- 首版优先覆盖：
  - `awaiting_approval`
  - `needs_input`
  - `blocked`
  - `completed`
  - `max_turns_exceeded`

原因：

- 用户感受到的“对话感”，很大一部分来自语气是否连续、是否像系统在持续汇报。
- 这类模板成本低、收益高，适合放在验证阶段先判断是否已经足够改善体验。

备选方案：

- 完全不加统一口吻模板，只直接显示各字段原始内容。

不选原因：

- 即使底层字段已经齐全，不同状态的表达仍然可能显得松散，降低整体协作感。

另一种备选方案：

- 做更像聊天助手的长段自然语言生成。

不选原因：

- 这会过早把验证推向“桥梁层”或“对话生成层”，超出当前 change 的范围。

### 11. 为高价值事件定义稳定优先级，避免不同 episode 的主时间线节奏漂移

决定：

- 首版为主时间线中的高价值事件定义一组稳定优先级，而不是让页面按“拿到什么就显示什么”的方式自由排列。
- 建议首版优先级从高到低为：
  - 当前 stop reason / 为什么停下
  - 当前需要用户做什么
  - 当前 selected action
  - 最近一次关键执行结果
  - 最近完成的关键里程碑
  - 其他辅助事件摘要
- 同类事件在主时间线中优先只保留最近且最相关的一条，其余事件继续放在 Trace / Debug 区。

原因：

- 如果没有稳定优先级，不同 episode 很容易出现时间线节奏忽前忽后、重点飘移的问题。
- 用户对页面的熟悉感，很大一部分来自“每次打开页面时重点都摆在相近的位置”。

备选方案：

- 不定义优先级，完全由当前 snapshot 中有哪些数据来临时决定顺序。

不选原因：

- 会导致主时间线缺乏稳定阅读节奏，降低验证结果的可信度。

### 12. run card 的关键字段按工具类型做轻量微调，而不是完全统一或完全定制

决定：

- run card 首版采用“两层字段”策略：
  - 所有工具统一显示通用字段：`tool`、`status`、`summary`、`run_id`
  - 再按工具类型轻量补充 1 到 2 个更有判断价值的字段
- 这类工具类型微调首版以高频工具为主，例如：
  - `fpocket`：主要产物、是否生成可进一步查看的 pocket 结果
  - `vina`：关键评分摘要、主要 pose / result 产物
  - 预处理工具：是否生成后续步骤可直接消费的输出文件

原因：

- 如果所有工具都严格只显示同一组字段，很多卡片会显得过于抽象，不够有用。
- 如果每个工具都完全单独定制字段，又会让首版实现过重，也不利于保持时间线整体一致性。

备选方案：

- 所有 run card 完全使用同一组字段，不做任何工具类型区分。

不选原因：

- 信息会过于平，用户很难一眼判断这次 run 对当前决策到底重要在哪里。

另一种备选方案：

- 每个工具都设计一套专属 run card。

不选原因：

- 实现成本高，而且会让首版验证偏离“先验证整体协作感”的目标。

### 13. “系统旁白”模板首版先放在 Web Host 侧组织，口吻稳定后再考虑下沉 runtime

决定：

- 首版的轻量系统旁白模板先由 Web Host 侧组织。
- runtime 继续提供事实基础，例如 `stop_reason`、`progress_summary`、`plain_language_explanation` 和 `next_step_suggestion`。
- 如果这套口吻在验证后证明稳定、并且 CLI 或未来 workbench 也需要复用，再考虑把它下沉为 runtime 可复用的展示辅助语义。

原因：

- 这次 change 的目标首先是验证展示方式，而不是立即抽象一层跨界面的 narration contract。
- 先放在 Web Host 侧更便于快速试错和调整口吻，不会过早把展示文案固化进底层契约。

备选方案：

- 一开始就把系统旁白模板定义为 runtime 的正式输出契约。

不选原因：

- 过早下沉会增加调整成本，也容易把验证阶段的 UI 文案选择误固化成底层结构。

### 14. 主时间线采用“当前状态优先层 + 最近历史事件流”的轻量双轨组织

决定：

- 首版时间线在视觉和信息组织上，轻度区分两类内容：
  - 当前系统状态消息
  - 最近历史事件消息
- 其中：
  - “当前系统状态消息”负责明确回答：系统现在停在哪、为什么停、当前最推荐用户做什么
  - “最近历史事件消息”负责说明：系统是怎样走到当前状态的，最近完成了哪些关键动作
- 首版不做复杂的双栏或双时间轴实现，而采用更轻的方式，例如：
  - 主时间线上方固定一个当前状态卡 / 当前系统消息
  - 下方再继续展示最近历史事件流

原因：

- 如果把“现在”与“刚刚发生过什么”完全混在同一层级，历史事件很容易冲淡当前最关键的卡点信息。
- 用户进入页面后，首先应该立刻看懂“我现在该不该介入、该做什么”，而不是先花时间回放历史。

备选方案：

- 所有消息都混在一条完全平级的时间线里。

不选原因：

- 虽然实现简单，但用户更容易被历史事件吸引，导致当前 stop reason 和 next step 不够突出。

另一种备选方案：

- 一开始就实现严格意义上的双轨时间轴或双栏交互布局。

不选原因：

- 对首版验证来说过重，会把重点从“是否更像协作”转移到更复杂的布局工程。

## Risks / Trade-offs

- [风险：只是把页面换个排版，并没有真正改善理解成本] → 用时间线项的因果顺序和就地操作来强化“连续感”，而不是只改样式。
- [风险：时间线派生逻辑散落在模板里，后续难维护] → 在 Web Host 内集中构建一个 timeline view model，再统一渲染。
- [风险：部分状态很难自然叙事化] → 首版只覆盖最关键的 workflow 节点，不追求把所有原始事件都翻成自然消息。
- [风险：主时间线和 debug 视图信息不一致] → 两者都从同一份 snapshot 派生，避免复制状态。
- [风险：用户因为没有 chat 输入框而仍觉得“不像对话”] → 这正是本次验证要回答的问题；若仍明显不足，再进入桥梁层设计。

## Migration Plan

1. 在 `apps/enzyme-web-host` 中抽出 timeline view model 组装逻辑，基于现有 snapshot 派生消息项与卡片项。
2. 重组主页面布局，让 conversation-style timeline 成为主操作区。
3. 把 pending gate / interrupt / selected action / recent run 迁入时间线卡片，并把相关操作表单嵌入卡片。
4. 在页面结构和卡片模型中预留未来 `mcp-structure-workbench` 的宿主接缝，但不提前实现其本体。
5. 保留并下沉 Debug / Trace / Raw State 区域，确保审计和排障能力不丢。
6. 更新 Web Host 测试，验证关键状态下的时间线内容与操作入口。
7. 更新 playground 说明，明确这次验证想观察的体验点。

回滚策略：

- 由于不新增新的真源和新的持久化模型，回滚只需要恢复 Web Host 页面组织方式即可。
- runtime、project memory、workflow 状态和已有 HTTP 动作接口都不需要回滚数据。

## Open Questions

- 除了 `fpocket`、`vina` 和预处理工具，首版是否还需要为其他高频工具补专门的 run card 字段？
- 如果后续 CLI 也希望复用“系统旁白”口吻，应该采用共享 helper、共享模板数据，还是再下沉成 runtime 字段？
