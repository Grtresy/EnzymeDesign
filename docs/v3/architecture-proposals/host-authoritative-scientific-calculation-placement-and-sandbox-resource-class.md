# Deferred: Host-authoritative scientific-calculation placement and sandbox resource class

Status: proposed; not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 `sandbox.exec` 是一个固定资源面的通用 agent-authored command。Core 将 command 的
`resource_policy` 记录为 CPU `2`、memory `2GiB`、PID `256`，Podman command 也固定使用
`--cpus=2 --memory=2g --pids-limit=256`；`s09.exec_policy.v2` 允许的单次 wall timeout
上限是 `3600s`。这些约束对隔离通用 Python 工作负载是清晰的，却没有表达“某个已注册科学计算
需要什么资源、应在哪里执行、当前 placement 实际能提供什么”。

本轮 AOX 真实数据把这个缺口变成了可观察问题。516 条 non-reference candidate 产生
132,870 个 pair。旧实现根据 `sched_getaffinity()` 看见的 CPU set 最多创建 16 个 worker，
但 affinity 不等于 cgroup CPU quota；在固定 2-CPU sandbox 中，agent 和计算代码都没有收到一份
Host-authoritative effective quota/placement receipt。16 个 runnable worker 因而可以持续竞争 2 CPU，
而不是得到真实 resource class 或在执行前选择更合适的已批准 placement。

现有
[Host-authoritative controlled-operation resource estimate proposal](host-authoritative-controlled-operation-resource-estimate-and-limit-snapshot.md)
解决的是 provider、runner、bio tool 等 **external controlled operation** 的 demand、limit、approval
和 usage。它不覆盖 `sandbox.exec` 内部的本地纯计算：本地 Python 函数不创建 controlled operation，
没有 per-calculation placement plan，也没有 Host/HPC execution receipt。把该提案简单扩写成“所有
command”会混淆 external effect quota 与 local scientific compute，因此本文件单独记录设计。

当前 Goal 只允许两项有界小修：

1. 为 AOX similarity 使用 exact direct-pinned Biopython `1.87` 与 NumPy `2.4.4`，并以 runtime
   version、algorithm、numeric-unit、trace/correction 和 tuple/oracle assertions 证明结果语义没有改变；
2. 让当前 worker-count helper 识别有效 cgroup CPU quota，而不再把 Host affinity 误报为可用
   sandbox 并行度。

这两项只改善当前固定 sandbox 内的实现与诚实资源感知。它们不新增 placement state、Host worker、
HPC route、approval schema 或通用 resource compiler，也不把正在运行的 diagnostic 追认为 cutover
evidence。下面的大架构在本 Goal 中 **不实现**。

## Current evidence and failure mode

1. Core 和兼容 Podman runner 都把 sandbox CPU 固定为 `2`，但 agent-facing calculation facts
   只投影 callable/contract；没有 effective CPU quota、memory、deadline 或 throttling facts。
2. command record 中的 `resource_policy` 描述整个 `sandbox.exec`，不是某一 calculation 的
   input cardinality、complexity、implementation 或 output contract。
3. `os.sched_getaffinity(0)` 可能返回 Host/cpuset 可见 CPU 数；Linux CFS/cgroup quota 仍可把容器
   限制为 2 CPU。仅以 affinity 决定 process count 会 oversubscribe。
4. AOX similarity 是 `openzyme_pipeline.aox_similarity` 内的本地 pure calculation。即使 Host 已有
   HPC runner 和 controlled bio-tool routes，agent 也没有一个 typed、receipt-bearing 方法把同一
   calculation 请求放到受控 Host worker 或 HPC。
5. agent 可以自行重写脚本或调用其它库，但那会改变 implementation identity，且可能违反 workflow
   pin。当前 harness 的真实选择实际上只有“在 2 CPU/3600s 内运行”或失败；这个约束没有在
   calculation capability 上低摩擦呈现。
6. 只提高全局 sandbox CPU/timeout 不是正确终态：它会影响所有 agent-authored command，扩大
   DoS 面，仍不绑定 calculation identity、approval、actual usage 或 output provenance。
7. 只把 AOX similarity 硬编码成 HPC command 也不正确：Host 会替 agent 改写 execution strategy，
   并在一个领域特例中复制 input/output/serializer/receipt 逻辑。
