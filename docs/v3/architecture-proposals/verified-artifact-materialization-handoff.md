# Deferred: verified artifact materialization handoff

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 Goal 只实现 canonical 的 adapter-input byte-flip 故障门：controlled operation 获得批准后、provider 或 HPC runner 收到请求前，Host 重新读取已批准 artifact 的真实 blob bytes，计算 digest，并在 observed/catalog/approved 三者不一致时 fail closed。live fault injector 必须真实修改 blob、`fsync` 后再触发该门；测试必须证明外部 provider/runner 的 spy 没有收到请求。

这已经回答“在 dispatch 前修改 canonical sealed blob，系统是否拒绝”，也是本轮 GO 标准要求的故障验证。但当前 materialization 校验返回后，consumer 仍可能通过 catalog 中的原始 `storage_uri` 再次打开 bytes；HPC staging 也尚未把本地与远端实际传输 bytes 都绑定到 approved digest。因此当前实现不能扩张表述为“从检查到消费始终使用同一个已验证对象”，也不能声称已经消除 check-to-use TOCTOU。

把已验证 materialization 变成 provider、compiler 和 runner 实际消费的唯一 authority，会改变 artifact boundary、controlled-operation runtime、provider adapter、execution compiler、runner staging、lease/recovery 与 evidence schema 的跨包 ownership。它属于独立的大架构调整：本轮只记录，不实现；若 canonical byte-flip gate 与其他当前验收项通过，它不额外阻断本轮 live cutover GO，但所有报告必须保持上述窄化 scope。

本提案只处理科学 input artifact bytes。HPC SIF toolchain bytes 的 immutable per-run snapshot 由 `immutable-hpc-sif-execution-snapshot.md` 负责；typed HPC command 与 plan ownership 由 `runner-owned-hpc-command-compiler.md` 负责。

## Current implementation evidence

1. `packages/openzyme-engines/src/openzyme_engines/execution.py::ExecutionEngine.execute_sandbox_adapter_operation()` 在 provider/HPC dispatch 前调用 `_verify_sandbox_adapter_input_artifacts()`。
2. `packages/openzyme-runtime/src/openzyme_runtime/artifact_boundary.py::ArtifactBoundaryService.materialize()`（由 `openzyme_core.artifact_boundary` 重导出）通过 `_verify_artifact_blob()` 读取 source bytes，比较 observed digest、catalog digest 与 approved digest，并生成只读 sandbox materialization。
3. `packages/openzyme-engines/tests/test_execution.py::test_sandbox_adapter_executor_rejects_mutated_sealed_input_before_hpc_submit` 修改真实 sealed blob bytes，并断言 digest mismatch 时 runner payload 为空。该测试证明 canonical pre-dispatch fault gate，不证明校验完成后的消费绑定。
4. `apps/openzyme-host-api/src/openzyme_host_api/aox_cutover_live.py::_inject_before_hpc_approval()` 对目标 blob 做 one-bit flip 并 `fsync`，而不是只改 catalog metadata。它为当前 live fault proof 提供真实 byte mutation。
5. `_verify_sandbox_adapter_input_artifacts()` 当前丢弃 `MaterializedArtifact` 返回值。它产生的 verified private path/identity 没有成为后续 consumer request 的输入。
6. `packages/openzyme-tools/src/openzyme_tools/execution.py::_local_path()` 仍从 catalog record 的原始 `storage_uri` 解析 Host path。provider/HPC compiler 可以在校验后重新读取 mutable source。
7. `apps/mcp-hpc-runner/src/mcp_hpc_runner/staging.py::upload_inputs()` 会计算本地 checksum，但当前传输合同没有要求在远端命令或其他外部 I/O 前把它精确比较到 operation 的 approved digest，也没有形成可离线复核的 local/remote consumption receipt。

### Check-to-use gap

当前顺序可以抽象为：

```text
catalog storage_uri -> verify/hash/materialize -> discard verified handle
catalog storage_uri -> provider parse or compiler path -> runner staging -> consume
```

