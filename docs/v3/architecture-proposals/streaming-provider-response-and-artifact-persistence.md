# Deferred: bounded streaming provider response and artifact persistence

Status: proposed; not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 Goal 已把 sandbox control socket 的单帧 NDJSON request/response 上限固定为 4 MiB，并改为
64 KiB chunk聚合。这个修复解决了合法大 request被单次 `recv(65536)` 截断的问题，也明确阻止无界
wire frame。它没有把 provider HTTP body、parsed result、artifact draft、workspace file与sealed Blob
之间的数据路径改造成streaming。

当前真实bio provider adapter仍以完整body和完整文本为主要值类型。`_http_request()` 调用
`response.read()`；`BioProviderHttpResponse` 同时保存decoded `body`和`body_bytes`；UniProt/HMMER等
adapter还会保存多个response、JSON pages、normalized records、base64 raw-response envelope和artifact
draft字符串。随后persistence path再次sanitize/encode/write，artifact boundary的若干digest/validation
路径使用`read_bytes()`或`read_text()`读取完整文件。

因此4 MiB control-frame cap只保护sandbox wire，不构成provider response、Host内存、temporary file、
artifact Blob或validator的size/backpressure证明。当前代码审计确认存在多份内存驻留，但本轮尚未观察
到由此导致的真实OOM；本文记录的是可预测的容量与正确性风险，不把它描述成已发生的r15故障。

把这条路径改为bounded streaming会同时改变HTTP adapter SPI、raw-response schema、artifact ingress、
Blob commit、validator、reader、GC与public projection，属于大架构调整。当前AOX/HMM Goal不实施本文，
不修改历史artifact语义，也不能把新proposal当作当前live bundle已满足的保证。

## Real r25 evidence: large result sets amplify both latency and resident data

r25 的 HMMER job 约 `24s` 已 terminal，但旧 adapter 随后用约 `52m` 处理 `686` 个 result payload。
terminal poll 使用 provider 默认 `page_size=50`，后续请求却使用 `page_size=100` 并从 `page=2`
开始，导致 `68,592` 条 provider 命中只物化 `68,542` 条。只读恢复用统一
`page_size=1000` 得到 `69` 页（最后一页 `592` 条）和完整 `68,592` 条。对应 UniProt 输入在
旧科学结果下仍有 `37,722` 个 accession、`378` 个计划 query batch；现有 adapter 会把多个 response、
decoded body、parsed record 与 raw-response metadata 同时累积在内存。

这次没有观察到 OOM，因此不能把 r25 记作 streaming failure；它提供的是此前代码审计缺少的真实规模
证据。当前 Goal 的同宽 `page=1..N`、`page_size=1000` 与 `nreported` closure 修复减少 result GET
次数并纠正完整性，但单页更大，既不是通用 resident-byte cap，也不是 bounded streaming。未来实现仍需
证明 wire/decoded/parsed/spool 各层上限与 backpressure，不能用“请求数从 686 降到 69”推导内存安全。

同样，`nreported` 是完整 response 集的 closure fact，不是预先分配内存的许可。streaming reducer 必须
在增量 ingest 中检查 page identity、ordered coverage、duplicate/gap 和最终 record count；partial spool
即使已有正确 digest prefix 或大量有效 records，也不能 publish。r25 的旧 `68,542` 条结果永久不可因
后续恢复诊断而升级为 eligible artifact。

## Current code facts and failure modes

### Multiple complete in-memory representations

一份response可能同时存在于`response.read()` bytes、decoded string、JSON object、adapter累计pages、
`provider_raw_http_response_set@1` base64 body、pretty-printed artifact draft、sanitized string、workspace file和
artifact boundary完整`read_bytes()/read_text()`。不是每条path都持有全部副本，但接口允许峰值内存随
response、parsed object、base64 envelope和generated artifacts放大，且无统一operation resident-byte cap。

### Unbounded read and late limit enforcement

HTTP在完整read前没有统一wire/decoded cap或decompression-ratio receipt；`Content-Length`缺失/错误不能
提供保护。validator多在完整落盘后运行，raw body又内嵌manifest。artifact row failure已有Blob GC概念，
但provider draft、workspace file与sealed Blob尚非统一atomic stream transaction。

### Read-side amplification

`_file_digest()`、tree summary和若干consumer直接完整读取；validator也缺少统一decoded chars、line/record
cap。即使caller只需digest或stream parse，当前仍可能载入完整bytes/string。

### Correctness ambiguity on partial data

