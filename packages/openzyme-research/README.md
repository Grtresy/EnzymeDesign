# openzyme-research

`openzyme-research` 是 provider-neutral Research Plugin。它拥有 Research request、bounded unit、
provider receipt、source/evidence、invocation state、worker、projection 和显式 publication link；不拥有
Session、Task、Approval、Agent runtime 或发布真值。

当前已实现：

- exact `openzyme_plugin_manifest@1` 与纯 locator entry point；
- closed `ResearchProviderDescriptor` 将 web、document、browser 三类 Provider Adapter 统一为
  exact `dispatch/reconcile` contract，安装或 import 本身不会选择 Provider；
- `deep_research.start` 的 Plugin-owned `ToolSpec`/runtime；
- `openzyme.research@1` 的独立 projection contract、显式 runtime surface builder、Session-scoped
  稳定游标分页与 bounded source/publication facts；projection digest 不复用 tool contract digest；
- worker 驱动的有界 dispatch、ControlledOperation admission/observe/reconcile 和 source-bound receipt；
- provider response 丢失时 `dispatch_in_doubt`，不重发、不换 Provider、不 fallback；
- provider transcript 只保存有界来源事实，不生成 publication、Task evidence、科学采用或 Task terminal；
- Agent 只能在 workspace 中写入结果并显式发布后，以 `RevisionPathRef` 链接不可变交接。

Tavily 实现位于 `openzyme-research-tavily`；PubMed、Semantic Scholar 与 literature quorum 位于
`openzyme-science-research`。基础 Research wheel 不包含 Tavily SDK、科学数据库或模型框架依赖。

旧 `openzyme-engines` Deep Research 第二权威和 Core `task.kind == "research"` planner 已退出活动
workspace；`openzyme_domain.research_contracts` 兼容模块、Domain 顶层别名以及旧 Core 的
summary/evidence/source/gap repository surface 也已删除。历史物理表只保留为离线迁移输入，不能作为
current Research mutation authority。EnzymeDesign Distribution 能构建 active exact graph；这些 target runtime
surfaces 只有在 exact mounted surfaces 中才启用。manifest active 不等于某个 Session 已获得 affordance，
generic Host 不会补造 Deep Research engine。
