# Deferred: bounded canonical artifact metadata manifest references

Status: proposed; not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

r27 的真实 positive attempt 证明 `aox_sequence_length_join@2` 对 37,772 个
UniProt identity 生成的合法 catalog metadata 已达到 17,016,803 canonical
JSON bytes，其中完整 `identity_mappings[]` 是科学合同要求，不能截断、抽样或删除。
旧 SDK 把 metadata 内联进 4 MiB control frame，因而在 Host dispatch 前以
`sandbox_transport_request_too_large` fail-closed。

当前 Goal 只做局部纠正：

- 保持 4 MiB request/response frame；
- SDK 对超过 256 KiB 且不超过 32 MiB 的 registration metadata 使用 attempt-local、
  canonical、digest-bound transport sidecar；
- Host 在任何 seal 或 catalog mutation 前验证 sidecar；
- registration response 返回 bounded closed projection；
- Artifact catalog 仍保存完整 metadata object，现有科学合同、17 件 AOX deliverable、
  artifact identity 与 verifier 语义不变。

这个修复解决 transport，不改变 catalog storage model。它不表示 17 MiB JSON row 是
长期目标，也不把 transport sidecar 提升为 canonical scientific artifact。本文记录更大的
repository/schema 迁移，当前 Goal 不实现。

## Current facts and pressure points

当前 Artifact 记录把以下内容共同保存在 `metadata_json`：

- 小型 identity：format、content/sealed digest、source snapshot、validation；
- 中型 provenance：provider/toolchain/input refs、count closure；
- 潜在大型 manifest：accessions、response digests、file manifest、逐 identity mapping。

现有 public `artifact.list` 已对 metadata 做 deterministic bounded summary，
control-plane `artifact.get` 已支持 collection/string paging。这证明产品读取面知道
metadata 可能很大，但持久化层仍把整个 object 复制进单个 SQLite TEXT row。由此产生：

- 同一计算 metadata 被附到 CSV、FASTA 或多个衍生 artifact 时重复存储；
- row deserialize 会一次性分配完整 object，即使 caller 只需要一个 digest/count；
- repository filter、workspace projection、bundle collector 容易误触完整 hydrate；
- SQLite backup、WAL、attempt sealing 与 verifier archive 放大重复 bytes；
- GC 无法独立管理 large metadata bytes，因为它们不是 BlobStore object；
- metadata path paging 是对已经完整加载 object 的投影，不是真正的 bounded read；
- schema evolution只能重写整行，无法独立迁移 manifest format；
- transport sidecar 是临时 spool；若误当 canonical ref，会形成第二个未治理的 truth。

## Agent-harness principles

- agent 应表达科学 metadata object，不负责判断何时拆 inline/manifest，也不手写 storage
  locator；artifactization 是 harness 的机械职责。
- 完整 scientific mappings 必须 durable、可离线重算；bounded projection 不能被解释为
  原数据为空或不存在。
- artifact metadata identity 必须由 canonical bytes/digest决定，而不是 SQLite JSON 文本、
  临时 sidecar path 或展示顺序。
- Host path、Blob path、GC handle 与 storage tier 不向 agent 暴露；agent只看到 typed ref、
  digest、count、schema 和可执行的 bounded read contract。
- inline 与 manifest 两种物理表示必须有同一 logical metadata digest；storage placement
  不能改变 artifact scientific identity。
- 任何 missing/corrupt/unbound manifest 都 fail-closed，不能回退到 truncated summary。

## Target invariants

1. 每个 Artifact 拥有一个 canonical logical metadata object 和唯一
   `logical_metadata_digest`。
2. 小 object 可 inline；超过 versioned threshold 的 object 必须进入 immutable metadata
   manifest Blob，catalog row只存 closed ref与 bounded index。
3. threshold只决定 storage placement，不改变 logical digest、artifact idempotency key或
   scientific contract。
4. manifest bytes使用 versioned canonical JSON或等价 closed encoding；禁止 duplicate key、
   NaN/Inf、non-UTF-8、非 object root和非 canonical bytes。
5. manifest Blob commit先于 Artifact row commit；row与Blob ref必须原子闭合或可回收，不得出现
   可见 dangling ref。