必须区分完整response后commit失败、transport truncation、Host cap stop、decoded overflow、Blob rename后row
未commit、row存在但durability未知。它们不能都压成`provider_unavailable`或“file exists”；partial bytes
和hash prefix都不是sealed scientific artifact。

## Agent-harness principles

- agent表达需要哪些科学数据和可接受的provider/format，不负责选择chunk size、temporary path、buffer
  queue或fsync策略。
- harness应在调用前投影真实size/quota/streaming capability，在执行中提供bounded progress与stable
  blocker；不能等Host OOM后才以模糊错误失败。
- size cap、backpressure、digest、completeness与license是世界约束；harness必须忠实执行，不能截断
  body后假装healthy empty/partial success。
- streaming只改变数据搬运方式，不改变agent的query、provider顺序、科学过滤、identity判断或task
  终态。
- raw provider bytes、parsed artifact与public summary是不同authority tier；一个safe digest receipt不
  自动授权raw bytes进入public workspace/report。
- 所有公开结果只引用immutable opaque artifact/blob identity；private spool path、opened fd、object-store
  locator、credential和raw restricted body永不暴露给agent。
- 大artifact unsupported时应在已知上限前fail closed，给出明确`required_bytes/capability`，不能静默
  回退完整内存路径。

## Target invariants

1. response绑定typed ingest identity、wire/decoded caps、digest、license和destination；chunk、queue、resident
   memory、spool与decoded total均bounded/backpressured。
2. wire与decoded digest/size分离；encoding/decode policy改变必须改变identity。
3. 只有EOF/completeness、digest/size、validation、durability与atomic publication全通过才签发handle；partial
   spool永非artifact。
4. raw body与manifest分离；manifest只引用ordered immutable body refs，不base64内嵌大body。
5. private staging经incremental hash、fsync、no-replace commit；SQLite row只引用durable Blob，row failure
   留GC candidate。
6. validator消费bounded reader；不支持streaming时在读取前gate。public wire只返回bounded handle；cancel/
   timeout/quota/disconnect/restart均有明确completeness状态。

## Target architecture

```text
provider transport
  | bounded wire chunks + deadline + cancellation
  v
ProviderResponseIngress
  |-- wire byte counter / incremental digest
  |-- content-encoding decoder with decoded cap
  |-- bounded tee to parser and private spool
  |-- backpressure / quota reservation
  `-- completeness receipt
          |
          v
private ArtifactBlobPrepare
  |-- exclusive no-follow staging leaf
  |-- incremental digest/size
  |-- streaming validator(s)
  |-- fsync file + directory
  `-- atomic no-replace content-addressed commit
          |
          v
immutable ArtifactStreamHandle
  |-- raw response blob
  |-- normalized fragment/blob
  `-- parsed scientific artifact(s)
          |
          v
small manifests / operation result / public projection
```

transport、artifact ingress和validator可以在同一可信Host进程内实现，但authority必须分层：transport不能
直接创建artifact row，parser不能自行发布Blob，agent/caller不能提交private spool path。

## Proposed typed schemas and SPI

### `provider_response_ingress@1`

```text
ProviderResponseIngress@1
  ingress_id / operation_id / provider_attempt_id
  provider / safe_endpoint_id / method
  status_code / safe_headers / content_type / content_encoding
  wire_size_declared / wire_size_observed / wire_digest
  decoded_size_observed / decoded_digest
  wire/decoded/ratio caps / chunk and in-flight caps
  body_blob_prepare_id
  completeness = complete | transport_truncated | decoded_limit_exceeded
                 | wire_limit_exceeded | cancelled | timed_out | storage_failed
  started_at / first_byte_at / terminal_at
  failure_code / receipt_digest
```

`safe_headers`使用closed allowlist；完整response headers如确需审计，进入Host-private encrypted/restricted
record，不能通过一个开放dict进入public schema。

### `artifact_blob_prepare@1`

```text
ArtifactBlobPrepare@1
  prepare_id / owner_type / owner_id
  intended_kind / format / semantic_type / license_scope
  private_staging_ref
  expected/max/observed size / content_digest
  validation_contract_id / validation_result_digest
  state = reserving | writing | validating | commit_ready
          | committed | aborted | quarantined | outcome_unknown
  quota_reservation_id / writer_generation / fencing_token
  created_at / terminal_at / failure_code
```

`private_staging_ref`与fencing token不进入任何public serialization。一个prepare只能有一个writer；stale
writer不能commit或extend reservation。

### `artifact_blob_commit@1`

```text
ArtifactBlobCommit@1
  blob_id / content_digest / size_bytes
  storage_contract_id / blob_generation / prepare_id
  validation_contract_id / validation_digest
  publication_mode / durability_receipt_digest
  content_type / format / semantic_type / license_scope
  committed_at / commit_digest
