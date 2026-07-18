# Deferred: immutable per-run HPC SIF execution snapshot

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 Goal 只实施一组有边界的纠正性加固：runner 绑定自己的 SIF locator，严格验证已知 AOX command template 中的 direct `apptainer exec`、runner-owned image token 与预期 entrypoint，并在同一远端执行链中对该 locator 做 pre/post SHA-256；两次 digest 不同、identity marker 缺失或格式异常均 fail closed。

这些措施能拒绝 locator 注入、额外 SIF 和执行期间未恢复的镜像变化，适合当前 trusted-Host-only runner 与 blank-world cutover 的局部范围。但它们不等价于“实际被 Apptainer 打开的 bytes 已不可变地绑定到 digest”。建立 per-run protected snapshot 需要新的 runner authority、storage/lease lifecycle、deployment capability 和 evidence schema，属于独立大架构调整；本轮只记录，不实现，也不把未来保证写成当前事实。

runner 从 typed intent 编译命令、消除 shell parser/rewriter 的另一项大调整，单独记录在 `runner-owned-hpc-command-compiler.md`。本提案只负责 immutable SIF materialization 与 snapshot-to-execution binding。

## Current implementation evidence

1. `apps/mcp-hpc-runner/src/mcp_hpc_runner/server.py::_bind_runner_toolchain_contract()` 根据 runner manifest 选择 SIF locator 与 contract digest，并拒绝 caller 直接提交 runtime request/identity。这已经把部署 locator 选择放回 runner 信任边界。
2. `apps/mcp-hpc-runner/src/mcp_hpc_runner/ssh_runner.py::_command_with_toolchain_attestation()` 对全局 locator 执行 `/usr/bin/sha256sum`，随后让 Apptainer 按 pathname 打开镜像，payload 结束后再次对同一路径执行 `sha256sum`。
3. `apps/mcp-hpc-runner/tests/test_toolchain_attestation.py` 固定了 pre-hash、direct exec、post-hash 和 marker 的顺序，并证明 digest 变化或 marker 异常 fail closed；它没有、也无法仅靠 shell ordering 证明 hash 与 Apptainer open 指向同一 immutable object。
4. runner preflight 只证明 locator 在检查时可读，明确不声称 execution digest。跨层 `toolchain_runtime_identity` 是 runner 返回的闭集投影，不携带 kernel-level open handle、snapshot lease 或 protected-object identity。

### Global locator hash-to-open TOCTOU

pre-hash 完成时 `sha256sum` 已关闭其文件，Apptainer 随后按 pathname 重新打开镜像。对该 locator 有写或替换权限的同 UID 进程，可以执行：

```text
global path -> image A
hash(A) succeeds
global path -> image B
Apptainer opens/runs B
global path -> image A
post-hash(A) succeeds
```

pre/post digest 相等只能证明两个采样时刻的 pathname 内容相等，不能证明中间被 Apptainer 打开的对象就是 A。同用户并发发布 SIF、部署脚本 atomic rename、运维回滚或恶意同 UID 进程都可触发这个类别；它不要求 caller 能伪造 runner metadata。

把 hash 调得更靠近 `apptainer exec`、增加第三次 hash、比较 mtime/inode 或使用 advisory lock 可以缩小或检测部分窗口，但只要 hash 与 open 是两个系统调用且执行仍解析 mutable global pathname，就不能建立不可绕过的 same-object guarantee。

## Impact on agent autonomy and trust

