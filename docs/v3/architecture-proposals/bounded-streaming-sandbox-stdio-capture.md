# Deferred: bounded streaming sandbox stdio capture

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 Goal 已把 sandbox command 的 stdout/stderr 按原始 bytes 计算 digest、size 与 truncation，完整内容写入 attempt-local、Host-private、不可由 agent 解引用的 log artifact；public surface只保留 bounded safe summary和closed metadata。它仍使用 `Popen(..., stdout=PIPE, stderr=PIPE)` 后由读取线程把所有chunk累积在Host内存，进程结束或超时后才统一封存。

把 capture 改为流式 private spool 会同时改变 process supervision、timeout/kill、磁盘配额、private log ownership、digest finalization、partial-read error、repository state和recovery语义，属于跨层架构迁移。本 Goal 不在真实 cutover 前临时改写这条链，只记录独立方案与验收标准。

## Problem statement

1. sandbox/container 的内存限制不能限制 Host 进程中 `PIPE` reader 保存的完整输出；恶意或失控命令可用持续输出消耗Host内存。
2. 当前只有子进程退出后才获得完整bytes并写log；Host crash时既没有可恢复spool，也无法区分“命令确实无输出”和“capture未完成”。
3. timeout路径需要同时处理process group终止、两个stream drain和最终metadata；若读取线程异常被忽略，partial bytes可能被错误声明为完整raw payload。
4. 仅把内存list换成临时文件不足以建立合同：必须定义exclusive create、quota、fsync、rename/finalize、digest、retention和orphan recovery。

## Impact on agent autonomy

- agent应持续获得bounded、及时、可行动的公开stdout/stderr摘要，而不是因为Host内存压力导致整个runtime失联。
- harness必须忠实区分command failure、capture failure、truncation和partial evidence；不得把基础设施丢字节伪装成科学程序的完整输出。
- agent无权读取Host-private spool locator；它只消费logical stream identity、digest、size、completeness、truncation与opaque ref。
- 大输出不应迫使agent改变科学策略或用静默降级的替代命令；资源限制应以结构化错误和明确retryability呈现。

## Non-goals

- 不建立新的task/runtime真状态或第二套artifact catalog。
- 不把stdout/stderr当作默认科学artifact；需要发表的结果仍必须显式写入`/workspace/output`并经artifact boundary注册。
- 不允许public client或LLM通过opaque ref读取private raw log。
- 不在本提案中改变runner/HPC日志合同、provider evidence或AOX GO reducer。
- 不通过丢弃超限bytes伪造完整raw digest；若policy选择停止capture，必须显式标记incomplete。

## Target invariants

1. Host对每个stream只保留固定上限的public prefix/suffix或ring buffer，完整capture不在内存中无界增长。
2. raw bytes边读边写到attempt-scoped private spool；父目录`0700`、文件`0600`、exclusive no-follow create，禁止共享`/tmp` fallback和symlink traversal。
3. SHA-256与raw byte count随chunk增量更新；final metadata不需要重新把完整文件读回内存。
4. 每个stream具有closed状态：`complete`、`partial_capture_error`、`quota_exceeded`、`host_interrupted`；只有`complete`可声称digest覆盖该命令的完整captured stream。
5. reader异常、short write、fsync/close/rename失败都会让command evidence fail closed，不得只记录thread exception后继续宣称成功。
6. timeout/kill必须等待两个reader到达确定终态；超过bounded drain deadline则标记capture incomplete并产生稳定error code。
7. public summary只从bounded raw buffer replacement-decode后做logical-path映射与diagnostic sanitizer；raw digest/size始终针对未decode、未sanitize的bytes。
8. private spool quota由attempt storage capability统一配置；quota exhaustion不能耗尽Host filesystem，也不能静默截断后标记complete。
9. finalized private record append-only；临时spool通过atomic finalize或显式state区分，Host restart可识别并处理orphan而不暴露内容。
10. 同一run/stream只产生一个canonical private record和一个opaque ref；重试/recovery幂等，不覆盖已finalized bytes。

## Proposed model

```text
SandboxProcessSupervisor
  ├─ stdout CaptureSink
  └─ stderr CaptureSink

CaptureSink
  stream / attempt + run identity
  exclusive private spool handle
  incremental sha256 / byte_count
  bounded public buffer
  quota + drain deadline
  capture_state / failure_code

PrivateCommandLogRecord
  opaque ref / stream / raw_digest / raw_size
  capture_state / finalized_at / retention
  private storage authority

PublicStreamMetadata
  raw_digest / raw_size_bytes / truncated
  capture_complete / failure_code?
  safe summary / opaque log_ref?
```

