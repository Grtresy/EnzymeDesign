# Deferred: transactional attempt-evidence collection and artifact-root closure

Status: proposed; not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 AOX/HMM evidence runner 会在 attempt 收口后从 SQLite、artifact catalog、Blob、
sandbox source snapshot、public receipts 与 MICU ledger 组装 bundle，并用 no-replace
方式写出单个 sealed evidence file。单文件不可覆盖是必要约束，但它不等于整次 collection
是一个 transaction，也不证明最终 artifact root 的实际文件集合与 bundle 声明集合完全
相等。

本 Goal 可以修复明确的 framing、provider batching 与 public-scanner 误报；不能在不迁移
collector/archive/verifier ownership 和 schema 的情况下，把逐文件写入描述为原子 commit。
因此，本提案只记录两阶段 collector、artifact-root exact closure、失败原子性、恢复与迁移
方案，不修改当前 collector，不改变现有 `aox_blank_world_attempt_bundle@1`，也不将提案语义
追溯附加到 r15 或后续当前-schema bundle。

任何 live GO 仍只能依据当前实现真正生成并由当前 verifier 接受的证据。提案文档本身不是
receipt、root closure 或 cutover qualification。

## Current evidence and failure mode

1. 当前 collector 通过 `_write_sealed_bytes` 一类 no-replace primitive 把多个文件依次写入
   最终 evidence/archive root。每个已成功写入的文件不可原位覆盖，但文件集合在循环期间
   对 consumer 可见。
2. `build_attempt_bundle` 在后续阶段规范化 declared artifacts；public-safety scan、semantic
   validation 和 offline verification 也发生在若干 evidence bytes 已落入 final root 之后。
3. 若读取第 N 个 artifact、复制 bytes、构建 inventory、public scan、bundle serialization
   或 verification 在中途失败，前 N-1 个文件可以永久留在 final root。它们可能未被 bundle
   引用，也可能缺少统一 terminal marker。
4. 单文件 append-only/no-replace 只证明该 path 没被覆盖；它不证明 collection 的 all-or-
   nothing，不证明目录中没有额外文件，也不证明 source root 在枚举和复制之间未变化。
5. failure fallback 若继续写同一 final root，可能与 partial positive evidence 共存、命名冲突，
   或让 consumer 错把某个早期 bundle/verification 文件当成 committed archive。
6. 当前 positive path 没有统一要求 `actual regular files under artifact root == declared artifact
   inventory`。部分 fault closure 已做局部 equality 检查，但它不是所有 attempt/branch 的
   directory-wide invariant。
7. 给 public scanner 增加宽泛目录例外不能修复 root closure；它反而会让未声明 Host-private
   或 diagnostic file 更容易进入 public archive。
8. collector 开始时若仍有 SQLite、Blob、sandbox、provider callback 或 report writer，任何
   inventory 都只是竞态 snapshot。事务式 publication 不能替代 writer retirement/quiescence。

## Relationship to other proposals

[process-isolated live-attempt supervision](process-isolated-live-attempt-supervision.md)
解决父进程如何有界退休 attempt child，并在 OS 确认本地 writer 消失后才读取 roots。
[durable async controlled operation and quiescent sealing](durable-async-controlled-operation-and-quiescent-sealing.md)
解决长 provider operation、continuation、lease/fencing 与 Host mutation freeze。

本提案只在这些 writer/quiescence 前置事实成立后开始 collection：

- transactional collector 不能证明一个隐藏线程、container、SQLite handler 或远端 callback
  已退休；收到未经验证的“quiet”布尔值不构成 authority；
- process isolation/async continuation 即使落地，也不自动提供 archive exact closure；它们仍需
  本提案的 prepare/commit 与 inventory equality；
- 本提案不改变 task、operation、approval、report 或 campaign reducer 的 canonical ownership，
  也不允许 collector 修补业务终态；
- 若 quiescence 不可证明，collector 不进入 prepare。父 supervisor 可以在独立 failure root
  写 fatal、non-eligible 事实，但不能发布普通 attempt archive。

## Agent-harness principles

- harness 只忠实封存实际 canonical state 和 bytes，不替 agent 选择科学分支、补产物、重跑
  operation、自动批准或把失败解释成 healthy empty。
- declared inventory 是对已观察 artifact 的证明，不是生成缺失 artifact 的指令。
- archive consumer 只读取一个明确 committed generation；partial staging、orphan directory 和
  无 marker root 永远不是产品真状态或 cutover evidence。
