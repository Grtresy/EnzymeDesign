## MODIFIED Requirements

### Requirement: Web Chat Host visualizes execution state and report artifacts
The system MUST 为活跃 episode 提供 agent state、recent observations、run lineage、待处理 feedback items 和生成的 episode 报告的浏览器面板，以便用户可以检查 agent 行为和输出，而无需手动浏览项目工作区。

当 agent workflow 启用 LLM backend 时，浏览器检查界面还必须包括：

- 当前 agent backend 名称
- 当前是否处于 fallback / degraded 状态
- 最近一次 sidecar 或 provider 错误摘要（若存在）
- provider / model / sidecar 版本等详细 provenance 信息的详情视图或调试视图入口

浏览器主操作区域 MUST 优先显示 backend 与降级状态，而不是把完整 provider/model 元数据放在主要 workflow 操作区的显著位置。

#### 场景：浏览器用户发现当前 workflow 已退回启发式 backend
- **WHEN** LLM sidecar 调用失败且 runtime 已回退到启发式 adapter
- **THEN** Web Chat Host 在主界面显示当前 backend 和 fallback / degraded 状态
- **THEN** 用户可以在详情视图中查看 provider/model 或错误类别等更细的 provenance 信息
