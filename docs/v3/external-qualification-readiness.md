# EnzymeDesign 外部资格就绪边界

本文描述真实外部资格验证之前的唯一 readiness 层。它回答“当前 source/composition 是否已具备安全、可重放、
fail-closed 地执行真实 qualification 的条件”，不回答真实 Provider、target、credential 或科学软件是否可用。

## 生命周期与声明

证据层固定为：

```text
selected
!= runtime_mounted
!= ready_non_live
!= qualified
!= cutover
!= live_occurrence
```

`ready_non_live` 必须同时记录 `external_effect_performed=false`、
`credential_material_accessed=false` 与 `fallback_performed=false`。它使用独立 schema，不能作为
`ExternalQualificationEvidence(lifecycle_claim=qualified)` adopt；运行时只接受 exact、未过期的 qualified fact。

## 六维资格单元

`ExternalQualificationUnit` 的业务 identity 是：

```text
capability_id
+ one operation
+ route_id
+ subject_kind/subject_id
+ source_digest
+ build_digest
+ configuration_digest
```

同一对象还绑定 component/Driver、contract、qualification spec、validator、expected result schema 与可选
credential locator scope。`external_qualification_unit@2` 还把该 capability 的 exact `subject_version_spec` 纳入
unit digest；软件 subject observation 必须提供 capability-specific canonical version field，并在 effect-free discovery
中满足该 spec，否则 observation 降为 `partial` 或 `drifted`。一个 operation 的结果不能扩大为 capability 全部
operations；route、target/provider、source/build/config 任一漂移都需要新 plan 和新 receipt。

product catalog 不复制 Distribution 选择。builder 先激活当前 exact composition，再从 selected Adapter manifest、
Plugin `QualificationSpec` 与 Driver binding 读取 component/source/build/contract identity；catalog blueprint 只描述
产品所需的 operation/profile，不得替换或新增 component selection。

## Profiles

`base` 永远 required。`research-provider`、`hpc-primary`、`hmmer`、`docking` 与 `alphafold` 只有在 plan request
显式启用时进入闭包，但一旦启用就必须完整通过。未知、重复、missing、unexpected、collision 或 selected
external component coverage gap 都在 plan 创建前失败；“optional”不是失败后的跳过或 fallback。

## Probe、reconcile 与 credential

`ExternalQualificationProbePort` 只有 exact `dispatch(request)` 与 `reconcile(request)`。request 绑定 unit、plan、
attempt、input/schema、timeout 和 credential locator identity。`dispatch_in_doubt` 只能 reconcile 同一 attempt；
不能 redispatch、retry、换 route、换 Provider 或换 target。

non-live `RecordingQualificationProbeBackend` 不 import 网络、SSH、Podman 或 scheduler client，只消费 deterministic
fixture。它覆盖 success、typed auth/config failure、timeout-before-effect、schema mismatch、operation mismatch、
response-loss-after-terminal 与 unresolved reconcile。`RejectingQualificationCredentialResolver` 永不返回 material；
readiness 中出现 resolution attempt 本身就是 policy violation。

真实 credential 只能由后续 operator-authorized resolver 按 exact unit + locator + scope 解析 ephemeral material。
plan/receipt/public diagnostic 不保存 secret name/path/value，不扫描 ambient environment、default profile、相邻账号或
anonymous fallback。

## Receipt、diagnostic 与 admission

readiness receipt 一一绑定 plan/unit/backend/fixture/negative tests/operation/schema/timestamp/diagnostic 和 effect flags。
独立 verifier 重算 digest、检查时效与 1:1 闭包。公共 failure 包含稳定 code、component/phase、unit/plan、effect、
mutation/fallback、retry/reconcile policy、operator action 与 `diagnostic_id`；private diagnostic 以同一 ID 保存
bounded cause context。

`EnzymeDesignExternalQualificationAdmission` 只呈现 exact qualified facts。多个分别合格的 route 会同时呈现给
Agent，harness 不代替 Agent 选择；某个 fact missing/expired/drifted 时只移除该 unit 并返回
`blocked_qualification`，不把 occurrence 切到其他 route/subject。

## CI 与人工边界

普通 PR/dev mainline 执行：

```bash
./scripts/check-external-qualification-readiness.sh
```