```

`blob_id`是opaque catalog identity；即使底层使用content-addressed basename，public API也不暴露Host
path或允许caller据digest构造读取locator。

### `artifact_stream_handle@1`

```text
ArtifactStreamHandle@1 (Host-private capability)
  handle_id / blob_id / content_digest / size_bytes
  owner_session_id / purpose / format / semantic_type
  read_mode / max_read_bytes / expires_at / lease_id / fencing_token
```

consumer得到brokered reader/FD/iterator，而不是path。public projection只含artifact/blob opaque id、digest、
size、format和closed validation status。

### Provider raw response manifest v2

```text
ProviderRawHttpResponseSet@2
  schema_id
  provider / operation / operation_id
  responses[]:
    ordinal / phase / provider_attempt_id
    status_code / safe_headers
    body_artifact_id / body_digest / size_bytes
    content_type / content_encoding / completeness
  response_set_digest
```

`@2`不内嵌`body_base64`。它只在每个body artifact已经immutable committed后发布；missing/extra/ref drift
全部fail closed。历史`provider_raw_http_response_set@1`仍按内嵌body语义读取，不能原地改义。

## Streaming ingest and atomic commit protocol

1. preflight取得approved caps、quota、license/format与cancellation；exclusive/no-follow创建private staging并
   持久化quota reservation/prepare intent。
2. headers closed-validate length/type/encoding；bounded chunks进入小queue，由writer、hasher和stream parser
   消费同一bytes，慢consumer向transport施加backpressure。
3. wire/decoded分别计量并限制ratio、nesting、line/record size；只有protocol EOF才finalize completeness。
4. validator从同一opened handle/brokered reader消费；flush/fsync后核对stat/digest/size，no-replace rename并
   fsync parent；existing target仅在regular type、size和full digest相同时复用。
5. SQLite transaction再commit artifact/blob row，失败则GC；manifest/result只引用committed handles并返回
   bounded summary/IDs。

## Backpressure and quotas

每条route声明wire/decoded/ratio、chunk/inflight、operation/session spool、open streams、validator record和
total output caps，并纳入provider config digest与approved estimate。运行时不能偷增cap；plan不足返回
capacity blocker，截断body永不partial success。limiter区分network、open streams、resident memory和disk
reservation；线程池大小不是quota。

## Validators and readers

`ArtifactStreamValidator@1`声明format/semantic types、`single_pass | bounded_random_access`、record/count/
nesting caps和closed receipt。FASTA/CSV逐record，JSON限制depth/token/string；HMM等可用private bounded
reader/mmap，但不能无限`read_text()`。reader提供`iter_chunks()`、bounded range、verified reader和
metadata-only stat；agent tool仍只返回bounded excerpt或sandbox materialization ref。

## Failure and recovery

transport/decoder/cap failure使prepare aborted，partial spool始终private。rename前crash只留staging；先fence
writer再隔离/恢复。rename后、row前crash留下orphan Blob，可按prepare/digest/size/durability完成同一commit
或GC；row后crash只重建projection，不重读provider。existing Blob只有regular type、size/full digest一致才
复用。quota/cancel/disconnect均保留explicit completeness，不能删除别的active artifact或发布partial。
validator更新产生新version derivation，不原地改历史receipt。

## Authority and security

- provider transport拥有authenticated endpoint/credential和one-response stream，但不能决定artifact
  public visibility。
- response ingress拥有byte caps、hash、spool writer和completeness；它不解析科学结论或创建task状态。
- artifact boundary拥有private Blob root、no-replace commit、validation registry、catalog row与GC；caller
  只传typed content intent，不能传Host destination path。
- provider parser消费read-only stream handle，输出normalized drafts/streams；不得访问credential或修改raw
  blob。
- license policy决定raw/parsed artifact的read authority。safe public metadata与restricted bytes分别
  投影；digest不解除license限制。
- public events/errors禁止body excerpt默认泄露。需要diagnostic sample时由source-specific closed projection
  生成bounded、scrubbed artifact，不能在exception中任意切片raw body。
- staging root默认`0700`、leaf`0600`、no-follow/exclusive create；blob consumer只经opaque handle和scope
  check读取。
- digest/size、artifact ID和safe provider request ID可公开；private path、URL query、header、cursor、
  credential、lease/fencing和object-store locator不可公开。

Stable failure覆盖declared/wire/decoded/ratio cap、incomplete/backpressure、spool quota、validation、prepare
fenced、Blob commit/durability/digest、catalog commit和stream capability unavailable。public detail只含safe
IDs、caps、sizes/digests、format/reason，不含path、raw bytes、private headers或credential。

## Compatibility and migration

1. 量测并盘点`response.read/body_bytes/base64/read_bytes/read_text`，发布additive prepare/commit/reader SPI。
2. 小response可shadow比较digest但只能有一个authority；先迁raw-response@2 refs，再迁UniProt/NCBI、
   HMMER及validators/readers，不支持的大format显式unavailable。
3. 接入quota/backpressure/restart/orphan/GC/fencing，升级public projection/verifier；@1历史不追溯升级。
4. 无外部caller后退役legacy writer，保留reader/compat exporter；同一operation不得失败后择优切换。

rollback让新operation选择legacy route并保持其旧size cap。已经开始的streaming prepare必须完成、abort或
reconcile；不能读取partial spool后转交legacy writer继续。

## Test strategy and acceptance criteria

unit/property tests覆盖任意chunk segmentation、cap+1、length drift、truncation、encoding/decompression bomb、
deep JSON/record cap、slow consumer peak memory、schema/private fields和@2 ref closure。crash tests覆盖write/
fsync/rename/row/event，预存target、symlink、short write、disk full与GC；恢复后只能是committed artifact或
private orphan/aborted。

live验收要求large UniProt response在固定小resident budget下完成且不base64内嵌，raw/parsed artifacts可
离线重算；oversize/truncation在下游前fail closed且partial artifact为零；wire只传bounded handle，restart
不重复provider call，public面无secret/path。性能gate验证RSS/queue/spool bounded而不制造无用流量；未来
schema仍需两次positive E2E加fault，本文不改变当前GO。

完成这些验收前，不得声称“大provider body已bounded streaming”或“artifact persistence是atomic stream
commit”。

## Non-goals

- 不修改AOX/HMM科学规则、provider query、identity mapping或agent调用策略。
- 不把所有artifact迁移到外部云object store；近期可继续使用可信Host本地filesystem+单进程SQLite。
- 不把stream chunk、FD、path、buffer或storage backend暴露为agent工具参数。
- 不把partial/truncated response解释为healthy empty、degraded success或可用于下游的partial artifact。
- 不承诺任意format都有stream parser；不支持时通过显式bounded capability失败。
- 不以4 MiB control-frame cap、`Content-Length`、mtime、readonly chmod或filesystem basename替代完整
  digest/completeness/atomic commit。
- 不在本文解决provider retry decision、batch checkpoint或response-delivery outcome unknown；相邻proposal
  分别定义这些状态。

## Relationship to existing proposals and stable contracts

- [Harness doctrine](../00-harness-doctrine.md) 要求harness把真实资源与failure结构化呈现；本文的cap、
  backpressure和completeness属于world constraint，不是agent策略。
- [Capability engines](../03-capability-engines.md) 要求provider limiter、canonical artifact与bounded engine
  output；stream limiter和artifact handles应作为其底层mechanics，而非新的engine truth。
- [Sandbox external capability bridge](../sessions/10-sandbox-external-capability-bridge.md) 定义sandbox只经Host
  supervisor调用外部能力；本文不让sandbox绕过bridge直接读取provider stream或Host path。
- [Artifact boundary docs](../execution-pipeline-docs/artifacts.md) 描述当前artifact ID/materialization/register
  用法；本文是未来内部storage/ingress演进，不把private stream API变成agent-facing path API。
- [Bounded streaming sandbox stdio capture](bounded-streaming-sandbox-stdio-capture.md) 处理子进程stdout/stderr；
  本文处理provider HTTP与artifact bytes。两者可共享bounded spool/digest/fsync primitives，但capture
  completeness和artifact license/validation schema必须分开。
- [Verified artifact materialization handoff](verified-artifact-materialization-handoff.md) 保护input Blob到
  provider/runner consumer的same-object consumption；本文保护provider output到Blob commit。未来应共享
  opaque stream handle、lease/fencing和streamed digest。
- [Transactional attempt-evidence collection](transactional-attempt-evidence-collection-and-root-closure.md)
  负责最终campaign archive；它只能收集本文已经atomic committed的artifact，不能把partial spool复制进
  archive后补成完整。
- [Unified provider evidence broker](unified-provider-evidence-broker.md) 可拥有provider response ingress SPI
  的统一组装，但raw bytes authority仍属于artifact boundary。

后续实施应先抽取小型共享stream/blob primitives，再由各owner组合；不能建立一个同时拥有credential、
scientific parser、artifact catalog、task terminal与public projection的provider/storage巨石。
