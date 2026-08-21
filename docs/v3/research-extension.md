# Research Plugin 与 Provider Adapter

## Owner 与通信方向

`openzyme-research` 增加研究语义；Kernel 只提供 extension invocation、ControlledOperation、authority、
failure、continuation 和 publication application services。Agent 必须从当次 `ToolAffordanceSnapshot`
显式调用 `deep_research.start`，Kernel 不检查 `Task.kind`、不替 Agent 生成 brief，也不自动改变 Task 状态。

```text
Agent tool call
  -> Research Plugin admission/state
  -> Kernel ControlledOperation admission
  -> exact ResearchProviderPort binding
  -> Tavily/其他 Provider Adapter
  -> provider receipt
  -> Kernel observe 或 reconcile
  -> Research worker settlement/projection
```

Plugin 与 Adapter 不 import 彼此实现。Research manifest 的 tool requirement 是
`openzyme.research.provider@1`；Distribution 的 `research.provider` slot 选择 exact Adapter。可选 Adapter
未安装时 Host 可形成不含该 binding 的 epoch，Research 工具保持 blocked；若已安装但 manifest/config/secret
preflight 漂移则 fail closed，不能按“可选”忽略错误。

Research 合同用 closed `ResearchProviderDescriptor` 表达 web、document 和 browser Adapter 类型；
它们共用 exact `dispatch/reconcile` Port，但只有 Distribution manifest 显式选中的 Adapter
才能形成 route。当前 EnzymeDesign 只选择一个 optional Tavily slot，未声明 Browser fallback。

## 身份、状态和失败

Research request 最多八个 unit，每个 provider dispatch 绑定唯一 operation ID、request/intent digest、
provider/route、deadline、Session/actor authority。receipt 绑定 source ID、公共 locator、content digest、
retrieved time 和 response digest。

已知 terminal provider response 使用 observe；请求可能已被接受但响应丢失时进入
`dispatch_in_doubt`，后续 worker 只调用 exact provider 的 reconcile，不新建请求、不切 Tavily/Browser、
不改 query。provider absence、rate limit、schema drift 和私有 locator 各自保留 typed blocker/failure。

## 文件交接和非终态边界

provider transcript、source count、Research `COMPLETED` 都不是共享文件或 Task evidence。Agent 若要交接研究
摘要，必须写入自己的 workspace、形成 clean checkpoint、显式 publish，再把 exact `RevisionPathRef`
链接到 Research invocation。后续 private dirty state 不改变该不可变引用。

Research settle 不调用 `task.finish`，也不产生 scientific adoption。科学文献的 PubMed/Semantic Scholar
来源政策和 quorum 由 `openzyme-science-research` 拥有；基础 Research 不决定科学证据是否充分。

## 当前实施状态

Plugin、Tavily Adapter、可选 Adapter selection 和 science-research contract 已有 non-live 单元测试。
`openzyme-engines` Deep Research 源码和 Core task-kind planner 已从活动 workspace 移除；通用 Runtime
不再导出 Research tool/provider seam，基础 Host foundation 也不再按环境变量创建 Tavily 或 bio service。
两个 Distribution manifest 已是结构上可激活的 `active`，但 Host 尚未通过 exact
startup proof/epoch 挂载 target Plugin runtime，因此本文不声称已完成生产 cutover 或
live Provider qualification。
