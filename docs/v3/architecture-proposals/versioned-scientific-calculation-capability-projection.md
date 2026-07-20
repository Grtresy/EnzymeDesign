# Deferred: versioned scientific-calculation capability projection

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 Goal 只做两类局部纠正：

1. 对仓库中已经存在的 `openzyme_pipeline.aox_*` 精确实现，在显式选择的 AOX
   workflow pack 中投影 callable、canonical serializer、contract digest 与
   implementation digest，禁止 agent 近似重写；
2. collector/offline verifier 从封存 bytes 重算科学结果，任何 approximation、sentinel、
   schema-shaped 假行或 digest drift 都 fail closed。

这不能解决全部架构问题。当前一些版本化计算同时拥有 typed Python callable、结果对象与
测试 fixture；另一些计算只存在于 Host collector 常量、验证分支和 Markdown 说明中。例如
`aox_motif_candidate_filter@1`、`aox_upstream_empty_materialization@1`、
`aox_reference_only_scoring_alignment@1` 与
`canonical_empty_cluster_membership@1` 尚未形成统一、可发现的 SDK capability facade。
若在本 Goal 中统一它们，会改变 Pipeline SDK API、calculation ownership、workflow manifest、
artifact metadata、collector/verifier schema 以及历史 bundle 兼容，属于大型架构调整，因此
本文件只记录计划，不实施。

## Problem evidence

- 科学 identity 分散在 `openzyme_pipeline.aox_*` 模块、Host API cutover collector、eval
  validator、workflow 文档和测试 fixture 中，没有单一可枚举的 canonical registry。
- workflow pack 可以告诉 agent 一个 calculation id 和数学约束，但若没有 exact callable
  projection，agent 仍需猜测参数、返回类型和 serializer。r3 executor 因而把
  `aox_motif_rule_score@1` 写成 alignment percent-identity approximation。
- r32 的受控 AOX SOP 已列出 exact callable 与 accessor 名，但没有投影 Python 返回类型；
  executor 因而把 `result.to_fasta() -> str` 直接交给 bytes-only `Path.write_bytes`，在完成
  真实 NCBI operation 后以 `memoryview(str)` TypeError fail closed。当前 Goal 只补足该已安装
  facade 的精确类型事实与 UTF-8 边界；统一 registry/typed projection 仍属于本提案的大改。
- Host collector 能离线识别错误 bytes，但这种事后拒绝没有在执行前低摩擦地告诉 agent
  “应调用哪个 typed capability、如何注册结果、哪些 branch 输出必须为空”。
- 部分 branch-only calculation 由 collector 直接重算，executor 只能手写等价逻辑。即使
  agent 策略正确，也容易因排序、header、空集合、decimal 或 metadata 细节产生不可接受漂移。
- contract digest、implementation digest、callable 名、serializer 和文档目前可能独立更新；
  CI 能覆盖已知 AOX 路径，却没有通用 drift closure。
- 把完整 Python 源码塞进 prompt 不是解决方案：它增加上下文压力、鼓励复制实现，并把
  executable authority 混入自然语言知识，而不是形成受控 capability。

## Agent impact

- agent 应看到可调用的科学能力、typed 参数、结果 schema、固定 identity 和失败原因，而
  不需要从 collector 源码逆向合同。
- harness 应忠实呈现“当前安装了什么”“哪个版本被 workflow 选择”“输出怎样封存”，但不
  规定唯一 graph、顺序、batching、inspection、retry 或 early-stop 策略。
- agent 可以选择不调用未到达分支的 capability；一旦调用，Host 必须能证明它执行了精确
  implementation，而不是一个同名、近似或本地重写版本。
- 不可用、版本漂移或 serializer 不兼容应成为结构化 prerequisite/capability error，不能
  静默退回手写 Python、旧函数或“能跑”的 fixture。

## Target invariants

1. 每个版本化科学计算只有一个 immutable logical contract record；callable、result schema、
   serializer、docs、workflow projection 与 verifier expectation 都从该 record 派生。
2. `calculation_id@major`、contract digest 与 implementation digest 分离：合同不变但实现
   bytes 改变必须显式更新 implementation identity，并重新证明等价性或切换版本。