若 source 在第一步完成后、第二次打开前发生修改或替换，canonical pre-dispatch byte-flip gate已经结束，consumer 可能读取另一组 bytes。即使本地 staging 计算了 checksum，只要没有把 observed value 与 approved digest 做强制比较并阻止后续 I/O，checksum 仍只是诊断值而不是 authority。远端传输后若没有复核 remote bytes，network/filesystem corruption 也可能在实际执行前未被发现。

把第二次 hash 移得更近、再次调用 `materialize()` 或依赖只读 mode 只能缩小窗口；只要 verifier 与 consumer 重新解析 mutable path，且没有 lease/fencing 或 immutable handle，便不能建立 same-object guarantee。

## Impact on agent autonomy and trust

- agent 应引用 artifact ID、approved digest 与科学用途，不应理解 Host path、sandbox path、runner staging path 或存储后端细节。
- harness 必须把 materialization、lease、consumer binding 与 staging failure 结构化呈现，让 agent 能依据真实 blocker 调整科学策略；不能用内部路径或模糊“input unavailable”掩盖状态。
- verification 失败不能触发读取原始 `storage_uri`、选择 sibling artifact、跳过 digest、重新下载或走 native/legacy backend 的隐藏 fallback。
- provider/HPC consumer 应获得同一种 authority-free `VerifiedInputHandle`，但各 consumer 仍保留适合其领域的解析和执行策略；harness 不替 agent 固定科学计划。
- private path、storage URI、SSH target、remote staging path、lease fencing token 与 credential 不得进入 public operation/event/workspace/report/bundle。
- 当前 @1 证明应明确保持“canonical source 在 dispatch 前复核”语义；未来 schema 才能声明 verified materialization-to-consumer binding。

## Non-goals

- 不改变 `session + task board + approval + controlled operation + artifact` 的顶层产品真状态，也不建立第二套 scheduler 或 artifact catalog。
- 不改变 AOX motif rule、UniProt/NCBI identity、HMM 科学规则、文献证据或 GO reducer。
- 不允许 agent、provider caller 或 runner caller提交 private materialized path、remote path、lease/fencing token 或 observed digest。
- 不在本提案中解决 SIF toolchain hash-to-open TOCTOU；它属于 immutable snapshot 提案。
- 不在本提案中把 Host shell command 改成 runner-owned typed compiler；本提案只规定 compiler/runner 必须消费已验证 input handle。
- 不把所有 artifact 复制到永久的新 object store。第一阶段在单进程 SQLite 与现有 storage boundary 内实现 correctness-first 的 materialization/lease 生命周期。
- 不把历史 operation 补造为已拥有 consumption binding；历史 receipt 永远按原 schema/scope解释。
- 不以 checksum cache、size/mtime、只读 chmod、path equality 或“runner 属于可信 Host”替代内容绑定。

## Target invariants

1. 每个需要 artifact input 的 controlled operation 都必须把 exact `{artifact_id, approved_digest, input_slot}` 集合绑定到 approved operation；provider params、HPC stage refs 与 binding 集合不多不少。
2. artifact boundary 从 source bytes 创建 verified materialization，同时计算 observed digest；observed、catalog 与 approved digest 必须完全相等，unknown algorithm/field fail closed。
3. provider、execution compiler 与 runner staging 只能消费由该 operation 获得的 active `VerifiedInputHandle`；不得重新读取 catalog `storage_uri` 或 caller path。
4. verification 与 consumption 通过 operation-scoped lease 和 fencing token绑定。过期、释放、重复、跨 operation、跨 workspace 或旧 fencing handle 均不可消费。
5. provider 在任何外部网络请求前从 verified materialization 完成本地解析；解析期间检测到 bytes/digest漂移时 external call count 必须为零。
6. HPC staging 在 upload 前复核 local observed digest 等于 approved digest，并在 launch 前复核 remote observed digest；任一不匹配时远端科学命令调用次数必须为零。
7. 同一 input slot 只能存在一个权威 consumption binding。idempotent retry 只能复用同 operation、同 approved digest、仍 active 的 binding，不能“挑一个能跑的”materialization。
8. materialization、lease、consume、release 与 invalidation 状态必须 durable；crash/restart 后 stale authority不能复活，active object不能提前 GC。
9. failed/cancelled/timed-out execution 不得把 partial outputs 注册为 trusted scientific artifacts；诊断 artifact 若允许，必须使用独立 closed kind/status，不能混入 declared success outputs。
10. public projection 只包含 opaque IDs、approved/observed digest、closed status/outcome/failure code与 schema version，不包含 private refs 或 path。
11. 新 route/schema 缺失、binding 失败或 consumer 不支持 handle 时显式 fail closed；不能静默回退原始 `storage_uri`、legacy adapter 或未验证 staging。
12. 历史 @1 reader 与未来 @2 reader严格分离；@2 verifier不得把 @1 pre-dispatch proof升级解释为 consumption binding。