- agent 应把策略预算用于科学路径，而不是推测 operator 是否在一次 operation 中途替换部署镜像。
- harness 必须结构化呈现 snapshot 是否成功 sealed、实际 snapshot digest、lease/execution binding 与稳定 failure reason；不能用“路径前后 hash 相同”过度声称执行 bytes 已绑定。
- 同一 operation 的世界必须稳定：snapshot 建立后，global deployment locator 更新只影响后续 operation，不影响当前 run。
- `TOOLCHAIN_SNAPSHOT_UNAVAILABLE`、`TOOLCHAIN_DIGEST_MISMATCH`、`TOOLCHAIN_SNAPSHOT_LEASE_STALE` 等事实应低摩擦返回给 agent，但 private locator、UID、mount 和 snapshot path 不得暴露。
- snapshot 失败不能触发 native binary、旧 global locator、mutable tag 或其他 SIF 的隐藏 fallback；agent 可以改变科学策略，但不能覆写执行事实。
- 错误的 digest binding 会污染 artifact provenance、科学可复现性和 cutover 判断，因此新 schema 未完成前，当前 @1 identity 必须保持窄化表述。

## Non-goals

- 不改变 `session + task board + approval + controlled operation + artifact` 的顶层真状态，也不引入第二套 scheduler。
- 不改变 AOX motif、UniProt/NCBI identity、文献证据、scientific fail-closed 或 GO reducer 的科学语义。
- 不开放 runner 给不可信 Host，不允许 agent/caller 选择 private locator、snapshot path、mount namespace 或 attestation 字段。
- 不在本提案中设计 runner-owned typed command compiler；该 ownership、plan schema 和 parser retirement 见独立 compiler 提案。
- 不扩张成通用容器 registry、镜像构建/签名平台或完整软件供应链治理系统；这里只消费已批准 deployment binding，并保证本次执行的 SIF materialization。
- 不承诺第一阶段覆盖 Slurm。compute-node 内 snapshot staging/attestation 未落地前，Slurm 不得声称 immutable execution snapshot identity。
- 不用 hardlink、mtime cache、advisory lock、只读 shell variable 或同 owner 的 `chmod 0444` 冒充不可变 snapshot。

## Target invariants

1. 每个受证明 operation 在 payload 启动前获得一个 per-run `ToolchainExecutionSnapshot`；global deployment locator 后续变化不能改变该 run 的 bytes。
2. snapshot digest 在从一个已打开 source handle 向受保护目标 materialize 的同时计算；执行消费 sealed snapshot，而不是再次解析 global locator。
3. workload identity 与同 UID 并发进程都不能修改、替换、chmod、unlink 或重新绑定 active snapshot。部署没有合格 immutability primitive 时 capability fail closed。
4. snapshot digest 必须精确匹配 approved prerequisite/toolchain identity；不接受 mutable tag、latest、path-only identity 或 digest 缺失。
5. snapshot staging object 只有在 copy、hash、format/size validation、data/directory fsync 与 atomic seal 全部完成后才可被 lease；partial object 永不进入 executable namespace。
6. 每个 run 获得独立 snapshot lease 与 fencing token。底层 bytes 可以安全去重，但 authority、lifecycle 与 attestation 必须按 run 隔离。
7. launcher 只能解析已 sealed、active、fencing token 匹配的 snapshot handle；不能接受 caller path，也不能在 handle 失败后重开 deployment source。
8. lease 在 launch 与 process lifetime 内 pin 住 snapshot；GC 不能删除 active object，stale/duplicate lease 不能复活旧 authority。
9. runner-issued attestation 必须绑定 operation、logical contract、deployment epoch、snapshot digest、lease/execution binding 与 immutability mechanism；caller、Host projection 或 stdout marker不能自声明。
10. public projection 不含 source/snapshot path、SSH target、UID、mount detail、storage URI、credential 或 scheduler handle，只含闭集 opaque identity/digest 和 failure code。
11. 历史 @1 schema 永久按其原始 pre/post-path scope 验证；新 verifier 不把它升格解释为 immutable snapshot，也不在 @2 缺失时静默回退。

## Proposed ownership and object model

snapshot service 属于 runner execution boundary。Host/engine 仍拥有领域 intent、approval 与 controlled operation；runner-private deployment view 选择 source。snapshot service 不拥有 session/task/approval，也不编译科学命令。