3. agent-facing projection 只包含科学参数、input/output artifact roles、branch preconditions、
   serializer 和 safe failure taxonomy；不暴露 Host path、storage URI、credential 或私有
   provider/runner mechanics。
4. calculation capability 不拥有 session、task、approval、operation 或 artifact 顶层真状态。
   它只在现有 execution sandbox/Host artifact boundary 内执行并返回 typed result。
5. workflow 选择使用 explicit subset/role-scoped binding；registry 不根据关键词自动注入
   domain policy，也不把所有 calculation 广播给所有 teammate。
6. canonical serializer 是合同的一部分。agent 不应手拼 CSV/FASTA/JSON rows；serializer
   bytes、metadata 与 calculation receipt 必须由同一结果对象生成。
7. 空结果是 typed branch outcome，不是缺文件。每个 empty-capable calculation声明允许的
   reason、zero-record artifact roles、derivation id 与下游 capability closure。
8. collector/offline verifier独立从 sealed inputs 重算或验证 receipt，不能只信 agent metadata
   或 callable 名；SDK 与 verifier 使用共享 schema，但保留独立 closed reconstruction。
9. registry缺失、重复 identity、unknown version、digest drift、serializer drift、额外字段或
   result bytes不一致时 fail closed，禁止 best-effort coercion。
10. 历史 bundle 永远按其记录的 schema/version验证；新 registry不能重新解释旧 calculation
    identity，也不能原地修改已封存 artifact 语义。

## Proposed model

```text
ScientificCalculationContract
  calculation_id / version / contract_digest
  title / scientific_semantics / fixed constants
  input_roles[] / parameter_schema / branch_preconditions
  output_roles[] / empty_outcomes[] / failure_taxonomy
  result_schema_id / serializer_ids[]

ScientificCalculationImplementation
  calculation_ref / implementation_digest
  python_module / callable_name / result_type
  serializer_bindings / dependency_identity
  deterministic_fixture_refs / supported_runtime

AgentCalculationProjection
  calculation_ref / contract + implementation digests
  callable import path / typed arguments / safe result summary
  artifact registration profiles / docs refs

ScientificCalculationReceipt
  calculation_ref / contract + implementation digests
  input artifact ids + content digests
  canonical parameter digest / branch outcome
  output artifact ids + content digests
  serializer identities / runtime identity
```

推荐由一个窄、无 Host API/runner 依赖的 registry package 拥有 logical schema 和 canonical
digest。`openzyme-pipeline` 从 registry 生成或显式绑定 Python facade；workflow knowledge 只
投影当前选择所需的 safe subset；Host collector 和 offline verifier消费同一 versioned schema，
但分别重建/复算 receipt。registry 不执行调度，也不保存 mutable state。

## Capability discovery and prompt projection

- `world.inspect` 或独立 facts-only capability index 只返回 bounded calculation identities、
  availability、callable ref、input/output role与 docs ref；不内联源码、fixture或大结果。
- workflow prompt render只包含显式绑定 calculation的短 call map。完整参数/结果 schema通过
  `docs.read` 或 typed tool descriptor按需读取，避免每轮重复大段合同。
- executor sandbox镜像/SDK preflight发布 registry digest与每个 implementation digest；workflow
  requirements在第一次 model call前验证 exact match。
- agent仍可自由组织一个或多个 source files、选择合法顺序和检查点。projection不得生成
  todo graph、自动委派或隐式 operation。

## Empty and conditional calculations

每个可为空的 output role应声明：

```text
empty_reason enum
trigger input role and predicate
canonical byte shape
artifact kind/format/validation profile
derivation calculation ref
omitted downstream capability set
required independent health evidence, if any
```

例如 AOX 的 `target.fasta`、`AOX_candidates.fasta` 和 CD-HIT representative FASTA 可以是
exact zero bytes，但只有对应 calculation receipt、stable reason 与 upstream sealed inputs
闭合时才有效。通用 `fasta_zero_records@1` 只验证字节形状；scientific registry负责声明哪类
calculation可合法使用该 profile，workflow verifier负责证明 branch。两层不能互相替代。

## Migration plan

1. 只读盘点所有 `*@1` scientific ids、Python callables、Host constants、serializer、fixture、
   docs和verifier分支，输出 duplicate/missing/drift清单。