## Proposed state model

本提案新增的是 controlled operation 下属状态，不是新的顶层产品实体。

```text
VerifiedArtifactMaterialization
  materialization_id / session_id / sandbox_workspace_id
  artifact_id / approved_digest / catalog_digest / observed_digest
  byte_size / immutable_source_identity / private_materialized_ref
  state = PREPARING | VERIFIED | LEASED | CONSUMED
          | RELEASED | INVALIDATED | FAILED
  created_at / verified_at / expires_at / failure_code

ArtifactConsumptionLease
  lease_id / materialization_id / operation_id / input_slot
  consumer_kind = PROVIDER | HPC_STAGING | SANDBOX
  fencing_token
  state = ACTIVE | CONSUMING | CONSUMED | FAILED | RELEASED
  issued_at / expires_at / terminal_at

VerifiedInputHandle (private, authority-free DTO)
  handle_id / artifact_id / content_digest / byte_size
  input_slot / purpose / schema_id

ArtifactConsumptionBinding
  binding_id / operation_id / input_slot
  artifact_id / approved_digest / materialization_id
  lease_id / consumer_kind / request_or_transfer_digest
  local_observed_digest / remote_observed_digest
  outcome / failure_code / consumed_at

ArtifactConsumptionProjection (public closed view)
  schema / binding_id / operation_id / input_slot
  artifact_id / approved_digest / observed_digest
  consumer_kind / outcome / failure_code
```

`private_materialized_ref`、真实 path、storage backend identity、fencing token 与 runner staging locator 只存在 Host/runner private store。`VerifiedInputHandle` 是进程内或 authenticated internal protocol 的 opaque capability；其 public form不能反推出 path，也不能由 caller自行构造。

推荐 future schema 使用 `artifact_consumption_binding@1`。当前 canonical pre-dispatch proof继续使用原有 schema，不原地改义。

### Stable failure taxonomy

- `artifact_blob_digest_mismatch`：catalog source bytes 与 catalog/approved digest 不一致。
- `artifact_materialization_digest_mismatch`：materialized bytes 与 approved digest 不一致。
- `artifact_consumption_binding_missing`：operation/slot 没有唯一 active binding。
- `artifact_consumption_lease_stale`：lease 过期、fencing错误、跨 operation或已释放。
- `artifact_consumer_digest_mismatch`：provider/compiler读取的 verified bytes 漂移。
- `artifact_staging_digest_mismatch`：本地 upload source 或远端 staged bytes 不匹配 approved digest。

failure detail 可以带安全的 artifact/operation opaque ID 与 expected/observed digest；不得带 private path、raw provider payload、SSH config或secret。自动 retry只能重新建立全新的显式 materialization/lease，不能回头读取原始 path继续旧 operation。

## Ownership boundaries

