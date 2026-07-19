# Deferred: artifact-derived conditional capability closure

Status: proposed, not implemented generically in the current AOX/HMM blank-world Goal.

## Problem evidence

科学 workflow 的真实执行图经常由中间结果决定：HMMER 无高分 accession 时不应调用 UniProt；UniProt 序列经长度过滤后为空时不应运行 HMMalign；motif 过滤后无候选时不应运行 CD-HIT。若 workflow manifest 静态声明所有 operation 都是 required，agent 即使正确识别终止条件，也会被 harness 迫使执行无意义调用；若 collector 为了通过静态清单伪造 operation、request/response digest 或空输出，又会破坏 fail-closed 和可复核性。

AOX 专用实现可以由 `hmmer_score_filtered_accessions@1`、`aox_sequence_length_join@2` 和 motif/candidate artifacts 离线反推实际分支，并用严格 skip receipt 记录未调用原因。但把 AOX 的 stage 名称、artifact role 和 omission 列表直接做成通用 Host schema，会把一个 workflow 的策略固化到顶层 harness。通用 closure 需要 workflow manifest、operation attestation、capability health、report projection 和 offline verifier 的共同设计，属于大架构调整，因此本 Goal 只实现 AOX 专用 verifier，并在此记录长期方案。

## Agent impact

- agent 应能基于可观察的真实科学结果选择继续、早停或更换仍在用户授权范围内的策略，不应为满足静态 checklist 而调用没有输入意义的 provider/tool。
- harness 应结构化呈现“当前 artifact 证明了什么、哪些 capability 仍可合法调用、哪些调用现在必须省略”，但不替 agent 决定科学策略或自动完成 task。
- 正确早停必须产生可理解、可验证的 outcome；不能仅留下缺失 operation，也不能要求 agent 手写 digest 或伪装 provider I/O。
- capability 的可用性证明与正式科学结果应分离。known-positive probe 可证明被省略的 backend 健康，但其 bytes、operation 和结论不得进入正式结果。

## Target invariants

1. `session + task + lane + approval + controlled operation + artifact + report` 继续是唯一产品真状态；conditional closure 只是从这些 durable facts 派生的验证结果。
2. reached branch 必须由 sealed artifact bytes 经 versioned offline calculation 推导，不能信任 agent、execution summary、UI 或 collector 自报的 branch 字符串。
3. 每个分支声明精确的 required、optional-now-reachable 和 forbidden operation roles；实际 formal operation 集合必须与 derived reached graph 完全相等。
4. “未调用”不是 provider outcome。skip receipt 必须绑定 trigger artifact、derivation operation、reason 和 decision digest，并明确 `provider_io_performed=false`；不得包含虚构 operation、invocation、request 或 response digest。
5. formal capability coverage 与独立 health-probe coverage 的并集必须满足 manifest 的完整 cutover capability set；probe artifacts 与 formal artifacts 永不交叉引用。
6. closure verifier 不改变 task status、不批准 operation、不恢复失败调用、不选择 fallback，也不把 runtime idle 解释成业务完成。
7. artifact 缺失、schema/digest drift、branch ambiguity、额外调用、被隐藏的失败调用或 probe 污染一律 fail closed。

## Proposed model

```text
ScientificBranchManifest
  manifest_id / workflow_selection_ref / validator_ref
  trigger artifact roles and calculation contracts
  branch definitions:
    reached predicates
    required / forbidden operation roles
    required artifact roles and digest-bound edges
    terminal outcome contract
  complete capability set

DerivedBranchAttestation
  trigger artifact refs / derivation operation ref
  validator implementation digest / recomputation result
  reached branch id / reason / observed counts
  exact reached operation and artifact closure
  typed skip receipts

CapabilityCoverageAttestation
  formal reached capabilities
  isolated known-positive probe capabilities
  union / required set / missing set
  identity-overlap and artifact-flow checks
```

manifest 只固定可验证的不变量与分支条件，不固定 agent 的命令顺序、teammate 拓扑或 prompt 文案。workflow-specific offline validator 读取 allowlisted sealed bytes并返回 branch fact；generic closure layer 只检查 operation/artifact graph、skip schema、capability union 和隔离性。

## AOX behavior used as the compatibility oracle

AOX 专用实现应作为行为基线，而非直接成为通用 schema：