6. metadata read必须真正 bounded：server按 typed key/index cursor读取，不先 hydrate完整 object。
7. `artifact.list`、workspace projection和registration response永远使用 bounded summary；完整
   manifest只能通过授权 read API 分页读取。
8. verifier按 ref/digest读取 exact bytes并重算 logical object；summary从不充当完整证据。
9. 同 digest metadata在同一 attempt/repository内内容寻址去重；不同 session authority 不因知道
   digest自动获得读取权限。
10. Blob GC只有在无 Artifact、bundle、retention或legal-hold ref时才可回收。
11. restart、duplicate registration与idempotent reuse必须得到同一 metadata ref/digest。
12. legacy inline row在迁移完成前仍可读；fresh writer不能静默在两种 schema间降级。

## Proposed object model

### `artifact_metadata_binding@1`

```text
ArtifactMetadataBinding@1
  logical_metadata_digest
  logical_size_bytes
  root_schema_id
  storage_mode = inline | manifest_ref
  inline_value?                 # bounded
  manifest_id?
  manifest_content_digest?
  manifest_encoding?
  top_level_field_count
  bounded_identity_index
  binding_digest
```

`bounded_identity_index` 只含 schema、contract、content/sealed digest、counts与经过 allowlist
的短 scalar。它不是完整 metadata，也不能覆盖 manifest truth。

### `artifact_metadata_manifest@1`

```text
ArtifactMetadataManifest@1
  manifest_id
  session_scope / ownership_scope
  encoding = canonical_json_v1
  content_digest / size_bytes
  logical_metadata_digest
  top_level_field_count
  collection_index[]
  blob_ref_private
  created_at / retention_class
  manifest_commit_digest
```

`collection_index[]` 可为 large top-level list/dict提供 item count、segment roots或可选 chunk
index，但不能改变 canonical logical object。若未来采用 chunked Merkle manifest，应另发 schema，
不得在 `canonical_json_v1` 下改变 digest算法。

### `artifact_metadata_page@1`

```text
ArtifactMetadataPage@1
  artifact_id / logical_metadata_digest
  typed_path_segments[]
  offset / limit / returned_count / next_offset
  value_kind
  items_or_text
  page_content_digest
  manifest_content_digest
```

typed path需与 `artifact-path-addressing-for-arbitrary-dictionary-keys.md` 协同；在该提案未落地前，
仅安全 key可精确分页，其余返回 root-only capability，不猜测字符串路径。

## Authority and write path

1. SDK/Host handler接收 logical metadata object或已验证 transport sidecar。
2. ArtifactBoundary canonicalize并计算 logical digest、size与bounded identity index。
3. 小于 inline threshold时创建 inline binding；大于 threshold时先把 exact canonical bytes写入
   Blob staging，fsync、rehash并以no-replace content address提交 manifest。
4. Artifact idempotency key绑定 source digest、source snapshot与 logical metadata digest，不能绑定
   临时 sidecar path或manifest storage URI。
5. repository transaction提交 Artifact row、metadata binding/refcount；失败的孤立Blob进入GC queue。
6. registration response只返回 artifact id、content/tree digest、logical metadata digest、storage mode
   与bounded summary，不回送完整 object。
7. transport sidecar在commit后仍只是 attempt-local debug evidence；其删除不影响 canonical manifest。

ArtifactBoundary拥有 canonicalization、binding与Blob commit；repository拥有 row/refcount事务；
projection只读binding/index；科学 calculation拥有metadata字段语义，但不拥有storage placement。

## Read and projection path

- `artifact.list` 只读 row + bounded index，不加载 manifest bytes。
- `artifact.get` root 请求返回binding、bounded index、omission summary与typed page capability。
- 精确 page请求由manifest reader按offset/chunk读取；实现必须证明resident memory受page cap约束。
- SDK `artifacts.get`只返回 sandbox-safe bounded ref；需要大型 metadata 的pipeline应显式请求受控
  page或materialize authorized manifest，不通过4 MiB response猜测。
- workspace/report/scientific-evidence projection不得隐式展开manifest。
- bundle collector可按需求sealed-copy manifest一次，并在inventory中以digest引用；多个Artifact共用同一
  manifest时不得复制相同bytes多次，除非archive format明确要求且有dedup receipt。

## Verification and scientific closure

offline verifier必须：

