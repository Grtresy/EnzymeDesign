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

job request 必须携带 exact workspace generation、source ref、commit/tree、Git LFS closure、clean
observation、cwd/command/resources/target policy、execution identity 和 absolute deadline。Host supervisor
将修订准备为 Gitless compute tree；runner 只拥有 ledger、opaque handle、observation/cancel/terminal
receipt，不读取 Host checkout，也不扫描或声明 `expected_outputs`。结果文件留在 owner workspace，
由 agent 显式检查、提交和选择是否发布。

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

engine boundary 必须把原始异常保留为 Host 私有 diagnostic，并公开同一 `diagnostic_id` 的安全结构化
failure observation。任何 broad catch 都必须位于明确的 semantic boundary，区分确定的 pre-effect
failure 与 possible-effect failure，并以 `raise ... from exc` 保留 cause；不得静默 return、默认重试、
改选 provider/endpoint/mode 或把观察失败标成业务失败。

## Domain specialization

AOX/HMM 等垂直能力通过显式 workflow contract/registry 和 installed pure calculations 组合。generic
core 不增加 AOX 条件分支。formal scientific path 必须绑定 attempt admission、selection、producer
effect、published files 和 exact validation receipt；历史 campaign 不回填。
