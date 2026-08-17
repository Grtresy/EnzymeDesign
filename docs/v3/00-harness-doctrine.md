# V3 Harness Doctrine

## 核心原则

agent 应保留策略自由；harness 要把世界的真实约束忠实、结构化、低摩擦地呈现出来。

harness 不替 agent 选择研究路线、合并策略、HPC placement、失败处置或何时完成任务。它负责
把身份、权限、owner、lease/fence、文件状态、revision、approval、effect certainty、deadline、
quota 和错误语义变成可检查的机器合同。

## Harness 必须拥有

- canonical session/task/lane/protocol/approval/runtime state；
- repository binding、agent workspace generation、capability lease 和 credential scope；
- private checkpoint、immutable publication、Git LFS closure 与 revision path verification；
- controlled-operation、continuation、external job/result 的 durable lifecycle；
- mutation writer/quiescence、scientific attempt/selection/adoption/deliverable 的权威状态；
- bounded public projection、closed error 和 provenance event。

## Harness 不得拥有

- agent 的领域策略或隐藏 plan；
- prompt、浏览器 state、临时文件树中的第二套业务真状态；
- 对未知 external effect 的乐观推断；
- task terminal、scientific conclusion 或 GO/NO-GO 的隐式推导；
- ambient credential/path、自动重试、silent fallback 或旧 contract 翻译。

## 公开动作与事实分离

command 表达意图，receipt/observation 表达事实。以下事实必须分开：

- message accepted 与 runtime turn executed；
- task delegated 与 recipient ran；
- process exited 与 external effect settled；
- revision published 与 report/scientific file adopted；
- scientific attempt closed 与 task completed；
- source code implemented 与 deployment migration executed。

任何 reducer、projection 或 supervisor 都不能将这些边界折叠。

## Fail-closed

unknown 是结构化状态，不是 negative 或 permission。参数错误应返回 model-readable tool error；
provider、Git、runner、schema 和 receipt drift 显式失败。恢复只在 owner、phase、effect 和
idempotency identity 都可证明时进行。

## 有界执行

一次 request、signal claim、runtime command 或 worker slice 都有明确 step/time/budget。HTTP
线程不持有 LLM、provider、Git、sandbox 或 HPC wall time。长流程通过 durable state 和下一次
claim 继续；bounded 结束不自动改变 task 业务状态。

## 文件原则

agent 在自己的 native workspace 中读写文件；共享只通过 immutable revision/path。大文件是
同一 revision 的 Git LFS object。harness 负责验证 closure 和授权，不为 agent 创建隐藏副本、
自动 staging 或通用 catalog identity。

## 验收原则

测试应验证不变量和边界，而不固定 agent 的具体策略序列。架构 qualification 覆盖 authority、
identity、world fidelity、strategy neutrality、reconciliation、restart fencing、supervisor
progress 和 wire contract。focused test 不能替代 mainline。
