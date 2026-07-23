# V3 architecture proposal 生命周期索引

本目录只保存尚未完成归档的架构提案。proposal 不是产品真状态；当前合同始终以
`docs/v3/` 稳定文档、当前代码和对应 OpenSpec 为准。目录中的提案可以形成 umbrella
关系，但不同 ownership、迁移风险或验收面不得为了“减少文件数”被强行合并。

## 生命周期与归档规则

状态闭集如下：

- `proposed`：问题与边界已记录，尚无获批实施 change；
- `active`：已有唯一 OpenSpec change 正在实施或验证；
- `deferred`：方向保留，但明确不在当前实施范围；
- `superseded`：结论或方案已被更新事实/提案替代，只保留历史追溯；
- `implemented-archived`：声明范围已经实现和验证，proposal 已移到对应归档 OpenSpec。

归档约定：一个 proposal 的声明范围完成并通过 OpenSpec verify 后，必须与该 change 一起
放入 `openspec/changes/archive/<date>-<change>/architecture-proposals/`。本索引保留指向
归档文件的唯一链接，不在本目录留下内容重复的 tombstone。若原 proposal 仍有不同的残余
工作，先把残余边界拆成新的 proposal/change，再归档已完成范围。OpenSpec spec 的同步与
archive 仍使用标准 OpenSpec 流程；移动 proposal 不改变 stable spec，也不改写历史 live
evidence。

## 当前 active / next

当前由 OpenSpec change
[`establish-v3-executable-architecture-qualification`](/openspec/changes/establish-v3-executable-architecture-qualification/)
执行系统性架构资格收口。它不是新的产品真状态，也不把本目录 deferred proposal 自动晋级为
已实施合同。deterministic baseline 确认的两个 P0 分别由
[`bound-public-diagnostic-sanitizer-work`](/openspec/changes/bound-public-diagnostic-sanitizer-work/)
和
[`fix-v3-durable-supervisor-semantic-progress`](/openspec/changes/fix-v3-durable-supervisor-semantic-progress/)
完成实现。两个 P0 closure、完整 deterministic matrix、clean admission 与独立 pure verification
已经闭合；change 在同步/归档前仍保持 `active`，但其实现与验证任务已经完成。

编号 AOX live campaign 的 r48/r49 已永久 NO-GO。已归档 proposal、focused tests、
premerge subset、dirty diagnostic 或历史资格 GO 均不构成新 attempt admission；只有当前 clean
commit 的 full/zero-P0 architecture admission 可以解除架构阻断，且仍需 operator 另行启动并
通过全部外部、科学与证据门禁。资格验证本身不创建 attempt，也不调用真实
provider/runner/Chrome/MICU。

## 已实现并随 OpenSpec 归档

- [Process-isolated live-attempt supervision](/openspec/changes/archive/2026-07-21-add-process-isolated-live-attempt-supervision/architecture-proposals/process-isolated-live-attempt-supervision.md)：local POSIX spawn/process-group bounded retirement、root gate、exact receipt 与 parent-owned fatal evidence。
- [Sandbox Host authority handoff](/openspec/changes/archive/2026-07-21-simplify-sandbox-host-authority-handoff/architecture-proposals/sandbox-host-authority-handoff.md)：typed Host-call authority、process-lifetime handoff、bounded runtime barrier 与 AOX observation cleanup。

以下五份 proposal 的已声明 scope 由同一 runtime/HPC umbrella change 完成。任意 Python
stack replay、generic 非 controlled RPC、distributed writer 与 process hard-kill 等残余边界
已明确留在独立 proposal，不阻止已完成 scope 归档：

- [Runtime/HPC reliability roadmap](/openspec/changes/archive/2026-07-21-runtime-hpc-reliability-refactor/architecture-proposals/runtime-hpc-reliability-refactor-roadmap.md)
- [Durable HPC transport, staging and dispatch reconciliation](/openspec/changes/archive/2026-07-21-runtime-hpc-reliability-refactor/architecture-proposals/durable-hpc-transport-staging-and-dispatch-reconciliation.md)
- [Non-blocking supervised continuation](/openspec/changes/archive/2026-07-21-runtime-hpc-reliability-refactor/architecture-proposals/nonblocking-supervised-continuation.md)
- [Durable async controlled operation and quiescent sealing](/openspec/changes/archive/2026-07-21-runtime-hpc-reliability-refactor/architecture-proposals/durable-async-controlled-operation-and-quiescent-sealing.md)
- [Controlled-operation outcome unknown after response failure](/openspec/changes/archive/2026-07-21-runtime-hpc-reliability-refactor/architecture-proposals/controlled-operation-outcome-unknown-after-response-failure.md)

## Deferred umbrella 关系

umbrella 只统一 ownership 与实施顺序，不把成员 proposal 的验收范围揉成一个 change。

### Provider execution / evidence

