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
credential locator scope。一个 operation 的结果不能扩大为 capability 全部 operations；route、target/provider、
source/build/config 任一漂移都需要新 plan 和新 receipt。

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
LLM occurrence 为 USD 5 告警/USD 25 硬上限，Tavily 为 USD 2/USD 10，两个 batch 的现金硬上限分别为
USD 100；告警不缩小 probe 或切换 route，只有 dispatch 前无法 reserve 硬额度才 `blocked_budget`。

`ExternalQualificationDryPlan` 固定 `max_retries=0`、`live_effect_authorized=false`，并闭合 effect allowlist、
same-attempt reconcile、cleanup、TTL 与 protected storage。SQLite 持久化实现由 `openzyme.store.sqlite` Adapter
拥有，Distribution 只依赖通用计划合同和 Port，不 import `sqlite3` 或拥有 canonical state。
每个 resolved unit 还单独绑定可选 credential locator；batch 级 locator 集合必须恰好等于这些 unit locator 的
并集。generic request、owner bridge 和 authorized router 任一 locator 不一致都会在 effect 前失败，不能把 LLM、
Tavily 或 HPC locator 交叉借用。
Identity preparation 同样逐 action 绑定 owner component、input schema、secret-safe fields、canonical
input-binding digest 和至多一个 credential locator；计划级 locator 集合与 action 并集不相等、调用方 input digest
漂移或 owner builder 不匹配时，必须在解析 credential 或产生 effect 前失败。

当前实现把 operator state root 固定为显式 locator：目录必须由当前 uid 持有、精确 `0700`、禁止 symlink；
`layout.json`、`credentials.json`、SQLite ledger 与私有 qualification 配置精确 `0600`。resolver 只接受 plan 中的
`credential.llm.micuapi.qualification`、`credential.tavily.qualification` 和
`credential.hpc.diannan.qualification`，不读取 ambient environment fallback。安全结果只记录 locator/version、
opaque digest 和 material-accessed 布尔值，不记录 token、key、私有路径或 raw stream。
`PlanOnlyQualificationBackendFactory` 在 exact
`ExternalQualificationOccurrenceAuthorization` 缺失、过期、batch/plan digest 不匹配或 identity 未闭合时，必须在
credential resolution 前返回结构化 blocker。当前人工 workflow 只生成 operator packet，不引用 secrets，也不构造
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
`docker.io/library/python@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3`、
当前 `uv.lock` digest 和 official source commit；构造代码不会自动 build。HPC action 只生成独立
`aox-qualification-diannan` 配置，保持 `activated=false`、`scheduler_submit_enabled=false`，使用 exact credential-bound
host/port（当前 `Diannan` 端口为 `22222`）、`ssh -F /dev/null`、`BatchMode=yes`、`IdentitiesOnly=yes` 与 exact
identity/known-hosts files；不覆盖当前 runner 配置。

Preparation success 写入 `ExternalIdentityPreparationResult` 和 protected SQLite ledger。effect-free rediscovery 验证每个
result 的 plan、authorization、owner、input 和字段覆盖后才生成新的 safe snapshot。随后必须重建 exact catalog：
`nonlive.locator.*` 不能进入 real plan，LLM/Tavily/HPC 改绑专用 locator，本地 Git/LFS 移除 credential placeholder；
因此 real unit digest 与 non-live readiness unit digest 有意不同。

本地 operator 入口分为三个命令，且不能互相替代：bootstrap 命令只创建 `0700` root 和 `0600 layout.json`；
authorization writer 只把操作员批准的 exact plan/batch/operator/window 规范化为带摘要的 JSON；Batch 1 executor 才要求
`OPENZYME_ALLOW_LIVE=1`。executor 会用当前 checkout 重建并逐字比对 packet 内的 preparation plan，在任何 mutation 前
一次性验证三个 exact locator 的 material kind/version/required fields，然后按稳定 occurrence identity 执行七个 owner
action。每个 terminal result 立即写入 protected SQLite；重启只恢复相同 plan 与 authorization 下已有的 exact result，
没有 ledger result 却检测到已有 Git/image/HPC state 时停止人工 reconcile，不重发或覆盖。完成后写出的
`prepared_not_qualified` packet 只含 secret-safe fields，并为下一次独立 qualification authorization 暴露新的 Batch 1
dry-plan digest。

当前源码已加入 authorization-bound exact-unit router、LLM/Tavily/公共 Bio HTTP typed bridge，以及 Git/LFS、
Podman、SSH、Slurm 和科学 Driver 的 owner binding guard。非 live 测试证明这些边界拒绝 hosted Git sync、未固定
image、错误 target/route/subject、raw scientific execution、credential locator 漂移和重复 dispatch。它们没有
构造真实基础设施 backend，也没有运行 HMMER/Vina/fpocket/preprocess；相应完整 live bridge tasks 仍保持未完成。

## 后续强制暂停点

当前必须在首次 Provider、Git mutation、container、SSH、Slurm、HPC 或科学程序 effect 前，把 exact
identity-preparation plan digest、batch 和 operator 交给操作员再次确认；preparation 完成后，真实 probe 还要
对重建的 qualification dry plan 另行确认。真实 qualification 完成后，在创建
`cut-over-enzymedesign-qualified-runtime` 或执行 adoption 前，还要再次确认部署环境、quiescence、迁移/备份、
rollback/forward-only 边界、监控、post-cutover smoke 与最终授权人。