- `ArtifactBoundaryService` 拥有 source access、materialization、content verification、private ref 与 materialization lifecycle；它不拥有 approval、provider策略或runner命令。
- controlled-operation/core service 拥有 approved artifact identity/input-slot set与 operation binding；它只持 opaque materialization/binding IDs，不持 Host path。
- execution engine 拥有从 approved operation请求 lease、把 verified handles交给 exact consumer、记录 terminal consumption outcome；它不能自行改 approved digest。
- provider adapter 接受 verified byte stream/handle或由 boundary产生的解析结果，不接受带 `storage_uri` 的 `SessionArtifactRecord` 作为active-path input。
- Host execution compiler 接受 verified handles和logical output declarations；若 legacy compiler暂时需要本地 path，path只能在同一 private boundary内从 active handle解析，且不得持久化或投影。
- runner staging 接受 typed staged input `{handle, approved_digest, byte_size, purpose}`，负责 upload前 local hash、upload后 remote hash与 launch gate；它不信任 caller自报 observed digest。
- repository 在近期单进程 SQLite 中持久化状态、lease、fencing与 receipt；private refs分层存储并从所有公共projection闭集排除。
- verifier/GO reducer只消费 closed evidence，不直接打开 private materialization，也不把 diagnostic checksum当authority。

## Materialization-to-consumer protocol

1. approval commit 时 core closed-validate route-specific input params/stage refs，并把 exact artifact/digest/slot 集合纳入 approved operation digest。
2. dispatch前 engine 向 artifact boundary 请求 materialization。boundary 从受控 source handle流式读取、hash、验证 size/digest、写入私有 staging object，完成 data/directory durability 后 atomic seal；partial object不可签发 handle。
3. boundary 创建 `VerifiedArtifactMaterialization(VERIFIED)`，为 operation/slot 签发 lease与 fencing token，再返回 opaque `VerifiedInputHandle`。handle内容由 Host生成，caller不能覆盖。
4. provider route从 handle解析 verified bytes。若需要生成 accession/query等外部参数，必须在发起网络 I/O 前完成解析和 digest复核；provider request receipt绑定 consumption binding。
5. HPC route把 handle传给 compiler/staging DTO。Host不能从 catalog重新解析 source path；runner在 authenticated boundary内解析受控 transfer source，先计算 local digest并与 approved digest比较。
6. upload完成后 runner在目标执行环境计算 remote staged digest；只有 local、remote、approved三者相等且 lease/fencing仍有效，才可生成 execution plan/command并启动科学工具。
7. consumer第一次不可逆 I/O前原子地把 lease从 `ACTIVE` 迁移到 `CONSUMING`。成功读取/transfer/launch后记录 receipt并进入 `CONSUMED`；失败进入 `FAILED`，不能复用旧 authority。
8. operation terminal、cancel或timeout后释放lease。GC只清理无active lease且不被sealed evidence retention引用的materialization；crash recovery宁可暂时保留bytes，也不能让stale lease复活。
9. evidence sealing把 closed consumption projection与 operation/artifact provenance一起封存；offline verifier复算schema/digest并验证每个 required input slot恰有一个successful binding。

## Relationship to adjacent proposals

- `immutable-hpc-sif-execution-snapshot.md` 保护 Apptainer SIF toolchain bytes；本提案保护 FASTA/HMM/sequence 等科学 input bytes。两类digest、lease和failure code必须分开，不能用一个证明替代另一个。
- `runner-owned-hpc-command-compiler.md` 让 runner从typed intent编译plan。未来 compiler应引用 `VerifiedInputHandle`/staging receipt，而不是 Host path；本提案不决定argv、entrypoint或shell grammar。
- `single-source-hpc-toolchain-contract-registry.md` 可声明 tool contract需要哪些typed input slots，但不拥有artifact bytes或consumption lease。
- `dual-tier-scientific-evidence-boundary.md` 可复用public/private projection原则；本提案的 private materialization不能因报告或bundle生成而泄露。
- 三项可分别shadow，但 cutover到 consumption-binding @2 时，provider/runner receipt、operation binding与sealed bundle必须引用同一artifact ID/digest。单独生成一个materialization record而实际继续读取原路径，不构成验收。

## Migration plan