- 任何 missing、extra、duplicate、alias、mutation 或 unreadable fact 都显式 fail closed；不以
  “尽量收集”缩小声明集合来制造可验证成功。
- public archive 与 Host-private diagnostic/root 严格分离。collector 不通过 scanner exemption
  把私有 path、SQLite/WAL、raw log 或 credential-bearing bytes 公开化。
- source artifact identity、artifact catalog row、copied bytes 和 archive inventory 必须形成一条
  可离线重算的闭合链，而不是依赖 mutable path 名或 collector 进程记忆。

## Target topology

```text
quiescent attempt roots (read-only collector view)
  |-- canonical SQLite snapshot / catalog
  |-- sealed Blob and typed source roots
  |-- public receipt inputs
  `-- MICU snapshot
          |
          v
private sibling prepare root (not consumer-visible)
  |-- artifacts/                 exact copied artifact closure
  |-- artifact-root-manifest.json
  |-- attempt-bundle.json
  |-- offline-verification.json
  `-- evidence-prepare.json
          |
          | validate all bytes, semantics, public safety, closure and source stability
          v
commit
  |-- preferred: fsync + atomic no-replace rename of complete directory
  `-- constrained fallback: publish closed commit marker last
          |
          v
immutable committed attempt archive
```

Collector 必须使用与 final archive 同 filesystem 的 sibling staging directory。staging name
包含 opaque transaction id，不含 session prompt、Host path 或 secret。final directory 和 reserved
commit marker 在 prepare 开始时必须不存在；预存 leaf、symlink 或 identity drift 直接拒绝。

## Two-phase protocol

### Phase 1: prepare

1. 接收一个 typed、只读的 attempt-root capability 和已经验证的 quiescence receipt；冻结
   SQLite high-watermark、catalog root digest、Blob/source root identity 与 MICU snapshot identity。
2. exclusive/no-follow 创建 private sibling staging root 及预声明目录，mode 默认为 `0700`；
   staging 不进入 public workspace、artifact catalog 或 campaign reducer。
3. 从 canonical SQLite/catalog 枚举 exact artifact universe。枚举结果必须由稳定主键排序，
   禁止“扫描目录然后猜 artifact row”。
4. 对每项 artifact 在 source 端先验证 type、regular-file/tree shape、size、digest、provenance 和
   semantic profile，再复制到 staging `artifacts/`，复制后重新计算 bytes/tree digest。
5. 枚举 staging `artifacts/` 的实际 regular-file universe，生成
   `aox_attempt_artifact_root_manifest@1`，并验证 actual set 与 declared set exact equality。
6. 构建 attempt bundle、safe public projections 和所有 bundle-level receipt；对 decoded source、
   report、diagnostic projection 与 manifest 实施当前 public-safety/semantic checks。
7. 在 staging bytes 上运行完整 network-free verifier。它不得通过 source Host path 回读缺失
   bytes，也不得向 provider、runner、UI 或 mutable SQLite 查询补充事实。
8. 重新读取 source high-watermark/root digest/quiescence identity，证明 prepare 期间 source 未
   漂移；任何变化使 transaction abort。
9. 写 `aox_attempt_evidence_prepare@1`，绑定全部 component digest、verification result、source
   before/after identity、root manifest、schema/version 和 intended final basename。

prepare 完成仍不表示 archive 可消费。consumer、campaign reducer 和 UI 必须忽略 staging root。

### Phase 2: commit

首选 commit 是同 filesystem 的 whole-directory no-replace rename：

1. fsync staging 内每个 file，再从叶到根 fsync directory；
2. 最后一次验证 source high-watermark、quiescence receipt、staging tree digest 和 final target
   absent/no-symlink；
3. 使用具备 `RENAME_NOREPLACE` 等价语义的 atomic directory rename；不得先删除/覆盖 target；
4. fsync final parent directory，随后以 read-only reopen 重算 commit identity。

若目标平台不能对目录提供可证明的 no-replace atomic rename，可采用显式 marker-last 模式：

1. final generation directory 必须使用不可猜、唯一 transaction id，且 consumer 从不按
   “latest directory”自行发现；
2. 完整 generation fsync 后，在稳定 campaign archive parent 中通过 sibling-temp + fsync +
   no-replace rename 最后发布 `.aox-attempt-evidence-commit.json`；
3. marker 精确绑定 generation basename 与所有 component/root digests；只有 marker 指向的
   generation 可消费；
4. marker 后 generation 与 marker 都 immutable。任何修改只能产生新 generation/schema，
   不能 repair committed archive。

两种模式都必须生成同一 `aox_attempt_evidence_commit@1` 语义。平台选择进入 effective config
和 receipt；不能把 marker-last 描述成 whole-directory atomic rename。

## Proposed schemas and layout

建议 committed archive：

```text
<attempt-generation>/
  artifacts/
    <safe canonical relative paths...>
  artifact-root-manifest.json
  attempt-bundle.json
  offline-verification.json
  evidence-prepare.json
  .aox-attempt-evidence-commit.json