1. 验证binding closed schema与binding digest；
2. 从archive manifest ref读取exact bytes，核size/content digest；
3. strict decode canonical object并重算 logical metadata digest；
4. 重算 bounded identity index并与catalog row比较；
5. 对 workflow-specific metadata执行既有科学recompute，例如 AOX active/inactive partition、count
   closure与sorted identity mappings；
6. 验证所有引用同一logical digest的Artifact没有schema/index漂移；
7. manifest missing、extra、duplicate、tampered、wrong-scope或summary-only一律NO-GO。

## Compatibility and migration

1. 增加 additive binding/manifest tables与Blob kind；不立刻重写历史row。
2. dual-reader读取 legacy inline或新binding，fresh writer先shadow生成binding并比较logical digest。
3. 对大历史row做offline backfill：canonicalize、commit manifest、写binding；保留migration receipt，
   不能从bounded projection反推完整object。
4. verifier同时支持明确版本的 legacy inline bundle与manifest bundle，不自动把一种解释成另一种。
5. 观察SQLite/WAL/latency、dedup ratio、page memory后，把fresh large writer切到manifest-only。
6. 外部调用方审计完成后退役large inline writer；small inline仍可作为正式storage mode。
7. rollback只切换fresh writer；已提交manifest binding继续可读，禁止反向复制成无上限row。

## Failure, recovery, and GC

- transport sidecar验证失败：effect前失败，不创建manifest或Artifact。
- Blob staging成功、row commit失败：staging/ref进入GC queue，Artifact不可见。
- row commit成功、response delivery失败：Artifact仍committed；按
  `controlled-operation-outcome-unknown-after-response-failure.md` 使用result handle/reconcile，不能重写。
- manifest损坏：Artifact保留identity fact但变为不可消费/不可cutover；不以summary代替。
- refcount drift：GC fail-closed保留Blob并产生repair audit，不猜测删除。
- Host restart：扫描staging、pending binding与GC queue；content-address/no-replace保证重复commit幂等。
- quota耗尽：在Artifact row commit前返回typed failure；不自动截断metadata或改为inline。

## Security and privacy

- manifest ref是session/Artifact-scoped authority，不是“知道SHA即可读取”的公开URL。
- private Blob locator、Host path、SQLite rowid、GC token与encryption key不进入public binding。
- metadata仍执行private-field sanitation policy；artifactization不能成为泄露Host locator的旁路。
- page limits同时限制bytes、items、depth与serialized response；恶意nested object不能强制完整hydrate。
- canonical decoder有深度、field、string与collection hard caps；超过cap typed fail-closed。
- dedup跨privacy scope默认关闭；若未来跨scope去重，必须先有encryption/ownership与side-channel分析。

## Test strategy and acceptance criteria

- 1 byte below/at/above threshold产生预期storage mode，logical digest一致。
- 17 MiB AOX 37,772 mappings与100k上界synthetic manifest可bounded写入、分页与离线重算，Host RSS不随
  full object重复增长。
- 同一metadata绑定多个Artifact只存一份manifest bytes，refcount与archive inventory闭合。
- duplicate registration/restart得到同一manifest digest与Artifact idempotency结果。
- tampered size/digest/canonical bytes、duplicate key、NaN、wrong schema/scope全部effect前失败。
- Blob commit、row commit、response send、restart和GC barrier逐点故障注入，无dangling visible row、误删或
  ordinary retry replay。
- `artifact.list`、workspace、registration response在最大manifest下保持固定budget。
- typed page对安全/不安全dict key、list offset、大字符串与next cursor无跳项、重复或越权。
- legacy inline与new manifest bundle均按声明版本验证；缺manifest不能借legacy path fallback。
- AOX two-positive-plus-fault fresh campaign证明storage迁移不改变scientific output、artifact set或GO reducer。

## Non-goals

- 不把 transport sidecar 当作 canonical ArtifactMetadataManifest。
- 不提高4 MiB control frame来容纳更大object。
- 不删除或摘要化科学 identity mappings。
- 不在本提案中替换SQLite control plane、引入分布式object store或改变task/runtime真状态。
- 不把metadata manifest与artifact content blob混为同一logical kind。
- 不在当前AOX/HMM Goal中实现本文任何repository/schema/GC迁移。
