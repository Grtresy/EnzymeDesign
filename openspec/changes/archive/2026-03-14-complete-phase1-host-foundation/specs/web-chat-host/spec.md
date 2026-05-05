## MODIFIED Requirements

### Requirement: Web Chat Host visualizes execution state and report artifacts
The system MUST 为活跃 episode 提供 agent state、recent observations、run lineage、待处理 feedback items、workflow audit 摘要和生成的 episode 报告的浏览器面板，以便用户可以检查 agent 行为和输出，而无需手动浏览项目工作区。

浏览器检查界面必须包括：

- 当前 agent state 摘要
- 最近 selected actions / decision trace 摘要
- 最近 observations 和 run 列表
- 待处理的 feedback / approval 项
- 当前 episode 的报告视图或下载入口

当 agent workflow 启用 capability discovery 与 LLM backend 时，浏览器检查界面还必须包括：

- capability inspect 与相关 workflow audit 事件的 trace 或 debug 视图入口
- 当前 agent backend 名称
- 当前是否处于 fallback / degraded 状态
- 最近一次 sidecar 或 provider 错误摘要（若存在）
- provider / model / sidecar 版本等详细 provenance 信息的详情视图或调试视图入口

浏览器主操作区域 MUST 优先显示 workflow 状态、pending interrupts、gates 与 backend / degraded 状态，而不是把 capability inspect 细节或完整 provider/model 元数据放在主要 workflow 操作区的显著位置。

#### 场景：浏览器用户审查 agent 为什么改变行动路径
- **WHEN** 一个 episode 在多轮 observation 后切换了 strategy 或 selected action
- **THEN** Web Chat Host 显示最近 observations、decision trace 摘要、workflow audit 摘要和新的 working plan
- **THEN** 显示的信息与共享 runtime 生成的规范 agent state 和 run lineage 匹配

#### 场景：浏览器用户在调试视图中看到 capability inspect 事件
- **WHEN** 当前 episode 先 inspect 了某个 capability 再选择其具体 tool
- **THEN** Web Chat Host 在 trace 或 debug 视图中显示 capability inspect 与后续 tool 选择之间的关联
- **THEN** capability inspect 不会被提升成一个新的主操作模块而稀释主要 workflow 控制区域