- HMMER upstream empty：外部 provider 图到 EBI HMMER 与 score filter 为止，省略 UniProt、HMMalign、CD-HIT；本地可重算图仍产生 exact-13 model reference、AAB-only coordinate reference/scoring input、reference-only scoring alignment、motif/candidate/empty-membership/similarity closure；用严格 `provider_upstream_empty_receipt@1` 解释 UniProt 未调用。
- length-filter empty：UniProt 与 sequence join 已到达，省略 HMMalign、CD-HIT，用已验证的 AAB-only scoring input 物化 reference-only scoring alignment。
- motif-filter empty：HMMalign 与 motif scoring 已到达，省略 CD-HIT，仍产生 canonical empty membership/graph closure。
- nonempty：执行完整正式图。
- 无论正式图落在哪个分支，独立 probe 证明 cutover 所需、但本分支未到达的 provider/toolchain 健康；probe 不改变 AOX outcome。

## Alternatives considered

- 静态要求所有 operation：会鼓励无意义调用并削弱 agent 的正确早停，不采用。
- 只允许 agent 报告 `skipped=true`：不可离线证明 trigger，容易伪自声明，不采用。
- 把所有分支写进顶层 scheduler：会让 scheduler 成为科学策略 owner，并混淆 runtime progression 与业务语义，不采用。
- 缺 operation 时自动补 health probe：隐式外部调用扩大授权与成本，不采用；probe 必须由显式 campaign/manifest 启动。
- 允许 collector 从 execution summary 选择分支：summary 是产品输出而非权威输入，只能与重算结果一致，不能决定 closure。

## Migration plan

1. 冻结 AOX 专用 branch、skip receipt、probe isolation 和 tamper tests，收集 nonempty 与每个 empty branch 的 golden closure。
2. 定义只读 `ScientificBranchManifest` 与 validator SPI，先对 AOX evidence shadow 计算，不改变现有 AOX decision。
3. 提取通用 operation/artifact graph closure 与 exact-set 验证；workflow plugin 只提供 branch predicate 和 role/edge manifest。
4. 引入 typed skip receipt repository/DTO；AOX 先双写专用 JSON 与 generic shadow record，并逐字段比对。
5. 引入 capability coverage reducer，把 formal/probe union 作为独立 attestation；验证 identity、artifact、session、task、workspace 全隔离。
6. 至少用一个非序列、同样包含正确早停的 scientific workflow 做 shadow 验证，避免通用模型过拟合 AOX。
7. generic shadow 与专用 verifier 对所有正向、空结果、额外调用、隐藏失败和篡改 fixture 等价后，再发布 major-version manifest；旧 AOX reader永久保留。

## Compatibility and rollback

- 不重写已封存 attempt、skip receipt、operation 或 artifact；generic layer 只引用原始 identity。
- shadow 结果不得参与 GO/NO-GO，直到 manifest major version 被显式选择。
- 回滚只停止 generic attestation 写入，不恢复静态 required-operation fallback，也不删除已写 shadow facts。
- branch/skip/capability schema 改变 canonical bytes、reason、exact role set 或 blocker precedence 时必须 major-version。
- 迁移期间只有一个权威 closure reducer；禁止专用与 generic verifier 任选其一通过即算成功。

## Risks

- manifest 过度规定策略：只允许声明 outcome predicates、capability class 和 evidence closure，不编码 teammate、prompt 或命令计划。
- 恶意 artifact 诱导错误分支：validator 必须无网络、固定 implementation digest、严格解析并验证 upstream raw bytes。
- probe 被当作 formal fallback：enforce session/root/operation/artifact identity disjointness，report claim 不得引用 probe artifact。
- skip receipt 变成伪 operation：schema 明确没有 backend run、approval、request/response 字段；UI 单独显示为 derived decision。
- branch 爆炸：manifest 支持组合 predicate 与继承公共 edge，但发布前必须证明每个 terminal branch 有正向和 tamper coverage。
- TOCTOU：branch 只对 content-addressed sealed bytes求值，operation closure引用同一 digest，不能读取 mutable workspace path。

## Acceptance criteria

- AOX nonempty、三个 healthy-empty 分支和相应篡改 fixture在专用与 generic shadow verifier 上得到相同 branch、required/forbidden role set 和 pass/fail。
- self-claimed empty、trigger artifact 篡改、虚构 provider digest、额外 forbidden operation、被隐藏的 failed operation 全部产生稳定 fail-closed blocker。
- formal 与 probe capability union 精确覆盖 manifest required set；任一缺失、重复、identity overlap 或 probe artifact流入 formal graph 都失败。
- agent 在正确早停时不需要执行无意义 provider/tool、不需要拼装 attestation，仍能看到结构化 reason 与下一步合法 capability。
- scheduler、protocol 和 task business exit 语义不因 closure 引入而改变；没有 implicit drain、implicit completion 或 hidden fallback。
- manifest/validator/skip schema 有 major-version、canonical digest、offline tamper corpus 和 migration/rollback tests。
