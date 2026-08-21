# openzyme-reporting

`openzyme-reporting` 是报告生命周期、格式、渲染、验证与投影的目标 Plugin owner。Kernel 只拥有
immutable revision/path、generic evidence 和显式 Task finish，不拥有报告正文或报告业务状态。

## 当前迁移状态

本包已成为 `SessionReportDraftStatus`、`SessionReportStatus`、`SessionReportDraftRecord`、
`SessionReportRecord` 与 `ReportRef` 的唯一代码 owner，并保持原有枚举值、dataclass row shape、`to_dict()` 结果和
report version 默认值。仓内生产 caller 已直接 import `openzyme_reporting`；旧 Domain/Core compatibility
module、mixed revision aggregate 与 `ReportRef` 重导出均已删除。

当前包是 `target_implemented_not_cutover`。它已经提供 exact component manifest/locator、四个
`report*` ToolSpec/runtime、bounded projection、只读 HTTP extension route、render worker、finish validator、
`openzyme_reporting` transaction participant、logical migration bundle、UI renderer contract，以及
file-native report/render/validation DTO。导入包或 locator 不会打开 SQLite、运行 renderer、创建表或暴露工具。
`ReportingLifecycleToolApplication` 把四个 typed tool 转换为 exact Session/Agent/idempotency context 下的
bounded query 或 `ReportingStateMutationApplication` 写入；后者只接受 exact `KernelCommandContext`，并把 closed
record batch 交给 Kernel 的 `ExtensionStateApplicationService`。读取只依赖 Store 注入的
`get_session_record/list_session_records` 窄查询，Reporting 不接收 Store coordinator、Core repository aggregate、
raw SQLite 或 Host service。旧 report publication-link 判定也已从 Core 移入本包，Core 不再导出该
report-specific helper。

Kernel 不注册 `report_draft.*`/`report.publish`，基础 restore/prompt/world projection 也不读取或写入
Reporting 状态；旧 Core package 与 `openzyme_core.report_drafts` 已删除，不存在第二 writer。
`session_report_*` 物理表仍由 Store schema 为 offline historical adoption 保留，旧 `@1` shape 的 report 字段固定为空，
不得作为 current Reporting projection。Host 只可从 verified mounted surfaces 装配本 Plugin；Standard
明确不选它，EnzymeDesign non-live application root 已按 exact Distribution 选择并 mount。当前最终 source 的
真实 offline adoption/cutover 未获授权，且
任何 wheel 都不能 ambient 激活。

## 目标通信与状态边界

Reporting 通过窄 Kernel application services 查询已验证的 `PublishedRevision + RevisionPathRef`，并通过
受限 transaction participant 写自己的 namespaced draft/report state。它不能访问 Core repository、raw
SQLite、Host 私有 service，也不能把 Markdown/PDF/HTML 正文写回 control-plane metadata。

报告正文始终位于 Agent workspace，经显式 checkpoint/publication 后才可共享。draft ready、render
success、report publication 或 validator success 都不能自动完成 Task；只有 Task owner 显式
`task.finish` 时，Kernel 才调用 Reporting finish validator，且 validator 只返回 closed read-only result。

目标运行面固定如下：

- tools：`report_draft.get`、`report_draft.update`、`report.publish`、`report.render.request`；
- state namespace：`openzyme_reporting`，entity kinds 为 draft、report_version、render_receipt、validation_receipt；
- projection：`openzyme.reporting@1`，稳定 cursor、item/byte budget，不包含正文、Host/private path 或 renderer log；
- HTTP route：`GET /v3/extensions/openzyme.reporting/sessions/{session_id}`，只返回同一 bounded extension view；
- worker：`openzyme.reporting.render-worker@1`，必须使用 manifest 中 exact renderer identity；
- finish validator：`openzyme.reporting.finish-validator@1`，只读 exact report/version/digest/validation state。

`report.publish` 只是登记已经存在的 clean published `RevisionPathRef`，它固定返回
`workspace_publication_performed=false`。`report.render.request` 只创建显式 render work；renderer missing/drift
在进程执行前拒绝，禁止改用另一个格式或 renderer。任何 Reporting runtime result 都固定
`task_finished=false`。

`ReportingExtensionStateProjectionApplication` 只从 exact `openzyme_reporting` namespace 和 Session 构造四个
bounded collection；`ReportingUiRenderer` 只解释这一 section，不读取或写入 Core reducer。工具 mutation 必须携带
显式 `idempotency_key`；draft CAS、report supersession、render source digest 与 participant authority/fence 都在
任何状态写入前重验。

## Identity、lifecycle 与失败语义

- draft/report 绑定 Session、Task、owner、exact content revision/path 和 monotonically increasing report
  version；supersession 必须显式，不能覆盖旧发布版本。
- Session pin exact Reporting extension/schema/renderer digest。插件安装、升级或移除不在既有 Session 中
  热切换；需要新 Session 或后续明确的离线升级协议。
- dirty private path、unknown publication、path/blob/LFS drift、renderer/schema digest drift、validation
  failure 或 stale authority 都保持 blocked，并形成结构化、脱敏失败记录。
- 禁止自动发布 private file、从 summary/content_ref 字符串猜测真实文件、从 report existence 推导 Task
  completion、静默选择另一 renderer，或把旧 compatibility shim 当成第二个 state writer。

首轮迁移不重命名物理表。目标 Plugin 的 logical migration 使用 Store-owned generic extension state table，
不获得 raw SQLite connection；现有 `session_report_*` 表只在后续 offline adoption 中转换，不能 dual-write。
SQLite Store 的 owner-partitioned migration catalog 继续把这两张旧物理表的语义 owner 标为 Reporting，以便
dry-run/row-equivalence/rollback evidence 能精确闭合。non-live integration test 已覆盖真实 Kernel admission →
restricted participant → SQLite coordinator、stale fence/未激活 Plugin 的 pre-write rejection，以及 Core probe 与
Reporting state 的原子回滚；这不等同于生产 offline adoption 已执行。