8. 一次只读 Biopython `1.87` C-backend diagnostic 已证明同一 packed tuple 规则可以精确重现，并在
   真实 1,000 pair 样本上约 `1.65s`。该 reference-validation 环境使用 NumPy `2.4.6`，与 cutover
   exact pin `2.4.4` 明确不同；这是选择当前小修的工程证据，不是可复用 benchmark、最终 dual-run
   receipt 或 live attempt evidence，也不授权版本 fallback。
9. 随后的真实 Podman `--cpus=2` 只读校准覆盖完整 516 sequences / 132,870 pairs：仅按 affinity
   启动 16 workers 用时 `168.766s`，按 cgroup quota 强制 2 workers 用时 `84.087s`，后者快
   `2.007x`；两者均产生 13,778 edges，nodes/edges/manifest 与纯 Python v3 逐字节相等，32-pair
   tuple digest也相等。该诊断证明oversubscription是resource-fact缺口，不是提高sandbox timeout的
   理由；该环境使用 Biopython `1.87` / NumPy `2.4.4`，其普通 `/tmp` receipt仍非sealed/cutover evidence。
10. 当前 formal private-cgroup Podman 已实证根 `/sys/fs/cgroup/cpu.max` 可见且准确表达 2-CPU quota，
    因此现有 AOX helper 对本轮 cutover path 的 cgroup clamp 不是 blocker。它没有遍历任意嵌套
    ancestor hierarchy，也不是通用 Host/container resource discovery；general-host/ancestor cgroup
    解析、effective limit 合并与 authoritative receipt 属于本提案未来实现范围，不能反向要求当前
    Goal 扩大 local helper。
11. 最终 current-backend comparison receipt
    `sha256:ace8baa8bfa070a621186d7b3db3acddcdf39abe26070e72270fc727b0017b5e`
    在同一 immutable image 中完成两次独立 exact-NumPy-`2.4.4` 2-worker full-set run：graph time
    `393.206478s` / `397.540161s`，均为 516 nodes、132,870 pairs、13,778 edges，raw outputs
    逐字节相同，且只规范化 pin-induced fields/manifest closure 后逐字节等于 old pure-v3。它确认
    当前 2-CPU/3600s resource class 足够；仍是 ordinary `/tmp`、`non_cutover=true` diagnostic，
    不实现本提案的 Host-authoritative placement receipt。

## Agent-harness principles

- agent 决定 **做哪个科学计算、用哪些已封存输入、参数是什么、在哪个 workflow 分支调用**。
- Host 忠实呈现可用 placement、实际 resource class、approval/cost 和 implementation identity；
  它不改变阈值、样本集合、pair 集合、算法、numeric mode、early-stop 或报告叙事。
- placement 是执行约束，不是科学策略。Host 只能在同一个已注册 calculation implementation 的
  等价 placement 集合内选择；若无法证明等价，就必须使用不同 implementation identity 并重新 pin。
- agent 可以声明 placement preference 或 resource demand，但不能自授 Host/HPC 权限、CPU、memory、
  timeout、GPU、network 或 credential。
- selected placement、resource class、runtime/dependency identity、approval 和 actual receipt 必须
  可持久化、可投影、可离线复核；不能只存在于 prompt、command line 或临时环境变量。
- 不可用、漂移、超限或 receipt 不完整时 fail closed。harness 不静默换 backend、不自动缩小输入、
  不串行 fallback、不拆 job、不提高 timeout，也不创建新的 approval 来“让它跑完”。
- local pure calculation 不应因为没有 external effect 就完全绕过 provenance；但它也不应被伪装为
  provider/runner controlled operation。两类 state 和 failure taxonomy 必须明确分型。

## Scope and relationship to adjacent proposals

本提案回答 **where/how much/under which execution identity**：

- [versioned scientific-calculation capability projection](versioned-scientific-calculation-capability-projection.md)
  回答计算合同、callable、serializer 和 implementation identity 是什么；
- 本提案从该 registry 读取已注册 calculation/implementation，编译 placement/resource/approval；
- [controlled-operation resource snapshot](host-authoritative-controlled-operation-resource-estimate-and-limit-snapshot.md)
  继续拥有 external provider/tool operation 的 limit/usage；