```

`artifacts/` 是 exact scientific/catalog artifact closure。bundle、manifest、verification、prepare
和 commit metadata 位于其外，防止验证 metadata 自引用进入 artifact inventory；commit marker
仍绑定它们全部。

### `aox_attempt_artifact_root_manifest@1`

闭集字段建议包含：

- `schema_id`, `attempt_id`, `artifact_root_identity_digest`；
- ordered entries：canonical `relative_path`、artifact id/kind/format/semantic type、size、mode
  class、content/tree digest、catalog provenance digest、producer operation/task/source refs；
- `entry_count`, canonical entries digest, actual-root tree digest；
- catalog SQLite high-watermark/schema identity 与 source Blob/root identity；
- explicit closure verdict 和 stable failure code（只在 prepare-private failure record 中出现）。

### `aox_attempt_evidence_prepare@1`

闭集字段建议包含：

- transaction/attempt/campaign identity 和 intended final basename；
- launch/config/workflow/schema identities；
- source quiescence、高水位和 root digest before/after；
- artifact-root manifest、bundle、offline-verification 与 public-safety result digests；
- staging tree digest、prepare timestamps/monotonic sequence、collector implementation digest；
- `commit_ready=true` 仅在全部 gates 通过后允许出现。

### `aox_attempt_evidence_commit@1`

`.aox-attempt-evidence-commit.json` 建议只含：

- exact schema/transaction/attempt/campaign identity；
- commit mode 和 generation basename；
- prepare、artifact-root manifest、bundle、verification 和 complete-generation tree digests；
- committed entry counts/sizes；
- final parent identity 与 no-replace publication receipt；
- commit timestamp、collector implementation identity 和 closed compatibility version。

marker 不包含 credential、Host absolute path、storage URI、raw report/provider bytes 或 mutable
status。consumer 必须 closed-schema parse 并独立重算所有绑定 digest。

## Artifact-root full closure

committed `artifacts/` 必须满足以下 exact set equality：

```text
every regular file/tree leaf under committed artifacts/
  <=> exactly one declared artifact/root-manifest entry
  <=> exactly one authorized catalog/provenance identity
