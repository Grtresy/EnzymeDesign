## ADDED Requirements

### Requirement: Web Chat Host 突出显示当前进度、停下原因和下一步建议
The system MUST 在浏览器主操作区域优先展示 workflow 当前进度、停下原因和下一步建议，而不是要求用户先阅读原始状态 JSON、完整 trace 或底层日志。

浏览器主视图至少必须显示：

- 当前 workflow 处于什么状态
- 系统最近完成了什么
- 当前卡在哪里
- 用户现在最应该做什么
- 当前是否需要用户立即介入

当 workflow 进入 `needs_input`、`awaiting_approval`、`blocked`、`max_turns_exceeded` 或等价状态时，浏览器主视图 MUST 把该原因放在显著位置。

#### 场景：浏览器用户打开一个等待输入的 episode
- **WHEN** workflow 因缺少必要输入而暂停
- **THEN** Web Chat Host 在主区域清楚显示“系统在等什么输入”
- **THEN** 用户可以直接看到补齐输入后的建议下一步，而不必先进入调试面板

#### 场景：浏览器用户打开一个等待审批的 episode
- **WHEN** workflow 因审批 gate 暂停
- **THEN** Web Chat Host 在主区域显示审批原因、当前卡点和建议动作
- **THEN** 用户无需先阅读原始 gate 数据也能理解为什么系统没有继续执行

### Requirement: Web Chat Host 将解释信息分成简明说明和技术细节
The system MUST 在浏览器中把决策解释分成“易懂说明”和“技术细节”两层，而不是把所有信息都挤进同一块展示区域。

浏览器界面至少必须支持：

- 在主操作区域展示简明说明
- 在 trace、debug 或等价展开区域展示技术解释
- 让两层解释指向同一个 selected action、停下原因或审批决定

简明说明 MUST 优先回答：

- 系统为什么这样做
- 这对当前目标意味着什么
- 用户接下来该做什么

首版简明说明 MUST 固定使用中文。

#### 场景：用户查看当前 selected action 的原因
- **WHEN** workflow 选中了新的下一步动作
- **THEN** 主区域显示易懂说明，帮助用户快速理解该动作的目的
- **THEN** 调试区域可以展开查看更详细的技术解释和相关状态依据

#### 场景：用户查看 blocked 状态的原因
- **WHEN** workflow 进入 `blocked` 或等价状态
- **THEN** 主区域先显示简明说明和建议动作
- **THEN** 技术细节仍可在展开区域查看，而不是占据主要操作空间