- [reproducible sandbox scientific dependency manifest](reproducible-sandbox-scientific-dependency-manifest-and-build.md)
  回答 selected runtime 中依赖 bytes、Python ABI 和 backend capability 如何可重建；
- [single-source HPC toolchain registry](single-source-hpc-toolchain-contract-registry.md) 与 runner receipt
  继续拥有真正 HPC execution packaging/attestation。

任何落地方案都必须引用这些 identity，而不是在 placement compiler 中复制科学常量、dependency
版本或 runner command template。

## Target invariants

1. 每个 scientific calculation command 绑定唯一 calculation contract、implementation、canonical
   params、input artifact ids/digests、output roles 和 source request identity。
2. Host 在 dispatch 前根据 versioned policy、可用 runtime、input facts 和 safe resource inventory
   编译唯一 placement plan；sandbox caller 不能提交 authoritative selected backend 或 resource grant。
3. placement 只能是闭集 `sandbox | controlled_host | hpc`。新增类别需要 schema/version bump，
   unknown string 不得按 sandbox 处理。
4. 每个 placement plan 绑定 exact resource class 与 effective limits；`affinity_count`、cpuset、CPU quota、
   memory、PID、wall time、scratch、process/thread concurrency 必须分字段表达，不能用一个 `cpu` 数字
   混写。
5. CPU quota 与 affinity 是不同事实。effective parallel capacity 由 Host versioned policy计算；
   fractional quota 使用整数 millicores/period facts表达，不能靠 float round 或 `os.cpu_count()` 猜测。
6. selected implementation 在该 placement 上必须是 registry 声明的 supported runtime/dependency
   identity。placement 改变且可能改变结果 bytes 时必须产生新的 implementation identity。
7. approval 绑定 exact plan digest。resource class、placement、input、params、runtime、dependency、
   implementation、output contract 或 cost class 漂移都要求 fresh approval 或明确失败。
8. execution receipt 绑定真实 runtime/worker/job、actual resource facts、input/output digests 和 terminal
   status。caller 自报的 timing、worker count 或 output path不是 authority。
9. Host/runner 只执行 registry 允许的 callable/entrypoint；agent-authored arbitrary Python 永远留在
   sandbox，不能借 `controlled_host` 获得 Host code execution。
10. output 只有经现有 artifact boundary seal/validate 后才可进入 task/report/scientific lineage。
11. no-network calculation 在三个 placement 都保持 no-network；placement 不能隐式获得 provider、
    credential 或 Host filesystem capability。
12. historical command/attempt 保留原 runtime identity，不从新 plan schema 反推或补写 authority。

## Proposed topology and ownership

```text
agent-authored sandbox source
  `-- typed calculation request via openzyme_pipeline
          calculation ref + params + sealed inputs + outputs + preference
                              |
                              v
Host ScientificCalculationPlacementCompiler
  |-- calculation/implementation registry
  |-- safe runtime health + dependency manifests
  |-- resource-class registry + availability/queue facts
  |-- permission/approval/cost policy
  `-- deterministic placement feasibility and plan compiler
                              |
                              v
scientific_calculation_placement_plan@1
  |-- exact request/implementation/input/output identity
  |-- selected sandbox | controlled_host | hpc placement
  |-- effective resource class + runtime/dependency identity
  `-- approval requirement + no-fallback policy
                              |
                    approved / no approval required
                              |
                              v
placement-specific executor
  |-- existing sandbox runtime
  |-- restricted Host calculation worker
  `-- runner-owned HPC calculation adapter
                              |
                              v
scientific_calculation_execution_receipt@1
  `-- actual resource/runtime/input/output/terminal closure
                              |
                              v