`PrivateCommandLogRecord`的storage locator不进入domain DTO、event、workspace projection或bundle。`PublicStreamMetadata`只有在private record成功finalize后才携带opaque `log_ref`；capture不完整时仍公开已捕获prefix的digest/size，但必须同时声明`capture_complete=false`，cutover verifier据此fail closed。

## Execution sequence

1. Host在spawn子进程前，为stdout和stderr分别exclusive创建private spool并初始化digest/quota state；任一创建失败则不启动命令。
2. reader以固定chunk读取pipe；每个chunk先检查quota，再执行bounded write、digest update、byte count和public buffer update。
3. supervisor等待process exit或timeout；timeout时终止process group，再在bounded deadline内等待reader EOF。
4. 两个CaptureSink分别close、fsync并atomic finalize；任何一步失败都生成typed capture failure，不复用普通`sandbox_exec_nonzero`。
5. repository在同一逻辑完成路径保存per-stream private record与public metadata，再更新SandboxRun终态。
6. restart recovery扫描未finalize spool及RUNNING run，根据process lease和capture journal标记`host_interrupted`，不猜测完整性。

## Migration plan

1. 定义versioned `CaptureState`、`PublicStreamMetadata`和private spool lifecycle；补state-machine/property tests。
2. 在现有bytes capture旁shadow写spool，只比较digest/size，不改变public结果；测量性能、磁盘占用和错误路径。
3. 把digest/size authority切到CaptureSink，仍保留旧in-memory bytes用于结果比较；发现不一致立即fail closed。
4. 将public summary改为bounded buffer生成，移除完整bytes join；加入reader exception与drain deadline传播。
5. 接入attempt storage quota、orphan recovery与private retention；验证多service instance不能重复finalize。
6. 删除旧list accumulation路径；更新S09、OpenSpec、Host operator文档和cutover verifier schema。

## Compatibility and rollback

- 新字段以versioned metadata或显式schema revision发布；旧run reader可投影`capture_complete=unknown`，不得补造`true`。
- shadow阶段不把spool结果用于GO证据；切换后若需回滚，相关run标记non-cutover，不能回退为无界capture并仍宣称同一合同。
- 旧private log按原retention保留；迁移不重新读取并复制到public event。
- runner/HPC远端日志保持独立authority；只有Host sandbox command使用本提案的CaptureSink。

## Risks

- 磁盘替代内存成为新DoS：必须preflight空间、per-stream/per-attempt quota和reserved emergency margin。
- timeout后pipe不EOF造成runtime挂死：使用process group kill、reader deadline和明确incomplete状态。
- spool写入拖慢子进程并改变行为：评估chunk size/backpressure，禁止无界async queue。
- crash窗口导致record与file不一致：使用journal或temp-to-final atomic rename，并以repository state验证。
- public prefix遗漏关键尾部错误：采用固定prefix+suffix或ring policy，并在metadata中声明summary policy/version。
- operator debug能力扩大泄漏面：opaque resolver需独立认证、审计、最小retention，LLM无自动读取authority。

## Acceptance criteria

- 生成至少10 GiB逻辑stdout/stderr的压力fixture时，Host RSS增长保持在配置的固定上限内，磁盘quota按合同fail closed。
- 正常、nonzero、timeout、SIGKILL、reader exception、short write、ENOSPC、fsync失败和Host restart均产生确定的per-stream capture state。
- 对完整capture，公开raw digest/size与private spool逐byte离线重算一致；对不完整capture，任何cutover evidence均拒绝。
- stdout和stderr同时高流量、同时超限时，各自保留独立metadata与opaque ref，不串流、不覆盖。
- public workspace、ToolResult、event、API、eval和AOX bundle零命中private locator/raw bytes；operator gated resolver可审计地读取授权记录。
- 现有小输出命令、UTF-8/invalid UTF-8、二进制NUL、timeout和nonzero语义回归通过，agent获得稳定code/stage/retryability。
- 并发run和Host restart测试证明spool exclusive ownership、finalize幂等、orphan处理及retention没有产生第二套产品真状态。