脚本清除已知 credential variables、设置 `OPENZYME_ALLOW_LIVE=0`，运行 focused suite 和 machine report verifier。
`.github/workflows/non-live-qualification-readiness.yml` 是自动 non-live workflow，不引用 secrets 或 live markers。

`.github/workflows/external-qualification-live.yml` 当前只有 `workflow_dispatch`，且唯一 mode/profile 是
`plan-only`/`not-authorized-yet`；它不会调用真实 backend。未来 live tests 必须同时满足 marker/profile opt-in、
`OPENZYME_ALLOW_LIVE=1`、受保护 environment、exact credential locator、预算与 operator approval。缺任一条件不得把
skip、recording result 或普通 integration pass 计为 live pass。

## 真实资格 dry plan

后续 change `qualify-enzymedesign-external-capability-routes` 已进入 plan-only 实施。它不会把上述 readiness receipt
就地升级，而是从显式安全快照建立 `ExternalSubjectIdentityObservation`，将每个 unit 重新绑定到真实 Provider/target
subject closure。`resolved` 只表示非 secret identity 字段闭合；`partial`、`missing`、`unsafe`、`drifted` 都形成
带影响 unit、候选方案与唯一推荐项的 `ExternalIdentityGap`。没有操作员对当前 gap digest 的明确 decision，builder
不得自行选择候选项。

资格分两批：Batch 1 固定包含 `base + research-provider + hpc-primary + hmmer + docking`，Batch 2 仅含
AlphaFold。每批独立绑定 source、identity、unit、budget、authorization 与 verdict。预算是防循环/失控的宽松熔断：
Batch 1 现金为 USD 100 告警/USD 250 硬上限；LLM occurrence 为 USD 50/USD 100 且 request count 为
10/20，Tavily 为 USD 20/USD 50；Git payload 为 32/64 MiB，Podman 时间为 3000/3600 秒、内存为
2048/4096 MiB，Slurm CPU-time 为 120/180 分钟。告警不缩小 probe 或切换 route，只有 dispatch 前无法
reserve 硬额度才 `blocked_budget`。

`ExternalQualificationDryPlan` 固定 `max_retries=0`、`live_effect_authorized=false`，并闭合 effect allowlist、
same-attempt reconcile、cleanup、TTL 与 protected storage。SQLite 持久化实现由 `openzyme.store.sqlite` Adapter
拥有，Distribution 只依赖通用计划合同和 Port，不 import `sqlite3` 或拥有 canonical state。
每个 resolved unit 还单独绑定可选 credential locator；batch 级 locator 集合必须恰好等于这些 unit locator 的
并集。generic request、owner bridge 和 authorized router 任一 locator 不一致都会在 effect 前失败，不能把 LLM、
Tavily 或 HPC locator 交叉借用。
首次 discovery CLI 默认保留 non-live locator，用于尚未执行 preparation 的安全快照。对既有
`prepared_not_qualified` snapshot 因新 source/recipe/contract 重建 gap 或 dry plan 时，必须显式使用
`--exact-prepared-locators`；该模式采用资格 locator，并将 local-only Git/LFS locator 精确设为 `None`。两种模式
不可隐式猜测或互相 fallback。operator packet 必须记录 `locator_binding_mode = nonlive_initial | exact_prepared`，
preparation executor 按同一模式重建 embedded plan；字段缺失、未知或重建 digest 漂移均在 credential resolution 与
effect 前 fail closed。prepared snapshot 若误用 non-live Git locator 同样必须在构建期失败。
Identity preparation 同样逐 action 绑定 owner component、input schema、secret-safe fields、canonical
input-binding digest 和至多一个 credential locator；计划级 locator 集合与 action 并集不相等、调用方 input digest
漂移或 owner builder 不匹配时，必须在解析 credential 或产生 effect 前失败。

当前实现把 operator state root 固定为显式 locator：目录必须由当前 uid 持有、精确 `0700`、禁止 symlink；
`layout.json`、`credentials.json`、SQLite ledger 与私有 qualification 配置精确 `0600`。resolver 只接受 plan 中的
`credential.llm.micuapi.qualification`、`credential.tavily.qualification` 和
`credential.hpc.diannan.qualification`，不读取 ambient environment fallback。安全结果只记录 locator/version、
opaque digest 和 material-accessed 布尔值，不记录 token、key、私有路径或 raw stream。
`PlanOnlyQualificationBackendFactory` 在 exact
`ExternalQualificationOccurrenceAuthorization` 缺失、已撤销、operator/batch/plan digest 不匹配或 identity 未闭合时，必须在
credential resolution、预算预留和 owner bridge 构造前返回结构化 blocker。qualification authority 不设置 wall-clock
有效期，只能启动或恢复同一 exact occurrence；protected ledger 中已有的 terminal unit 必须直接恢复，不得 redispatch。
当前人工 workflow 只生成 operator packet，不引用 secrets，也不构造
真实 backend。