```

具体不变量：

1. missing 和 extra file 都拒绝；hidden file、temporary file、editor backup、lost+found、旧 bundle
   或 failure diagnostic 不能被忽略。
2. relative path 必须 canonical、UTF-8、normalized、case policy 明确；拒绝 absolute path、`.`、
   `..`、空 segment、NUL、separator alias、Unicode normalization alias、case-fold collision。
3. symlink、junction、device、socket、FIFO 和其他 non-regular node 全部拒绝。hardlink 必须拒绝，
   或在未来 schema 明确表达 inode topology；`@1` 默认拒绝以避免一个 byte object 冒充多个
   独立 artifact。
4. artifact id、relative path、content/tree digest、size、mode class、semantic type 和 provenance
   必须一一对应；重复 id/path/digest alias 不能自动 collapse。合法相同内容仍需两个明确 entry。
5. directory artifact 必须展开为自验证 typed tree envelope；不能把 directory basename 当一个
   opaque file，也不能穿越 symlink读取树外 bytes。
6. source copy 前后都验证 digest/stat/root identity；copy 后、bundle 后和 commit 前重新枚举
   staging。任一次 mutation、TOCTOU、size/digest drift 都 abort。
7. public archive 不包含 SQLite、WAL/SHM、Host-private command log、credential、runner config、
   raw private provider cache、sandbox mutable working state或未声明 temporary bytes。
8. offline verifier 只能从 committed archive 与显式 immutable prerequisite读取，不能依赖原
   attempt roots仍存在。

## Failure atomicity and recovery

- prepare 任一步失败时 final target/commit marker保持不存在。staging 是 noncanonical private
  residue，可在验证 identity 后删除或移入 Host-private quarantine；删除行为不是产品状态迁移。
- whole-directory rename 前 crash 只留下 staging；rename 成功但 parent fsync 前 crash必须按平台
  恢复协议判定 durability，不能假设成功。恢复器只验证既有 generation/marker，不重写内容。
- marker-last 模式中，marker 前 crash留下 orphan generation；没有 matching committed marker 时
  consumer、reducer和verifier入口一律拒绝。orphan可以隔离/GC，不能“补 marker”除非重新从
  quiescent source完整 prepare与验证。
- marker 发布后 archive immutable。发现 drift、extra file或 verifier bug时只能撤销资格并生成
  新 schema/generation；不得修补或覆盖已 committed bytes。
- ordinary positive/negative attempt evidence与 fatal collector failure分离。collector failure由
  parent/campaign在 final attempt archive之外的 append-only failure root记录，明确
  `attempt_archive_committed=false` 和 unknown completeness。
- failure fallback不得向 partial positive archive追加 `error.json`、新 bundle或“完成”marker；
  也不得把 catalog/task/report状态机械改成 failed/completed。产品业务终态仍只来自 canonical
  agent/Host path。
- 若 artifact completeness、SQLite closure、ledger-after或external outcome未知，failure receipt
  必须保留 unknown；不得用空列表、零计数或缺省 digest冒充证明。

## Ownership and security

- Host attempt lifecycle/quiescence authority决定 collector是否可启动；collector不能自签 quiet。
- artifact catalog/repository定义 declared universe；collector只有 read capability，不写 artifact row。
- evidence collector拥有 private staging和prepare schema，但不拥有 task/report/operation状态。
- archive publisher是唯一 final commit authority，使用 no-replace capability；verifier和campaign
  reducer只读 committed generation。
- public scanner继续采用精确逻辑 allowlist和typed source context；root closure不是放宽 scanner
  的理由。unknown absolute path、private locator与secret任何时候都拒绝。
- staging、quarantine和fatal raw diagnostics必须为 Host-private，mode/ownership最小化，绝不通过
  artifact ref或public API授予读取 authority。
- schema digest、collector implementation digest和commit mode进入 archive identity，防止不同
  collector语义生成同一看似兼容 receipt。

## Alternatives considered

### Continue sequential no-replace writes

实现最小，但只提供单文件完整性；中途失败仍留下 consumer-visible partial set，无法满足
transaction或root closure。不采用。

### Write commit marker last without a private prepare phase

能阻止部分 consumer误读，但仍可能在 final namespace留下大量孤儿，且在 marker前没有统一
offline verification/source-stability recheck。只允许作为完整 private prepare之后的受约束
publication模式，不单独采用。

### Put every byte into one tar/zip

单文件 rename简单，但 archive parser、path traversal、compression bomb、mode/symlink语义和随机
artifact验证增加新攻击面；大 artifact还会要求额外空间与全量重写。可以作为未来 storage
format，但不能替代 logical inventory/root closure。

### Use SQLite transaction for filesystem publication

SQLite transaction不能原子覆盖不同 filesystem file writes/rename/fsync。把“committed”row先写
数据库仍有 DB/file split-brain；需要本文的 filesystem commit protocol。不采用为单独方案。

### Ignore extra files not referenced by the bundle

会隐藏泄漏、stale artifact和collector bug，无法证明blank-world closure。明确拒绝。

## Migration plan

1. **Shadow inventory**：在不改变现有 output 的情况下只读枚举当前 attempt catalog/root，生成
   private diagnostics，量化 missing/extra/alias/symlink和root size；不得影响cutover verdict。
2. **Pure prepare planner**：实现无写副作用的 canonical inventory builder、三个 schema的golden
   serializer/parser与离线root-closure verifier；锁定closed-field/digest规则。
3. **Private staging + fault injection**：引入same-filesystem staging、copy/recheck/fsync和每个步骤
   的 crash/failure seam；仍不发布为canonical archive。
4. **Shadow `@1` compare**：对非cutover/fresh attempts同时运行旧collector和新prepare，在private
   scope比较artifact universe、bundle semantics和offline result；drift保持NO-GO并分类。
5. **Versioned publication**：发布新的attempt archive/bundle generation（预期 `@2`），使campaign
   reducer只消费valid commit marker/atomic generation；offline verifier和public projection同步迁移。
   historical `@1` reader保留只读验证，绝不原位升级或补commit marker。
6. **Fresh live qualification**：在同一新commit/config上重新执行两次独立positive、一次controlled
   fail-closed fault和至少一次Chrome approval/terminal observation。每次都验证root exact closure、
   no partial final visibility、MICU连续账本和network-free archive portability，之后才能采用为GO gate。
7. **Retire legacy writer**：确认无外部caller依赖逐文件final layout后，删除旧publication path；
   rollback只切回明确NO-GO的旧reader/writer，不把旧archive解释为满足新closure。

## Compatibility and rollback

- `aox_blank_world_attempt_bundle@1` 与历史 directory layout 保持只读可验证，但其结果只能表达旧
  schema实际证明的内容，不能获得 `artifact_root_closed=true`。
- 新 schema/ref必须 correctional version bump；consumer按schema和commit marker显式分流，不做
  field-presence heuristic或“最近版本”猜测。
- 迁移期间 campaign config pin collector/manifest/commit mode digest；两个positive不得混用旧新
  collector identity。
- 若新collector出现错误，停止新live attempt并回滚到明确NO-GO旧路径；已经committed的新archive
  保持immutable，不能降级重写。
- external tooling若依赖旧单文件路径，必须通过只读compatibility exporter从已committed archive
  派生非canonical副本；exporter output不能回流成cutover evidence。

## Risks and mitigations

- **双倍磁盘与复制时间**：prepare需要source+staging并存。设置显式root byte/file cap、preflight
  free-space estimate、streaming digest和bounded failure；不得因资源压力跳过copy verification。
- **大root验证时间**：使用一次有序枚举和streaming digest，性能基准覆盖高file-count/large bytes；
  不用抽样替代exact closure。
- **rename/fsync平台差异**：平台能力进入preflight/receipt；不支持可靠no-replace时使用严格marker-
  last generation，无法证明任一模式的平台保持NO-GO。
- **source在prepare期间变化**：quiescence+before/after high-watermark/root digest双重检查；任何drift
  abort，不能无限重试并最终选一个幸运snapshot。
- **schema自引用**：`artifacts/` inventory与bundle/verification/prepare/commit metadata分层，marker
  绑定所有component digest；golden tests防止循环或遗漏。
- **GC误删**：只清理无commit marker且超过retention、identity完整的staging/orphan；GC无权修改
  committed generation。
- **failure evidence混淆**：fatal collector receipt使用独立schema/root并明确unknown字段，不复用
  positive bundle名或commit marker。
- **agent可用性退化**：agent仍只见artifact ids、SDK result和结构化failure；prepare实现细节不进入
  prompt，也不要求agent编排commit步骤。

## Acceptance criteria before implementation can become authoritative

1. schema golden/closed-field tests覆盖canonical JSON、duplicate key、nonfinite number、unknown/missing
   field、digest drift和version mismatch。
2. root closure tests覆盖missing/extra file、duplicate id/path、case/Unicode alias、absolute/traversal、
   symlink、hardlink、FIFO/device/socket、directory artifact和source-tree drift。
3. fault injection覆盖每个source read、copy、digest、manifest、bundle、public scan、offline verify、
   file fsync、directory fsync、rename、marker write和parent fsync边界；任何prepare failure都不得有
   consumer-visible committed final。
4. crash-recovery tests分别覆盖rename前、rename后/parent-fsync前、generation完成/marker前、marker
   temp、marker rename后和reopen verify；recovery只分类，不repair bytes。
5. source mutation/high-watermark tests证明prepare期间SQLite/catalog/Blob/root任何变化都会abort。
6. public-safety tests继续拒绝credential、private URL/locator、Host/HPC path、SQLite/WAL/private log；
   exact AOX logical suffix与narrow Python path-join exception不能演化为directory/global slash allowlist。
7. network-free portability test在移除原attempt roots和禁网后仍从committed archive重算全部digest、
   semantic closure和artifact-root equality。
8. large-root tests覆盖预期最大file count/bytes、bounded memory、disk exhaustion和interrupted copy；
   performance优化不得改为抽样。
9. failure atomicity test证明collector失败不会发布ordinary attempt archive，不会追加partial positive
   root，不会修改task/report/operation canonical truth，fatal receipt准确标记unknown completeness。
10. migration tests证明历史`@1`只读reader仍工作但不获得新closure claim，mixed collector identity
    campaign被拒绝，compatibility export不回流。
11. 最终必须在fresh roots上完成两次独立positive、一次controlled fault与Chrome验证；所有archive
    都有可重算commit/prepare/root manifest，且campaign reducer只从三份committed digest得出GO。

在以上条件全部满足并完成新schema的fresh live qualification前，本提案保持
**proposed / not implemented**。