1. **冻结当前 scope。** 文档和verifier明确当前证明只覆盖canonical source的pre-dispatch byte flip；保留真实mutation、`fsync`和external-call-zero fixture，不声称same-object consumption。
2. **盘点active readers。** 列出provider、compiler、runner staging、preprocess与sandbox中所有 `storage_uri`/local path reader，区分public projection、diagnostic与实际scientific consumer；建立CI denylist。
3. **发布schema与SQLite migration。** 增加materialization、lease、binding与receipt tables/state transitions/canonical digest。历史row不回填虚假binding，新operation显式选择versioned route。
4. **shadow materialization receipt。** 现有verified copy保留到consumer结束，记录would-consume handle与原reader observed digest做比较；shadow不改变实际I/O，也不能用于GO。
5. **provider canary。** 先迁移 `bio.hmmer_search`（以及需要artifact-derived query的provider route）只从verified handle解析。通过mutation barrier证明precheck后改原blob不会改变request，改materialization则在network前失败。
6. **HPC local handoff。** compiler从handle获取受控transfer source，RunSpec/staged-input schema加入approved digest、byte size、slot和handle identity；禁止active route调用catalog `_local_path()`。
7. **runner transfer binding。** runner在upload前验证local digest、upload后验证remote digest，写入staging receipt；remote command/Slurm submission只能消费successful receipt。
8. **接入lease/fencing与recovery。** 把claim lifecycle、timeout、cancel、restart、duplicate drain和GC接到materialization state machine；先按近期单进程 SQLite约束实现并做确定性交错测试。
9. **迁移public projection与offline verifier。** 发布 `artifact_consumption_binding@1` closed view，覆盖operation/events/workspace/reports/sealed bundle，增加private-field/path negative tests。
10. **切换全部scientific adapter inputs。** 按provider、direct SSH、受支持的Slurm route逐项canary；没有materialization handoff能力的route保持NO-GO/unsupported，不走legacy fallback。
11. **退役direct storage reader。** 确认无外部调用方后，删除active provider/compiler对catalog `storage_uri`的读取与旧staged-input writer；保留显式versioned历史reader用于复核旧bundle。

## Compatibility and rollback

- @1 pre-dispatch route与@2 consumption-binding route必须显式version；一个operation只选择一个authority，不双写后择优成功。
- shadow阶段可以同时计算对照receipt，但只有当前active route产生权威outcome；shadow receipt明确标注non-authoritative且不进入GO reducer。
- provider/HPC canary失败时可以关闭@2 route并让要求该保证的campaign保持NO-GO；不能在同一operation内回退原始 `storage_uri`。
- SQLite schema migration采用additive tables/columns和显式reader version。rollback不删除active lease、materialization、sealed evidence引用或审计record。
- 历史operation没有binding就是没有，不能根据catalog当前bytes补造；historical verifier继续按旧scope运行。
- handle/materialization schema或digest算法变化发布新version；不能原地改变opaque handle语义或把旧observed checksum升级为approved proof。

## Security, correctness and operability risks

- **opaque handle变成路径包装：** API和序列化层拒绝path字段；private resolver验证session/workspace/operation/slot/lease/fencing，不只比较handle字符串。
- **materialized copy仍可被同UID修改：** verified object放在consumer不可写的private boundary，或在每次consume前从同一opened handle复核digest；部署不能提供合格保护时显式capability unavailable。
- **double-open TOCTOU：** verifier与consumer共享sealed object/handle；不得先hash path再让consumer重新按path打开。平台受限时需要brokered stream或opened-FD handoff。
- **remote transfer corruption：** local与remote SHA-256都绑定approved digest；remote hash失败、缺失或格式异常时不启动命令。
- **lease race/use-after-release：** state transition带fencing与conditional update；duplicate drain、retry和crash recovery都不能复用stale token。
- **跨slot/cross-operation substitution：** handle绑定operation、artifact、digest与slot，exact-set validation拒绝额外、缺失或相同digest下的错误artifact ID。
- **partial output被误信任：** failed execution的declared outputs清空；诊断输出使用独立kind/status和projection，不能满足scientific prerequisite。
- **性能与容量：** 大artifact copy/hash会增加I/O和启动延迟。只允许按verified immutable content identity去重bytes，每operation仍签发独立lease；path/mtime cache不能替代hash。
- **GC pressure：** 设置TTL、quota、backpressure和审计retention。quota耗尽返回稳定resource blocker，不回退mutable source。
- **provider SDK要求path：** 在private adapter boundary把handle解析成read-only FD/temporary path，并保持lease到SDK完成；不得把path回写catalog或public trace。