```text
SnapshotPreparationRequest (runner-internal)
  run_id / operation_id / logical_contract_digest
  deployment_epoch / expected_image_digest
  requested retention class / execution mode

RunnerDeploymentBinding (runner-private)
  logical_contract_digest / deployment_epoch
  source locator or object ref / expected image digest
  supported snapshot mechanism / workload principal policy

ToolchainExecutionSnapshot (runner-owned, immutable)
  snapshot_id / run_id / image_digest / byte_size
  logical_contract_digest / deployment_epoch
  immutability_mechanism_id / protected_object_ref
  sealed_at / retention policy / private source observation

SnapshotLease
  lease_id / snapshot_id / run_id / fencing_token
  state / issued_at / expires_at / released_at

SnapshotExecutionBinding
  operation_id / run_id / snapshot_id / lease_id
  snapshot_digest / launcher_binding_digest / execution mode

SnapshotAttestationProjection
  schema / contract + deployment identities
  snapshot digest / immutability mechanism id
  execution-binding digest / mode / scope / outcome
```

`protected_object_ref`、source observation、真实 path、UID 和 storage details 只存在 runner-private store。public `snapshot_id` / `lease_id` 也应是 authority-free opaque reference，不能由 Host 用来直接打开 bytes。

## Snapshot materialization and execution protocol

1. runner 用 deployment binding 解析 source，禁止 caller locator、symlink traversal、relative escape 与 non-regular file；优先使用 `openat2(RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS)` 或平台等价约束，而不只检查终端路径字符串。
2. runner 从已经打开的 source file descriptor 流式复制到新的 staging object，同时计算 SHA-256 和 byte count。source 在复制期间变化不会破坏“sealed bytes 等于 digest”的事实，因为 digest 针对 copied object，而不是 pathname 的第二次采样。
3. staging 完成后验证 expected digest、SIF format/size 与 storage policy，`fsync` 数据及目录，再通过 atomic publish 进入 protected snapshot namespace。失败和 crash 留下的 staging object不能获得 lease。
4. immutability 由 workload 无法撤销的 authority提供，例如独立 runner service UID 拥有的只读 tree、经验证的 fs-verity object、受控 read-only mount 或等价平台服务。仅 `chmod 0444` 且 owner 与 workload 同 UID 不合格。
5. runner 为 run 签发带 fencing token 的 lease。允许 immutable content-addressed blob 去重，但每个 run 必须获得独立 lease/snapshot identity；mutable source inode hardlink默认禁止。
6. launcher 通过 runner-private resolver 把 active lease映射到 protected object，并在 execution namespace中只读呈现。它不得接受 Host/sandbox path，也不得允许 bind target覆盖 image。
7. launch前再次验证 lease state、fencing、protected object identity和digest metadata；验证对象与执行对象必须是同一 sealed handle/namespace binding。
8. process终止、output validation和attestation commit完成后释放lease。GC只清理无active lease、超过retention且未被审计保留的object。

目标 HPC 若缺少独立 runner authority，应先提供最小 snapshot broker/privileged staging service，或使用能证明不可变性的共享 object store。平台不支持时返回 capability unavailable，不能降级成同 UID `cp + chmod`。

## Relationship to adjacent proposals

- `single-source-hpc-toolchain-contract-registry.md` 回答“批准的是哪一个 logical contract/deployment binding”；本提案回答“这次 run 实际执行的是哪一个不可变 SIF object”。snapshot 引用 registry contract digest/deployment epoch，但 registry 不拥有 per-run lease或private object。
- `runner-owned-hpc-command-compiler.md` 回答“typed tool intent 如何变成实际 argv/launcher plan”。compiler只可接收 sealed snapshot handle；snapshot service不解析 tool argv或shell grammar。
- 两项可以独立 shadow：snapshot 可先 materialize但旧 path仍执行；compiler 可先生成plan但暂时指向旧 locator。两者单独都不能宣布完整 @2 execution binding。
- 组合切换时，`RunnerExecutionPlan.plan_digest` 必须绑定 `snapshot_id + snapshot_digest + lease_fencing_token`，最终 attestation同时证明 logical contract、compiler/plan与immutable snapshot。
- 若 single-source registry 尚未落地，可暂以冻结 runner manifest digest作为过渡输入；不得把过渡映射宣称成最终 single source。