operator 选择 identity candidate 后，若 subject 尚需建账号/locator、创建本地隔离 Git/LFS repository、build/pull
image 或补齐 HPC profile/inventory，必须先生成独立 `ExternalIdentityPreparationPlan`。它绑定当前 gap/decision、
batch、action、预算、cleanup 与 protected storage，但不会把 observation 标为 `resolved`。首次 preparation effect
需要绑定 exact plan/batch/operator、无 wall-clock 截止时间的持久一次性
`ExternalIdentityPreparationOccurrenceAuthorization`；已完成 action 只能恢复不得重新派发，authority 可由 exact 私有证据显式撤销。
完成后重新做 effect-free identity discovery，才能重建
qualification dry plan。Preparation authority 不能替代 qualification occurrence authority。

当前 Git 决策只覆盖本地隔离 repository/LFS endpoint，并显式禁止 GitHub 或其他 hosted sync。本地 receipt 以后也
不能扩大成 hosted Git service 资格。科学软件的 image/version/inventory 是 subject/resource identity；真实 HMMER、
Vina、fpocket、preprocess 或 SSH/Slurm smoke receipt 属于 qualification evidence，不能反过来作为 dry-plan identity
前置条件。

Batch 1 preparation 精确为七个 action：LLM locator、Tavily locator、本地 Git/LFS repository、`base`、`hmmer`、
`docking` 三组镜像，以及一个聚合的 `Diannan/3090` HPC identity action。三组镜像 recipe 绑定
`docker.io/library/python@sha256:356b0d18f9385f4bdcc673af60e1e64c9d1504952e4ec36ee32044c722a6bc4e`、
当前 `uv.lock` digest 和 official source commit；构造代码不会自动 build。HPC action 只生成独立
`aox-qualification-diannan` 配置，保持 `activated=false`、`scheduler_submit_enabled=false`，使用 exact credential-bound
host/port（当前 `Diannan` 端口为 `22222`）、`ssh -F /dev/null`、`BatchMode=yes`、`IdentitiesOnly=yes` 与 exact
identity/known-hosts files；不覆盖当前 runner 配置。

若 repository-owned output image 已存在，preparation 不覆盖也不重建：只有 Podman 同时返回 immutable image digest、
与当前 recipe digest 完全相等的 build label 及 `linux/amd64` platform 时，才以 `adopted-exact-existing` 恢复 identity；
任一字段不一致即 `qualification_existing_image_identity_mismatch`，禁止删除、重标记或 fallback。

image subject 的 safe projection 必须同时携带对应的 repository-owned recipe digest。effect-free rediscovery 会用
当前 checkout 重算该 digest：字段缺失时 projection 为 `partial`，与当前源码不一致时为 `drifted`；即使 immutable
image digest 仍存在，也不能据此生成 authorizable dry plan。recipe 改变必须使用新的 output image ref；旧镜像保留作
历史对象，不覆盖、不重标记，也不作为 fallback。

Preparation success 写入 `ExternalIdentityPreparationResult` 和 protected SQLite ledger。effect-free rediscovery 验证每个
result 的 plan、authorization、owner、input 和字段覆盖后才生成新的 safe snapshot。随后必须重建 exact catalog：
`nonlive.locator.*` 不能进入 real plan，LLM/Tavily/HPC 改绑专用 locator，本地 Git/LFS 移除 credential placeholder；
因此 real unit digest 与 non-live readiness unit digest 有意不同。

