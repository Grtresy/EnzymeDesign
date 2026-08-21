# openzyme-science

`openzyme-science` 是通用科学生命周期 Plugin 的目标语义 owner，而不是 OpenZyme Kernel
的一部分。软件开发、资料整理等非科学 Distribution 不需要安装或激活它。

## 当前迁移状态

本包已经成为以下纯契约的唯一代码 owner：

- scientific attempt authorization、admission、attempt、binding 与 closure；
- selection、operation disposition 与 effect adoption；
- immutable revision/path-bound scientific deliverable、bundle 与 validation receipt；
- `ScientificClosureRef` 与 scientific deliverable ref schema identity；
- 对应 closed 状态枚举、schema version、digest 和路径校验。

旧 `openzyme_domain.scientific_attempts`、`openzyme_domain.scientific_deliverables`
兼容模块与顶层别名已经删除；mixed revision aggregate 中尚存的 Science refs 仍按 temporary
re-export ledger 管理。仓内生产 caller 已直接 import `openzyme_science`。该迁移没有改变既有 schema version、序列化 row shape、物理表名
或状态含义。

当前 Plugin 是 `target_implemented_not_cutover`。exact manifest、6 个 lifecycle tool runtime、只读 route、
projection、UI renderer contract、worker、finish validator、logical migration、restricted transaction participant 和
通用 workflow contract registry 已落入本包。`ScienceLifecycleToolApplication` 将 6 个 typed tool 映射为
bounded read 与 `ScienceStateMutationApplication` 命令：调用方只能注入窄 `ScienceStateQuery`、exact
`KernelCommandContext` resolver 和受限 participant gateway，不能注入 repository aggregate、connection 或 Host
service；工具 receipt 返回 exact entity/version/digest 且固定 `task_finished=false`。另外公开
`ScientificPublishedFileReadPort` 与 `ScientificDeliverableFinalizationPort`，使垂直 finalizer 无需访问 Core
repository。旧 mixed Host 的 Science wiring、在线 `@1` writer 以及包内 raw-SQLite repositories 已删除；
`file_workspace_public@1` 只允许由后续离线迁移工具读取历史数据。本仓库没有执行真实 offline cutover，
Distribution 仍必须通过 exact manifest 和 deployment activation 显式启用 Science，不能因 wheel 已安装而形成
ambient capability，也不能双写或同时挂载同名工具。

纯只读 attempt lifecycle resolver、terminal-scope rollover projector、selection evaluator、文件采用与
deliverable finalization 仍由 Science 拥有，但目标在线 mutation 只有 namespaced participant 一条路径。
旧物理表的识别和迁移属于 SQLite Store 的离线 migration/proof，不是 Science runtime repository，也不能向
Plugin 注入 raw connection。

## 所有权与通信边界

目标实现只能通过 `openzyme-extension-spi` 的窄 Kernel application services 请求 Task、Approval、
Authority、Publication、ControlledOperation、Continuation、Failure 和 TaskEvidence mutation。Science
可以拥有 namespaced state，并可用受限 transaction participant 与 Kernel command 原子提交，但不能访问
`CoreRepositories`、raw SQLite connection、Host 私有 service 或其他 Plugin 的表。

Science 接收的是 Kernel 已验证的 identity、authority、published revision/path 和 controlled-effect receipt；
它不能从文件存在、job success、runtime idle、report publication 或 provider 文本推导科学采用、attempt
closure 或 Task completion。只有 Task owner 显式调用 `task.finish`，Kernel 才可调用 Science finish
validator；validator 只返回只读验证结果。

## 生命周期、不变量与错误语义

- Session 固定 exact Extension bundle。Science 的安装、升级或移除不能在 Session 中途静默生效；需要新的
  Session 或后续显式离线升级协议。
- formal attempt 绑定 Session、Task、campaign、workflow/root、scope、budget、authority 和 source identity；
  selection/adoption/deliverable/closure 不能跨 attempt、generation 或 Session 重用。
- scientific file 必须绑定 immutable publication、commit/tree、normalized path、Git blob/LFS identity、
  actual-byte digest、producer effect 与 adoption；当前暂时保留 Git-shaped revision contract。
- Science contract 不接受 artifact ID、Host/remote path、materialization locator 或 mutable workspace path；既有
  `ScientificDeliverableRef` 的 Git-shaped 字段就是当前获准保留的 revision/path contract，不是第二套 artifact
  abstraction。
- unknown effect、stale fence、missing adoption、publication/path/LFS drift、format failure 或 selection
  universe drift 必须保持 blocked，并形成结构化、脱敏的失败观察。
- 禁止自动重试未知外部效果、自动选择替代 provider/target、把缺失结果解释为 scientific negative、从
  receipt 自动完成 Task，或把历史 import 提升为 current adoption。

## Persistence 与兼容期

Science migration bundle 已声明 `openzyme_science` logical namespace，目标状态复用 SQLite Store Adapter 的
namespace-confined extension state，而不是再创建第二个 writer。旧表只可由离线 `@2` migration/proof 读取，
仍受 table-owner manifest、startup verifier 与 cutover 门禁约束；它不进入 `file_workspace_public@2`，也不授权
旧 namespace 成为第二套实现。

当前 namespaced 读取路径由 `ScienceExtensionStateProjectionApplication` 消费窄
`ScienceProjectionStateQuery`；Standard SQLite 的实现是
`SQLiteExtensionStateProjectionQuery`。该 Adapter 只允许 composition 明确授权的 namespace，按
Session 与 `(entity_kind, entity_id)` 稳定游标分页，不把 connection、SQL 或表名交给 Science。Science
投影再次校验 namespace/Session/entity kind，并只输出 attempts、selections、dispositions、adoptions、
deliverables、closures 与固定 `task_finished=false`。`ScienceUiRenderer` 只生成只读 extension view，既不合并
也不修改 Core UI state；renderer/section contract drift 会在 mutation control 启用前失败。

目标 mutation 集成测试已把真实 `ExtensionStateKernelApplicationService`、Science participant 与 SQLite
transaction coordinator 串联起来：inactive extension、stale authority fence 和 cross-Session context 都在 Store
前失败；participant 抛错时 Core probe 与 Science record 同时回滚。目标源码 writer 已收口，但尚未执行真实部署
activation，因此这不等于 production cutover 已发生。

完整目标边界见 [`docs/v3/science-extension.md`](../../docs/v3/science-extension.md)。