existing artifact catalog + task/report lineage + offline verifier
```

Ownership boundaries:

- immutable calculation contract/implementation record: scientific calculation registry；
- placement/resource class policy and safe runtime inventory: Host composition root 注入的 compiler；
- plan、approval link、command lifecycle、receipt references: canonical V3 control plane repository；
- sandbox/Host/HPC process lifecycle: placement-specific engine/runner adapter；
- artifact bytes/provenance: existing Host artifact boundary；
- strategy, branching and report interpretation: agent/team tasks，不进入 compiler。

Core 只能依赖 typed compiler/executor interfaces，不能 import Biopython、AOX 或 runner implementation。
Host compiler 也不能读自然语言 prompt 推断 calculation；request 必须来自 explicit typed SDK call。

## Agent request schema

建议使用 closed `scientific_calculation_request@1`：

- `schema_id`, `request_id`, `request_digest`；
- session/task/lane/agent/sandbox workspace/run/source snapshot identity；
- `calculation_ref`, contract digest, implementation digest；
- canonical parameter preimage/digest；
- sorted input artifact roles、ids、content digests、semantic cardinality facts；
- requested output roles、schema/serializer ids、empty-output policy；
- optional placement preference：闭集 `any | sandbox | controlled_host | hpc`；
- optional bounded demand hints such as expected pair/item count；
- idempotency key and call-budget identity。

request 不得包含 Host path、runner path、container name、SIF locator、CPU grant、memory grant、timeout
grant、queue、credential、raw shell command 或 approval verdict。input cardinality 必须由 Host 从 sealed
artifact 重算；caller 重复提交的 count 只能是 advisory mismatch check。

`placement_preference` 不是 backend authority。若 agent 明确要求 `sandbox` 而 sandbox 不可行，Host
返回可读 failure facts，不得自动改成 HPC。`any` 允许 Host 在等价且 policy-approved 的 candidate
中选择唯一计划，但 plan 仍必须在 effect 前可见并按 policy获批。

## Resource-class registry

每个 class 使用 versioned closed `scientific_resource_class@1`，至少包含：

- resource class id/content digest、placement category、policy epoch；
- CPU quota in integer millicores、quota period、cpuset/affinity upper bounds；
- max processes、threads、PIDs 与 calculation worker concurrency；
- memory/swap/scratch/output upper bounds in integer bytes；
- wall/CPU-time bounds in integer milliseconds；
- network mode、filesystem capability class、GPU/accelerator facts；
- isolation/runtime packaging identity；
- admission/queue/cost/approval class；
- receipt measurement/attestation method and supported failure taxonomy。

resource class 是 policy contract，不是机器当前 usage。availability、queue depth、current capacity 和
reservation 通过独立短期 snapshot 表达，避免把易变时间戳写入长期 class digest。

### Effective CPU capacity

Host 至少收集并区分：

- configured quota/period；
- cpuset CPU count；
- process affinity count；
- runtime/placement declared concurrency cap；
- current class reservation。

compiler 按 versioned formula得出 `effective_cpu_millicores` 和
`max_parallel_workers`。对于 current sandbox，2-CPU quota 与可见 16-CPU affinity 必须生成
2-CPU effective fact，而不是 16。任何 cgroup interface 缺失、malformed、unbounded 与 policy
期望不一致时，Host 明确标记 `unknown|unbounded|bounded`，不能把 read error当作 Host CPU count。

当前 Goal 的 cgroup-aware helper 只是 container-side safety clamp；未来 authoritative plan 仍须由
Host产生，并由 sandbox receipt证明观察值与 plan 一致。

## Placement plan schema

`scientific_calculation_placement_plan@1` 建议包含：

- plan id/digest、request id/digest、created/config epoch/expiry；
- calculation/contract/implementation identity；
- canonical params/input/output closure；
- placement compiler id/implementation digest and policy digest；
- candidate placements with bounded safe rejection reasons；
- exactly one selected placement and resource-class id/digest；
- runtime packaging、dependency manifest、Python ABI/platform or HPC toolchain identity；
- staged-input/materialization contract and expected output contract；
- deterministic/equivalence class identity；
- estimated operations/complexity/resource range and uncertainty category；
- approval requirement, permission class, cost class and approval summary；
- `fallback_policy="none"`；
- receipt schema and required measurement fields。

plan digest 覆盖完整 canonical preimage。candidate list不是运行时 fallback order；它只解释为什么
selected placement 可行。selected executor 一旦开始，backend unavailable、queue failure、timeout、
resource exhaustion 或 receipt failure均终结当前 command。agent 读取事实后可以显式提交 fresh request，
但 harness 不自动选择另一个 candidate。

## Placement semantics

### Sandbox

- 只执行已在 sandbox dependency manifest 中注册的 calculation implementation；
- 复用 sandbox isolation/no-network/workspace boundary；
- command 必须在 plan resource class 中启动，或证明现有 container class exact equality；
- cgroup/runtime drift 在 calculation start 前拒绝；
- receipt 由 Host 观察 process/container identity、resource facts 与 sealed outputs，不信 caller JSON。

### Controlled Host

- 仅允许 registry 中专门标记 `host_worker_safe=true` 的 pure callable；
- 使用无 credential、无通用 filesystem、no-network、dedicated uid/namespace/cgroup 的 worker；
- input 通过 verified read-only artifact materialization，output 只写 Host-created staging capability；
- 不执行 agent source、pickle、dynamic import、shell、notebook 或 caller-supplied module path；
- process group/cgroup 必须在 receipt 前完全退休。

### HPC

- Host 把 typed calculation intent交给 runner-owned compiler；sandbox 不提交 SSH/Slurm/shell/SIF path；
- input 只从 artifact catalog授权并 staging，output 只来自 declared expected outputs；
- toolchain/runtime identity使用现有 runner attestation，job/queue/resource request绑定 plan；
- remote outcome unknown、job失联或 incomplete fetch保持 fail closed，不转回本地重跑。

## Approval and permission

Host policy根据 placement、resource/cost class、external queue effect、input sensitivity 和 existing plan
call budget机械决定 approval：

- 已批准 sandbox command 内、低资源且无新 effect 的 calculation 可以是 `approval=none`；
- 新 Host resource reservation、HPC submission、GPU/high-memory/high-wall class 通常要求 approval；
- approval UI 展示 calculation、input cardinality、selected placement、resource/cost bounds、runtime/
  dependency digest prefix、output roles 和 uncertainty，不展示私有 locator；
- approval 只授权 exact plan。换 placement、class、runtime、input、implementation 或 output contract
  都不能复用；
- rejection/expiry 不触发 alternate placement；command 明确终止并把事实返回 agent。

该 approval 仍是现有 canonical ApprovalRequest/operation command 生命周期的一部分，不建立第二套
用户决策系统。是否把 local calculation 记录为新 `ControlledOperation` subtype 或独立 command
record，必须在 schema phase 明确；不能借用 provider operation fields 造成伪 external effect。

## Execution and receipt closure

`scientific_calculation_execution_receipt@1` 至少包含：

- receipt id/digest、plan/request/calculation/implementation identity；
- selected placement/resource class/runtime/dependency identity；
- canonical start/end/terminal status and stable error code；
- Host/runner-observed opaque process/job/container handle digest；
- effective CPU quota/cpuset/affinity/worker count、wall time、CPU time、max RSS、scratch/output bytes、
  throttling/queue facts；
- exact input artifact ids/digests and verified materialization receipts；
- exact output roles/artifact ids/content digests/serializer ids；
- no-network/filesystem capability verdict；
- exit/signal/timeout/resource-limit and process-retirement closure；
- incomplete/unknown fields with explicit reason, never fabricated zero；
- public-safe projection digest and private diagnostic ref。

Host 必须从 process/cgroup/runner/artifact boundary 生成 receipt。calculation callable 返回的 summary
可以作为待验证 observation，但不能填写 actual usage 或 artifact authority。offline verifier重算
request/plan/receipt digests、input/output bytes、calculation result和resource-bound comparison。

## Failure taxonomy

建议稳定分类：

- `scientific_calculation_contract_missing`
- `scientific_calculation_implementation_drift`
- `scientific_calculation_input_identity_mismatch`
- `scientific_calculation_placement_unavailable`
- `scientific_calculation_resource_facts_unavailable`
- `scientific_calculation_resource_class_mismatch`
- `scientific_calculation_plan_drift`
- `scientific_calculation_approval_required`
- `scientific_calculation_execution_failed`
- `scientific_calculation_resource_exceeded`
- `scientific_calculation_output_contract_mismatch`
- `scientific_calculation_receipt_incomplete`
- `scientific_calculation_backend_outcome_unknown`

public diagnostic 只返回 stable code、calculation/placement/class identity、safe count/bound 与 opaque refs。
private path、command、environment、cgroup locator、runner address、credential 和原始 stderr继续留在
受控 private evidence。`retryable=true` 只供 agent决策，不是自动 replay/fallback authority。

## Security and safety

- **Host arbitrary-code escape**：controlled Host worker只执行 allowlisted immutable callable，不接受
  agent source、pickle、module string、shell或dynamic plugin。
- **resource exhaustion**：每个 placement使用真实 cgroup/job limits、admission reservation和output
  bounds；Host API/core进程不直接承载重计算。
- **dependency confusion**：runtime只接受 pinned dependency manifest；在线 install和运行时 pip禁止，
  具体构建见独立 dependency proposal。
- **input substitution**：所有 placement从artifact catalog materialize并重算digest；sandbox path或
  HPC path不是输入authority。
- **backend semantic drift**：只有 registry 声明的 exact implementation/runtime可选；跨 backend
  golden/oracle不等于自动可互换，equivalence record也必须versioned。
- **approval bypass**：compiler机械决定approval requirement并进入plan digest；SDK hint不能降级。
- **receipt spoofing**：usage/process/output由Host/runner观察，caller summary不进入authority。
- **information leakage**：public facts只包含safe单位、count、status和digest prefix；不投影Host/HPC
  locator、queue secret、credential或其它tenant状态。
- **SQLite contention**：大计算在worker/runner执行；canonical state仍由单进程Host短事务写入，
  本提案不引入多进程SQLite writer。

## Compatibility and migration

1. **Inventory**：枚举所有 sandbox-local scientific callables、输入规模、复杂度、依赖、当前 timing、
   fixed resource policy与外部调用方；区分agent glue code与registry-worthy pure calculation。
2. **Schema freeze**：定义 request/resource class/placement plan/receipt closed schemas、canonical digest、
   public/private boundary和failure taxonomy，不改变执行路径。
3. **Safe resource facts**：Host runtime health以shadow形式投影effective cgroup/cpuset/affinity/memory/
   deadline facts；与container内观察比对，drift只使shadow qualification失败。
4. **Shadow placement compiler**：以AOX similarity为首个case，从sealed input cardinality预测current
   sandbox feasibility，并与实际 receipt比较；不自动改变backend。
5. **Restricted Host worker prototype**：只跑synthetic/non-cutover registered pure calculation，验证
   no arbitrary code、cgroup、artifact materialization和process retirement。
6. **HPC typed adapter**：由runner-owned compiler消费同一 calculation request，完成toolchain/
   staging/output receipt；不允许caller command。
7. **Dual receipt phase**：legacy sandbox command继续authoritative，new plan/receipt只shadow保存；
   mismatch为NO-GO，不能择优。
8. **Approval/schema cutover**：version bump SDK/control envelope、repository/API/UI/evidence；新 calculation
   command开始绑定exact plan，legacy command明确non-cutover。
9. **Caller audit and retirement**：确认无外部调用方依赖unplanned local path后，用correctional breaking
   change退役该calculation的legacy execution；registry不可用时不得双读或fallback。
10. **Fresh live qualification**：重新运行focused/resource/tamper gates、两次独立positive、一次fault和
    Chrome proof；三次必须绑定同一compiler/resource/runtime epoch。

Historical commands保持`legacy_unplanned_sandbox_calculation`语义，不原位补plan/receipt。新旧
placement authority不能混合聚合GO；rollback只能回到明确NO-GO legacy模式。

## Test and verification plan

### Unit and schema tests

- closed schema、duplicate key、unknown/missing field、noncanonical JSON、negative/nonfinite/overflow；
- request/plan/resource class/receipt任一字段改变都稳定改变digest；
- input cardinality从sealed bytes重算，caller hint漂移不能改变grant；
- CPU quota 2、affinity 16时effective worker cap是2；quota fractional/unbounded/malformed路径明确；
- placement preference与selected placement semantics，unknown placement fail closed；
- plan expiry/config/runtime/dependency/implementation/resource drift在dispatch前拒绝。

### Execution tests

- sandbox、restricted Host worker和HPC mock对同一registered deterministic calculation产生byte-identical
  output和distinct truthful receipts；
- process creation、worker、queue、staging、timeout、OOM、signal、output validation失败不触发fallback；
- controlled Host拒绝agent source、pickle、dynamic import、shell、network和arbitrary path；
- HPC receipt绑定runner-issued toolchain identity、exact staged input与declared output；
- actual worker count、CPU quota、max RSS、wall/CPU time和throttle fields来自executor observation；
- receipt缺失、cross-plan reuse、output re-seal或usage篡改被offline verifier拒绝。

### Product and live tests

- `world.inspect`/workflow prompt只显示bounded availability、placement/class facts，不推荐策略；
- approval UI/API绑定exact plan，同operation resume，不因backend failure自动新建approval；
- artifact/report lineage从receipt到sealed input/output闭合；
- 2-CPU sandbox真实case不会因Host affinity启动16 worker；
- 高成本真实case只有在explicit approved placement下执行，并产生真实非fixture receipt；
- migration tests证明historical rows只读、mixed authority拒绝、caller audit完成前legacy path不删除。

## Risks and mitigations

- **compiler变成workflow optimizer**：输入只含explicit calculation request与world facts，输出只选择
  等价placement/resource，不生成task graph、branch、threshold或retry策略。
- **resource estimate错误**：schema区分estimate、hard limit、availability和actual；未知时fail closed，
  不靠放宽deadline补救。
- **Host worker扩大TCB**：只接受small allowlist和immutable runtime，独立进程/cgroup/no-network，
  agent code永不进入。
- **三套executor漂移**：共享logical calculation/serializer schema，placement-specific adapter仅负责
  runtime；cross-placement golden和receipt tests持续比较。
- **approval过载**：policy对低资源already-approved sandbox calculation可免新approval，但authority
  仍在plan中；不通过隐藏auto-approve解决。
- **prompt膨胀**：只投影bounded ids、resource summaries和docs refs，完整plan/receipt通过按需读取。
- **performance benchmark误当科学证据**：diagnostic与attempt artifact namespace分离；receipt只有进入
  clean-root formal lineage并通过verifier才有cutover资格。

## Explicit non-goals

- 不把Host placement compiler、HPC runner或calculation registry变成顶层task/session真状态。
- 不自动选择科学问题、过滤阈值、候选集合、pair抽样、approximation、early-stop或报告结论。
- 不把agent-authored任意Python移到Host/HPC执行，也不开放shell/SSH/Slurm/SIF/path给sandbox。
- 不通过提高全局sandbox CPU/memory/timeout来代替per-calculation resource class。
- 不引入多进程SQLite writer、不改变runner仅供trusted Host的边界。
- 不把performance/equivalence测试当作wet-lab有效性或live GO evidence。
- 不在当前 AOX/HMM Goal 中实现request/plan/receipt schema、Host worker、HPC adapter或migration。

## Acceptance criteria before implementation becomes authoritative

1. agent可从facts-only projection看到已注册calculation、可用placements、effective resource/cost/
   approval facts，但不收到recommended action或固定workflow。
2. same request/input/Host policy稳定生成同一plan digest；sandbox caller无法伪造placement/class/grant。
3. affinity 16/cgroup quota 2、fractional quota、cpuset收紧、memory/pid/deadline drift均有可重算
   Host-authoritative结果与negative tests。
4. sandbox/controlled Host/HPC只执行registry允许的exact implementation；runtime/dependency/toolchain
   漂移在effect前失败。
5. plan与canonical approval绑定；placement/resource/runtime/input/output任一漂移都不能reuse。
6. selected backend失败不会自动serial/local/HPC fallback、缩小输入、改变算法或创建replacement
   approval；agent收到structured facts后自行决策。
7. Host worker证明不执行agent source、不联网、不读取Host arbitrary path，并在receipt前完全退休。
8. HPC执行证明runner-owned compile、artifact staging、declared output和toolchain attestation闭合。
9. actual receipt由Host/runner观察并绑定input/output/process/resource；tamper、missing、unknown outcome
   全部offline fail closed。
10. historical command不原位升级；external caller audit完成前legacy path不删除，retirement使用明确
    breaking version且无fallback。
11. public API/UI/evidence不泄露Host/HPC locator、cgroup path、credential、private config或raw stderr。
12. fresh AOX campaign的两个positive与一个fault在相同calculation/compiler/resource/runtime identity
    上独立封存并通过，之后才能声称该placement architecture支持cutover。

在这些条件全部满足前，本提案保持 **proposed / not implemented**。当前 Biopython `1.87` / NumPy
`2.4.4` direct pins、runtime numeric/trace/correction assertions与已由formal private-cgroup Podman根
`cpu.max`实证的cgroup-aware worker clamp只能称为局部实现纠正，不能称为
Host-authoritative calculation placement。