## Migration plan

1. **冻结 @1 scope。** 明确当前 receipt 仅证明 trusted Host、SSH direct Apptainer、same execution chain pre/post pathname hash；增加 swap-and-restore threat fixture，展示未解决边界。
2. **调查 deployment primitive。** 核验 service/workload UID、共享文件系统、ACL、fs-verity/read-only mount、Apptainer path/FD行为、Slurm compute-node可见性、quota和crash recovery，形成target capability matrix。
3. **发布 snapshot schemas。** 固定 request、snapshot、lease、execution binding与attestation projection的canonical serialization/digest；只在runner内部使用，不改变Host protocol。
4. **shadow materialization。** 对AOX SIF从opened FD copy/hash/seal，生成private shadow record但仍执行旧 locator；比较 expected digest、source churn、latency、quota与GC，shadow receipt不参与GO。
5. **启用 protected-object canary。** 只为allowlisted SSH/AOX contract把现有执行命令中的image binding替换成active snapshot handle；其余argv仍走现有严格路径，便于把snapshot风险与compiler迁移解耦。
6. **接入 compiler plan。** compiler提案落地后，plan显式绑定snapshot lease；runner拒绝无snapshot的 @2 plan，同一operation只能选择一个attestation authority。
7. **迁移跨层 projection/verifier。** execution adapter、engine、core与cutover verifier closed-reconstruct @2 safe snapshot projection，验证prerequisite/contract/snapshot一致并保留path/secret negative tests。
8. **扩展 Slurm。** snapshot必须在compute node实际可见且不可写，job内launcher生成node-side execution binding；submit/login-node hash不足以声明Slurm @2。
9. **退役 global active path。** 确认所有目标contract和外部调用方均迁移后，禁止新cutover operation直接执行deployment locator；历史@1 reader永久保留。

## Compatibility and rollback

- @1/@2必须显式route/version；同一operation不双写两个权威identity，也不在 @2 snapshot failure后回退global locator。
- 旧RunSpec可由versioned legacy adapter用于non-cutover/debug，receipt保持原scope，不补造snapshot digest。
- 历史sealed bundle继续由@1 verifier复核；@2 verifier拒绝缺snapshot/lease/execution binding。
- canary回滚只关闭@2 route并让需要高保证的campaign保持NO-GO，不降低acceptance policy。
- snapshot/lease/attestation records append-only；回滚不删除active lease、审计retention或sealed evidence引用的private record。
- deployment source更新产生新epoch/expected digest；旧run继续使用其snapshot，新run不能继承旧lease。locator-only更新不重写历史identity。

## Security risks and mitigations

- **privileged broker扩大攻击面：** API只接受runner-internal typed request，采用最小权限、独立UID、固定roots、default-deny network/syscall policy并审计lease/fencing。
- **workload仍可改snapshot：** 必须用实际workload UID尝试chmod/write/rename/unlink/bind-over；任一成功即判deployment mechanism不合格。
- **symlink/hardlink/reflink误用：** source no-follow/beneath open；snapshot不与mutable source共享可写inode。hardlink默认禁止，reflink仅在protected destination和CoW语义验证后允许。
- **handle/path confusion：** resolver限定protected root并核对lease/fencing；禁止caller path、`/proc` alias、mount escape或bind覆盖image。
- **attestation spoofing：** @2 receipt经runner authority/authenticated channel签发，不依赖tool stdout marker；public projection exact-schema closed reconstruction。
- **GC race/use-after-free：** active lease pin object，launch/finish采用fencing与原子状态迁移；crash recovery宁可暂时泄漏空间，也不删除运行中snapshot。
- **digest正确但合同错误：** expected image digest、logical contract和deployment epoch共同绑定；单独SHA-256匹配不授权未批准tool。

