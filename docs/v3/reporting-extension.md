# Reporting Extension

`openzyme-reporting` 是报告语义的唯一目标 owner；它不是 Kernel、Standard Adapter 或 EnzymeDesign 专属逻辑。
Standard 可以完全不安装 Reporting，EnzymeDesign Distribution 则可以把 exact Reporting manifest 列为 required。

## 身份与组合

Plugin ID 为 `openzyme.reporting`，state namespace 为 `openzyme_reporting`。component manifest 固定 tool、HTTP
route、projection、UI renderer、worker、finish validator、schema、migration 与 transaction participant
catalog identities。Python entry point 只返回 locator；只有显式 Distribution selection、wheel/manifest/digest
验证和 deployment activation 成功后，Kernel 才能 mount runtime bundle。环境中可 import 的包不会成为 ambient
capability，既有 Session 也不热切换 Plugin 或 renderer。

当前源码状态是 `target_implemented_not_cutover`：目标 runtime surfaces 和 tests 已存在，Core 已停止
注册旧 report tools、注入 restore/prompt facts、解析 report evidence 或持有 legacy repository writer；
EnzymeDesign non-live application root 已在 read-only startup proof 后 exact mount 这些 surfaces。`session_report_*`
rows 仍只作为 offline historical adoption 输入。旧
`file_workspace_public@1` 仅保留历史 closed shape，report collection 固定为空，不是 current projection。
因此安装 wheel 仍不得 ambient 激活目标 manifest。两张旧物理表只由 Store schema 和 Reporting 内的
legacy-only reader/repository 为 migration proof 保留，Core 不再注入或调用它们，也不会与 target participant
双写。

## 文件与状态模型

报告正文只存在于 Agent workspace。共享报告必须先由 Agent 显式 checkpoint/publish，随后 Reporting 才登记
完整 `RevisionPathRef@1`；只接受 file/LFS-file，拒绝 directory、private path、dirty content、Host path、URL
或内联 Markdown/HTML/PDF bytes。后续 private workspace 编辑不会改变既有 ReportVersion。

Reporting namespace 只保存 bounded metadata：draft、immutable ReportVersion、render receipt 与 validation
receipt。版本 1 没有 predecessor；后续版本必须显式指向 exact latest predecessor，禁止覆盖旧版本或自动选择
supersession。render receipt 绑定 source report digest、renderer ID/contract digest 与 immutable output ref；失败
只有 safe failure code，private log 进入 common private diagnostic。

Plugin transaction participant 只接受一个 closed `upsert_reporting_records` command，一次最多两个 entity，以
expected state version 做 CAS，并受 read/mutation/payload/time budget 限制。它使用 Store 注入的
`ExtensionStateReader/Writer`，不接收 raw connection，不在事务内 render、publish、网络访问或写 Core state。
Plugin-facing `ReportingLifecycleToolApplication` 先用窄 `get_session_record/list_session_records` query 解析
draft、版本链和 render source，再由 `ReportingStateMutationApplication` 把调用面限制为 exact
`KernelCommandContext` 加一至两个 closed records，并且只依赖 Kernel 公共
`ExtensionStateApplicationService`。Kernel 在 participant 执行前重验
Session composition pin、extension/capability-binding digest、owner、authority generation 与 fence；旧 Core
report publication-link helper 已删除，唯一实现位于 Reporting。

## 通信面

Agent-facing tools：

- `report_draft.get`：读取 bounded metadata；
- `report_draft.update`：登记/更新 draft metadata，可链接已发布 RevisionPathRef；
- `report.publish`：登记一个 immutable report version，不执行 workspace publication；
- `report.render.request`：选择 exact renderer 并排队显式 render，不做格式 fallback。

三个 mutation tool 都要求显式 `idempotency_key`。draft 更新使用 `expected_state_version` CAS；report correction
必须指定 exact latest predecessor；render request 必须绑定当前 immutable report digest。任何 cross-Session、
wrong-Agent、stale state/fence 或缺失 Plugin 都在 Store mutation 前拒绝。

同层 Plugin 不互相调用内部 service。需要 workspace publication/process 时，Reporting 声明 capability
requirement，经 Kernel resolver 得到 exact application service/route，再由被选 Adapter 执行。Reporting 不 import
Git/LFS、Podman、Host 或 Core repository。HTTP 只读 route 和
`ReportingExtensionStateProjectionApplication` 返回同一授权、分页、byte-budgeted
`openzyme.reporting@1` safe view；`ReportingUiRenderer` 只能消费 exact section，Core reducer 不解析 Reporting
payload，renderer 必须匹配 exact section contract digest。

## Task finish 与失败语义

draft ready、workspace publication、render success、validation accepted 和 report published 是五个不同事实，都不
自动改变 Task。Task owner 显式调用 `task.finish` 后，Kernel 才把 immutable finish context 和 generic
`EvidenceRef` 交给 `openzyme.reporting.finish-validator@1`。validator 只读核对 Session/Task、report contract、
exact version/digest 与已有 accepted validation；缺失、歧义或 drift 返回 typed rejection，整个 finish mutation
保持 unapplied。validator 不现场 render、fetch、publish 或写 Core/Reporting state。

任何 renderer/manifest/schema/authority/ref drift 在 effect 前失败并报告 `no_effect`；renderer response loss 由
其受控 process/effect operation 保持原 certainty，只能 reconcile 同一 identity。禁止自动发布 private file、
选择另一 renderer/format、弱化 schema、重开 approval、回退旧 Core tool 或从报告存在推导 Task terminal。

## 迁移与验收

offline cutover 必须 inventory 旧两张表、quiesce 所有 writer、备份、转换为 namespaced records、验证 row/key/FK/
digest/version 等价，再激活唯一新 runtime authority。activation 之后 forward-only；失败时不允许 dual-write 或
online translation。focused tests 覆盖 manifest/runtime catalog、immutable file binding、body rejection、
namespace/CAS、exact validation 和 Task terminal separation；完整接受还要求旧 Core/Host/UI authority 删除、
`file_workspace_public@2` 接通及 layered non-live qualification 通过。现有 non-live integration test 已证明真实
Kernel admission、restricted participant 与 SQLite coordinator 的原子提交/回滚，以及未激活 Plugin 和 stale
fence 在任何 Store 写入前失败；它不构成生产 offline adoption 或 target activation proof。
