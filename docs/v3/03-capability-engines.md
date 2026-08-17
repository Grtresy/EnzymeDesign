# V3 Capability Engines

## 定位

capability engine 把 research、scientific calculation 或受控执行能力接入 harness。它可以使用
局部 graph、provider SDK 或受监督进程，但不拥有 session/task/approval/publication/scientific
selection 的顶层真状态。

## Tool contract

每个 model-visible tool 使用 canonical dotted name、closed JSON schema 和结构化 `ToolResult`。
provider adapter 可以临时映射不支持 dotted name 的 wire alias，但 response 进入 router 前必须恢复
canonical name；alias 不写入 event、trace、continuation 或 catalog identity。

参数错误返回 LLM 可读的 closed error。engine 不得：

- 静默修正参数或选择“能跑”的替代 route；
- 捕获 provider/runtime error 后伪装 success；
- 自动完成 task、发布 revision 或采用 scientific result；
- 从 ambient filesystem、credential 或 Host path 读取输入；
- 暴露已删除 artifact/staging helper。

## Research

research provider 输出 bounded observation、source provenance 和 safe summary。需要共享的研究正文
由 producer 写入自己的 workspace 并发布；research index 引用 exact published path。provider
transcript 或 engine document 不是 file publication，也不自动成为 scientific evidence。

## Pipeline SDK

`openzyme_pipeline` 当前提供纯 scientific calculation 模块和 `workspace_revision` job adapter。
executor 先在 native workspace 写源文件、形成 clean checkpoint/publication，再用 exact revision
request 提交 job。SDK 不提供通用 register/materialize/stage/fetch catalog。

`scientific.deliverables.finalize` 只接收 published revision path、producer adoption 和 format contract，
Host fresh-read immutable bytes 后形成 validation receipt。

## Process isolation

Podman/agent capsule 或局部 sandbox 是 process isolation 实现，不是共享文件模型。process callback
绑定 process epoch 和 scoped Host context；不能继承 session turn lease。process exit 只说明进程状态，
不说明 provider/HPC effect、publication、scientific closure 或 task terminal。

## External operations

通用 provider effect 由 `ControlledOperationExecution` 监督；HPC 由 revision-bound job lifecycle 监督。
引擎只提交 typed request 并观察 durable outcome。`dispatch_in_doubt` 只允许 reconcile；deadline 到期
不允许换 request identity 或重复 submit。

## Domain specialization

AOX/HMM 等垂直能力通过显式 workflow contract/registry 和 installed pure calculations 组合。generic
core 不增加 AOX 条件分支。formal scientific path 必须绑定 attempt admission、selection、producer
effect、published files 和 exact validation receipt；历史 campaign 不回填。
