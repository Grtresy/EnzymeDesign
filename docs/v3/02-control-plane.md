# V3 Control Plane

## Canonical state

control plane 保存结构化 identity、state、lease/fence、receipt 和关系，不保存通用文件正文。
主要聚合为：

- session、access、task/dependency/finish、lane、agent member、inbox、approval；
- runtime signal、session lease、runtime command、continuation delivery；
- project repository binding、session pin、credential、private namespace；
- agent Git workspace、checkpoint、publication intent/execution/published revision；
- Git LFS policy/object/link/closure/verification/pin/GC receipt；
- controlled operation、dispatch/observation/result handle；
- executor HPC workspace、revision execution request、job handle/observation/result；
- research file index、report draft/report、protocol file handoff/revision path ref；
- scientific attempt、selection、occurrence、disposition、effect adoption、deliverable/receipt；
- mutation scope/writer/quiescence snapshot/receipt、durable event 和 deployment schema state。

## Transaction boundary

repository mutation 使用短 `BEGIN IMMEDIATE` Unit of Work。一个 canonical command 涉及多个
repository 时必须 all-or-nothing。LLM、provider、Git remote、process、SSH 或 HPC 调用期间不持
SQLite 写事务。

每个实际执行线程创建并关闭自己的 connection。read scope 使用 `query_only`。WAL、busy timeout
和 retry 只解决局部 contention，不替代 owner、fence 或 idempotency。

## Identity 与 idempotency

idempotent replay 必须同时匹配 request digest 和 owner scope。相同 key 不同 payload 是冲突，
不能返回旧结果。外部 dispatch identity 至少绑定 operation digest、dispatch generation、backend
request identity 和 fence。publication identity 至少绑定 intent、commit/tree、closure 和 remote ref。

## Lease 与 fencing

- session runtime lease：一次 bounded agent turn；
- signal claim：一次 wakeup delivery；
- process epoch：attached process 的 Host callback；
- execution lease/fence：一次外部 effect lifecycle；
- continuation delivery fence：一次 result resume；
- workspace generation：一个 agent/remote workspace incarnation；
- mutation writer fence：一个 scope generation 的 canonical write authority。

stale writer 的迟到结果在 commit 边界拒绝。lease expiry 不等于外部取消或 task completion。

## Events 与 projection

durable event 是 canonical mutation 的审计输出，不是另一套 owner。public projection 从当前 typed
repository rebuild；event replay 或 restore 必须匹配 `file_workspace_public@1`、tool catalog digest
和 schema bundle digest。旧 event/catalog context 终止为 stale，不合成 alias。

## File references

SQLite 中的 file relation 只保存 typed revision/path identity。验证至少覆盖 repository binding、
publication、commit/tree、path normalization、object type/OID、content digest、size 和 LFS closure。
任何 locator 或 mutable checkout path 都不能替代。

## Final schema

normal migration loader 只认识 `001_file_workspace_final.sql` 和 exact manifest。fresh empty database
写 `fresh_install_complete`；offline removal 成功写 `offline_removal_complete`。old、unknown 或
`offline_removal_incomplete` 在 mutation 前拒绝。

final schema 中保留 `legacy_removal_ledger/items` 只用于证明 deployment removal 完成与幂等重试，
它们不提供旧领域读取、写入、投影或 tool surface。