以 [unified-provider-evidence-broker.md](unified-provider-evidence-broker.md) 统一调用 mechanics
与 envelope；retry、batch transcript、streaming persistence 仍是三个可独立验收的成员：

- [provider-retry-policy-and-failed-attempt-evidence.md](provider-retry-policy-and-failed-attempt-evidence.md)
- [transactional-provider-batch-attempt-evidence.md](transactional-provider-batch-attempt-evidence.md)
- [streaming-provider-response-and-artifact-persistence.md](streaming-provider-response-and-artifact-persistence.md)

### HPC input / toolchain / execution plan

同一个 logical execution contract 下保持四个独立 migration seam：

- [verified-artifact-materialization-handoff.md](verified-artifact-materialization-handoff.md)
- [single-source-hpc-toolchain-contract-registry.md](single-source-hpc-toolchain-contract-registry.md)
- [immutable-hpc-sif-execution-snapshot.md](immutable-hpc-sif-execution-snapshot.md)
- [runner-owned-hpc-command-compiler.md](runner-owned-hpc-command-compiler.md)

### Campaign storage / evidence / attestation

按“typed roots → transactional archive commit → generic attestation reducer”排序：

- [attempt-scoped-storage-capability.md](attempt-scoped-storage-capability.md)
- [transactional-attempt-evidence-collection-and-root-closure.md](transactional-attempt-evidence-collection-and-root-closure.md)
- [generic-scientific-campaign-attestation.md](generic-scientific-campaign-attestation.md)

[dual-tier-scientific-evidence-boundary.md](dual-tier-scientific-evidence-boundary.md) 是相邻的
公开/受限证据边界，不并入 archive-commit ownership。

### Workflow request authority / role composition

- [request-lineage-workflow-authority.md](request-lineage-workflow-authority.md)
- [role-scoped-workflow-composition.md](role-scoped-workflow-composition.md)

前者拥有同一 user request 的 durable authority lineage，后者只投影 role-scoped knowledge；
二者共享 change 顺序但不能形成固定 agent 拓扑。

## 其余独立 deferred proposals

- Process supervision hardening: [live-attempt-supervision-hardening.md](live-attempt-supervision-hardening.md)，保留 different-UID/cgroup、escaped-descendant、external-handle 与 MICU crash reconciliation；不得反向扩张当前 local POSIX change。
- Operator interrupt retirement: [operator-interrupt-safe-live-attempt-retirement.md](operator-interrupt-safe-live-attempt-retirement.md)，单独定义当前 local POSIX supervisor 在 SIGINT/SIGTERM 下的 bounded process-group retirement、fatal evidence 与原 signal exit 语义；本轮只记录，不实施。
- Scientific closure/adoption: [artifact-derived-conditional-capability-closure.md](artifact-derived-conditional-capability-closure.md), [canonical-scientific-chain-adoption-and-attempt-closure.md](canonical-scientific-chain-adoption-and-attempt-closure.md), [canonical-research-evidence-adoption-and-invocation-history.md](canonical-research-evidence-adoption-and-invocation-history.md), [versioned-scientific-calculation-capability-projection.md](versioned-scientific-calculation-capability-projection.md).
- Artifact/query boundaries: [artifact-path-addressing-for-arbitrary-dictionary-keys.md](artifact-path-addressing-for-arbitrary-dictionary-keys.md), [bounded-canonical-artifact-metadata-manifest-references.md](bounded-canonical-artifact-metadata-manifest-references.md), [bounded-capability-facts-query.md](bounded-capability-facts-query.md).
- Sandbox/runtime mechanics: [bounded-streaming-sandbox-stdio-capture.md](bounded-streaming-sandbox-stdio-capture.md), [reproducible-sandbox-scientific-dependency-manifest-and-build.md](reproducible-sandbox-scientific-dependency-manifest-and-build.md), [host-authoritative-scientific-calculation-placement-and-sandbox-resource-class.md](host-authoritative-scientific-calculation-placement-and-sandbox-resource-class.md).
- Verification orchestration: [authoritative-tiered-test-execution-and-qualification-deduplication.md](authoritative-tiered-test-execution-and-qualification-deduplication.md)，定义 focused/affected-scope diagnostic、single-execution mainline plan、qualification 去重、resource-audited 并行与 fail-closed receipt；当前门禁不变。
- Control/public evidence: [canonical-approval-command-vs-activity-projection-events.md](canonical-approval-command-vs-activity-projection-events.md), [canonical-public-diagnostic-boundary.md](canonical-public-diagnostic-boundary.md), [verifiable-chrome-devtools-observation-transcript.md](verifiable-chrome-devtools-observation-transcript.md).
- Resource policy: [host-authoritative-controlled-operation-resource-estimate-and-limit-snapshot.md](host-authoritative-controlled-operation-resource-estimate-and-limit-snapshot.md).

这些提案目前均为 `proposed` 或 `deferred`，局部修复、文档定义或 fixture 通过都不得写成
generic implementation complete。