## Performance and storage risks

- SIF可能数百MB至数GB，逐run full copy/hash增加启动延迟、共享文件系统I/O与容量压力。
- 推荐“immutable content-addressed blob + per-run lease/snapshot identity”：首次从opened FD materialize/seal，后续只在expected digest与保护机制相同且blob健康时复用bytes；每run仍有独立authority。
- 可用验证过的reflink/CoW、fs-verity或read-only object-store mount优化；不能用mutable source hardlink去重。
- digest cache只按immutable blob identity命中；pathname、size、mtime或deployment epoch缓存不能替代内容验证。
- 配置per-tool/global quota、并发materialization backpressure、staging TTL与审计retention。quota耗尽返回稳定resource blocker，不回退global locator。
- capability prewarm可提前materialize批准digest，但operation仍必须签发per-run lease并在launch时验证protected object健康。

## Test strategy

### Unit and property tests

- snapshot/lease canonical digest稳定；语义字段变化必变，unknown/private field fail closed。
- resolver拒绝symlink、parent traversal、non-regular file、path escape、stale lease、wrong fencing、wrong contract/epoch和digest mismatch。
- partial copy、fsync/rename failure与crash object不能被lease或launch。
- @1/@2 projection的schema/mode/scope严格隔离，malformed receipt不泄露private ref。

### Adversarial concurrency tests

- 在source copy前、copy中、seal后、launch前和execution期间持续交换global A/B，并执行“B运行后恢复A”；实际输出与attested snapshot digest始终对应同一object。
- 同UID进程尝试write、truncate、chmod、rename、unlink、hardlink和bind-over active snapshot，全部失败且不影响run。
- 多个并发run共享同一immutable blob时得到独立lease/fencing，任一run完成/取消不回收其他run对象。
- GC、runner crash/restart、lease timeout和重复finish并发时无use-after-free、authority复活或两个权威attestation。

### Integration and live tests

- 构造可区分输出的SIF A/B，在高频global replacement下运行真实Apptainer；container fingerprint、snapshot digest与attestation一致。
- 用launcher/system-call审计证明Apptainer消费protected snapshot而非deployment source pathname；底层路径只留private evidence。
- runner restart后恢复sealed snapshot与active lease，但拒绝unsealed staging object。
- SSH positive、digest mismatch、snapshot unavailable、lease stale和launcher failure分别产生稳定error code且不产生partial identity。
- Slurm只有compute-node内完成相同证明才通过；submit/login-node-only fixture必须拒绝。

## Acceptance criteria

- swap-and-restore压力测试达到约定次数后，无法让执行内容与attested `snapshot_digest`分离；对照@1测试明确展示旧path无法提供该保证。
- workload与同UID并发进程不能修改或替换active snapshot；`chmod 0444`同owner等弱机制被测试拒绝。
- 全局SIF在run启动后替换不改变该run，只影响后续snapshot preparation，并在expected digest不匹配时fail closed。
- snapshot prepare/seal/lease/launch/release/GC状态机经并发与故障注入证明，无stale authority或active object提前回收。
- snapshot attestation精确绑定operation、logical contract、deployment epoch、snapshot、lease/execution binding、mode和outcome；任一篡改离线验证失败。
- public operation/event/workspace/report/bundle不含source/snapshot path、UID、SSH target、mount或secret；agent获得稳定capability/failure事实。
- @1历史bundle仍按原scope验证，@2缺失不降级；Slurm未完成node-side snapshot binding前不满足高保证cutover。
- 与compiler的组合验收证明实际launcher plan引用本snapshot的digest与active fencing token；compiler plan或snapshot任一不匹配均fail closed，且最终attestation只存在一个权威组合identity。