本地 operator 入口分为三个命令，且不能互相替代：bootstrap 命令只创建 `0700` root 和 `0600 layout.json`；
authorization writer 只把操作员批准的 exact plan/batch/operator 规范化为持久一次性、可显式撤销的带摘要 JSON；Batch 1 executor 才要求
`OPENZYME_ALLOW_LIVE=1`。executor 会用当前 checkout 重建并逐字比对 packet 内的 preparation plan，在任何 mutation 前
一次性验证三个 exact locator 的 material kind/version/required fields，然后按稳定 occurrence identity 执行七个 owner
action。每个 terminal result 立即写入 protected SQLite；重启只恢复相同 plan 与 authorization 下已有的 exact result，
没有 ledger result 却检测到已有 Git/image/HPC state 时停止人工 reconcile，不重发或覆盖。完成后写出的
`prepared_not_qualified` packet 只含 secret-safe fields，并为下一次独立 qualification authorization 暴露新的 Batch 1
dry-plan digest。

当前源码已加入 authorization-bound exact-unit router、LLM/Tavily/公共 Bio HTTP、Git/LFS、Podman、SSH、Slurm
的 owner operation bridge，以及 HMMER/Vina/fpocket/preprocess 的固定小型 workload、正式 Compute route 和
terminal validator。live coordinator 在 protected SQLite 中逐 unit 持久 outcome 与 safe receipt；重启只恢复 terminal
结果或同一 in-doubt attempt，无法安全恢复的 Provider attempt 稳定阻断，禁止 redispatch。Diannan scientific route
只使用 target 已安装软件，绝不安装、升级或重建远端工具；本地 route 只采用 preparation 已固定 digest 的 image。
非 live/fake-command 回归只能证明绑定、请求构造、状态恢复和失败语义，不能表述为真实外部资格已通过。

首次真实 Batch 1 occurrence 已终态裁决，不得复用 authority。它证明部分真实 route 可用，同时暴露了固定 Git branch、
不可写 `/data/openzyme` workspace、HMMER/fpocket output path、本地 docking image runtime dependency 与私有诊断投影问题。
修正后，Git publication ref 按 occurrence 隔离；HPC locator 的 `ssh_user`、`workspace_root`、`isolation_command` 必须在
SSH effect 前与 qualified helper identity 精确相等；cleanup resources 与逐 unit budget settlement payload 同 digest 一并
持久化，恢复时缺失即 fail closed。Vina 已采用 route-specific 双版本：Diannan HPC 固定 `==1.1.2` 与 legacy
`--log`/poses+log profile；本地固定 `>=1.2,<2` 与 modern 无 `--log`/poses-remark-derived score profile。
Plugin route requirement、Kernel admission、Driver workload/result digest 和 qualification subject 必须一致；任一路
漂移只阻断该 route，不能仅凭 SIF digest 进入 dry plan，也不能切换 route/profile 或 fallback。
HPC identity observer 现在把 HMMER/Vina/fpocket 的原始 version banner 规范化为单独的 canonical version 字段；
原始 banner 仍只进入 inventory generation digest。无法解析的 banner 返回
`qualification_hpc_software_version_unparseable`，不能以 opaque software fact 绕过版本约束。

后续真实 occurrence 还证明了 batch 级“全量重跑直到 44 项同时成功”会把独立 Provider/SSH 瞬态错误变成隐式
retry，并重复已经通过的付费或外部 effect。当前恢复合同允许新的 one-shot authority 在完整 dry plan 的上限内选择
exact 非空 failed-unit 子集；checkout source identity 与子集必须在首次 effect 前 create-once 写入 protected SQLite，
同一 authority 的任何 source/scope 漂移都在 credential resolution 前失败。subset occurrence 只说明所选 unit 是否闭合，
不得输出 batch `qualified`。独立 receipt-set verifier 才能跨多个 occurrence 选择同一 checkout source identity 与
dry-plan digest 下每个 unit 的当前 receipt，并逐份重验
authorization、occurrence scope、negative gate、budget settlement、cleanup、TTL 与 unit/subject/route/schema；缺一项即保持
`blocked_qualification`，且无论结果如何都仍是 `cutover=false`。

## 后续强制暂停点

当前必须在首次 Provider、Git mutation、container、SSH、Slurm、HPC 或科学程序 effect 前，把 exact
identity-preparation plan digest、batch 和 operator 交给操作员再次确认；preparation 完成后，真实 probe 还要
对重建的 qualification dry plan 另行确认。真实 qualification 完成后，在创建
`cut-over-enzymedesign-qualified-runtime` 或执行 adoption 前，还要再次确认部署环境、quiescence、迁移/备份、
rollback/forward-only 边界、监控、post-cutover smoke 与最终授权人。