## Test strategy

### Unit and schema tests

- materialization/lease/binding canonical digest稳定；任一语义字段变化必变，unknown/extra/private field fail closed。
- observed/catalog/approved digest三方不一致、unsupported algorithm、size mismatch、partial write、fsync/rename failure都不能签发handle。
- handle resolver拒绝wrong session/workspace/operation/slot/artifact/digest、stale lease、wrong fencing、released/failed state与path injection。
- public projections在operation/event/workspace/report/bundle中都不含`storage_uri`、materialized ref、Host/remote path、fencing token或credential。

### Adversarial handoff tests

- 用barrier在precheck通过后、provider read前修改原始catalog blob；provider必须继续消费已验证对象，request digest不变。
- 在precheck通过后修改/替换materialized object；consumer digest gate必须失败，provider network call count为零。
- 在compiler生成前替换catalog `storage_uri` target、symlink或inode；HPC RunSpec只能引用原verified handle，不能跟随替换。
- runner upload前修改local transfer source，必须返回`artifact_staging_digest_mismatch`且upload/remote command为零。
- upload途中或完成后破坏remote bytes，remote digest gate必须失败且Apptainer/scientific command/Slurm submit为零。
- duplicate drain、timeout、cancel、engine crash与Host restart交错下，旧lease/fencing不能再次消费；active materialization不会提前GC。

### Integration and live tests

- HMMER provider从真实verified HMM artifact产生canonical request；sealed receipt证明request-derived digest与approved input一致。
- CD-HIT、MAFFT、hmmbuild、hmmalign分别证明local/remote staged digest、operation input slot与实际declared outputs闭合。
- 真实canonical byte-flip fault仍在任何provider/runner I/O前fail closed，保持当前GO故障标准；另加post-check mutation fault证明新handoff关闭TOCTOU。
- failed/nonzero/timeout/missing-output execution不注册partial trusted artifacts，diagnostics不满足下游prerequisite。
- SQLite restart/recovery测试覆盖每个非终态与fencing；单进程约束下用确定性barrier模拟竞争，而不是声称多进程安全。
- 两次独立正向blank-world E2E与fault bundle都能由offline verifier复核exact input consumption bindings；任一缺失或extra binding使GO reducer fail closed。

## Acceptance criteria

- active provider、compiler和runner staging不再直接读取catalog `storage_uri`；静态denylist和runtime spy同时证明。
- 每次外部provider request、upload、remote command或Slurm submit之前，都存在唯一active consumption binding，且实际consumer bytes的observed digest等于approved digest。
- precheck后修改原始blob不能改变consumer输入；修改verified materialization、local transfer或remote staged bytes均在相应外部I/O/launch前fail closed。
- runner staging receipt精确绑定operation、slot、artifact ID、approved digest、local observed digest、remote observed digest与outcome；任一篡改离线验证失败。
- lease/materialization状态机经restart、duplicate drain、timeout、cancel与GC故障注入证明无stale authority、double consume或active-object early deletion。
- failed execution不产生trusted scientific outputs；partial/diagnostic artifacts不能被下游科学prerequisite消费。
- public API/events/workspace/reports/sealed bundle只有closed safe projection，不泄露Host/remote path、storage URI、private ref、fencing token或secret。
- @2 route不支持、binding缺失、digest漂移或lease stale时显式NO-GO，不回退@1/legacy/native路径；历史@1 bundle仍按原scope验证。
- copy/hash/staging的latency、I/O、quota和GC指标有明确上限与operator blocker；性能优化只复用已证明immutable的content bytes，不削弱per-operation binding。
- 架构文档、schema、migration、tests与offline verifier共同证明“验证的bytes就是consumer实际使用的bytes”，而不是仅证明两个时刻的pathname hash相等。