2. 定义 `scientific_calculation_contract@1`、implementation record与receipt closed schema；先为
   已有 typed AOX reference、HMMER filter、sequence join、motif和similarity实现 shadow records。
3. CI shadow-compare registry projection与现有模块常量、function signature、contract metadata、
   fixture bytes和workflow文档；不自动改写生产文件，差异先作为 blocker。
4. 为当前 Host-only branch calculations补 typed pure functions/result objects/serializers；保持
   collector的独立重算，证明新 facade输出与历史 canonical bytes逐字节一致。
5. 让 Pipeline SDK从 registry导出 stable public facade，并为 sandbox preflight发布完整
   registry/implementation identity；unknown或drifted record在dispatch前失败。
6. workflow manifest从 registry选择 explicit calculation refs并生成 bounded call map；删除
   手写平行 callable表之前，CI要求两者逐字段一致。
7. artifact registration接收由 calculation result产生的 typed derivation receipt；Host验证
   input/output digest、serializer和empty profile授权，禁止 caller伪造 implementation id。
8. collector/eval/offline verifier迁移到 versioned receipt schema；对每个计算保留 sealed-byte
   recomputation、malicious extra field、approximation、sentinel和digest drift负例。
9. 审计所有外部 SDK 调用方和历史 bundles。确认无调用旧 facade/metadata后，以纠正性 major
   change退役散落常量与手写文档表；不得在registry失败时双读择优。

## Compatibility and rollout

- 第一阶段仅 shadow registry，不改变现有 import path、artifact bytes、operation set或workflow
  ref；任何差异为 NO-GO，不做运行时修复。
- public import path可保留为 thin generated/exported facade，但其 calculation identity必须来自
  registry；删除或改参数使用明确 breaking version。
- 历史 calculation id若合同有歧义，冻结为 legacy verifier，不“修正”旧 bytes。新 workflow
  只能选择新版本，legacy结果不得进入 cutover GO。
- rollback只能切换明确的 registry/implementation epoch，并保留新旧 receipt；不能把新 receipt
  标成旧 digest或回写历史 artifact metadata。

## Risks and mitigations

- registry演变成科学上帝对象：只拥有 immutable schema/digest，不拥有策略、state或执行生命周期。
- code generation掩盖review：生成物deterministic、可审阅；CI展示semantic diff，不在runtime生成。
- shared validator形成单点误判：SDK、Host boundary和offline verifier保留独立negative corpus与
  closed reconstruction。
- prompt再次膨胀：默认只投影bounded ids/call map，源码与大schema按需读取并受prompt budget管理。
- 过度约束agent：registry固定科学事实和I/O合同，不固定graph、role topology、batching或报告叙事。
- implementation digest频繁漂移：明确区分semantic contract和implementation identity；等价优化
  仍需fixture/recomputation证明，但不无谓创建新科学合同。

## Acceptance criteria

- 所有 cutover-required calculation均可从一个 registry枚举，并具有 exact callable、typed
  inputs/result、canonical serializers、contract/implementation digest和deterministic fixture。
- 修改任一合同字段会稳定改变contract digest；修改implementation bytes会改变implementation
  digest；任一层未同步时preflight、dispatch或offline verifier fail closed。
- AOX reference selection、HMMER filter、sequence join、motif、candidate filter、conditional empty
  materialization、CD-HIT membership和similarity不再依赖Host-only手写科学常量。
- agent在不读取Host collector源码的情况下能发现并正确调用达到分支所需能力；仍可自由选择合法
  顺序、batching、inspection和early stop。
- approximation percent identity、手写schema行、sentinel FASTA、伪cluster/edge、错误serializer、
  unknown calculation version和metadata伪造的测试全部在封存前或offline验证时失败。
- facts-only capability projection在大量历史invocation下保持有界，不内联源码、artifact bytes或
  verifier evidence。
- 新旧bundle的versioned verifier均可重复运行；新workflow拒绝legacy/unregistered calculation。

## Explicit non-goals

- 不把LangGraph/LangChain或registry变成顶层产品真状态。
- 不自动生成唯一workflow graph、todo list、role topology或retry policy。
- 不让agent直接选择provider credential、runner、SSH/Slurm、Host path或artifact storage。
- 不以typed receipt替代sealed-byte recomputation、真实provider/HPC证据或wet-lab验证。
