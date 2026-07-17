# Deferred: unified provider operation and evidence broker

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Problem evidence

当前真实 provider 调用存在三条 ownership 不同的路径：research teammate 的 direct tools 在 `openzyme-core` 中建立 `research_tool` invocation；`deep_research` 内部 tools 在 engine invocation 内返回 `ResearchToolResult`；execution sandbox 的 `bio.*` 则通过 controlled operation、approval envelope 与 artifact boundary。三条路径已有共同的 outcome/provenance taxonomy，但 operation 创建、重试记录、safe transcript、artifact sealing 和 event emission 仍由各自 owner 组装。

本 Goal 只做了局部闭环：direct literature tools 在 provider I/O 前持久化 invocation，用 `ProviderCallResult` 终结所有 outcome，并通过 `ArtifactBoundaryService.seal_external_bytes()` 封存安全 citation evidence；PubMed/Semantic Scholar/Tavily adapter 使用共同的 bounded policy。它没有把 `deep_research`、execution supervisor 和所有 bio provider 改造成一个全局 broker。这样做会重划 engine、runtime、approval、artifact 与 operation ownership，属于大架构调整。

## Agent impact

- agent 选择 direct provider tool 或 `deep_research` 时，不应同时承担“哪条路径证据更完整”的隐含判断。
- researcher 应看到一致的 required/enrichment outcome、artifact id 和可恢复错误，不应因调用面不同而收到 exception、临时路径或不同 schema。
- executor 的 approved `bio.*` operation 不能被 research broker 绕过；researcher 的无副作用文献查询也不应被强制伪装成 HPC operation。
- reporter 应能从统一安全 projection 追踪 source ref、provider attempt、sealed evidence 与 claim，而不读取 engine-private payload。

## Target invariants

1. session/task/lane/approval/controlled operation/artifact/report 继续是产品真状态；broker 不是第二套 control plane。
2. 任一外部调用前，调用方必须先取得 canonical invocation 或 controlled-operation identity；所有 outcome 都终结同一 identity。
3. required 与 enrichment policy 由显式 workflow/evidence contract 决定，broker 不根据关键词替 agent 选择 provider 或 fallback。
4. credential、private header、private URL、Host/runner path 和受限全文永不进入 tool error、event、source ref 或 public projection。
5. science 使用的 licensed/safe bytes 必须经 artifact boundary 封存并回链 request/response digest；metadata 不能冒充 sealing。
6. broker 只治理 provider mechanics 和 evidence envelope，不固定 query、provider 顺序、任务拓扑或报告结论。

## Proposed model

引入 Host-owned `ProviderEvidenceBroker` SPI，但保留 caller-owned operation 类型：

```text
ProviderCallSpec
  provider / operation / endpoint_id
  requirement(required|enrichment)
  safe_request_identity / timeout / retry policy
  license policy / projection policy
  owner_ref(invocation_id | controlled_operation_id)

ProviderEvidenceResult
  completed | empty | degraded | failed
  attempts / request_digest / response_digest / retrieved_at
  normalized_items / safe_failure
  sealed_artifact_ids / source_ref_payloads
```

direct research owner 先建立 `EngineInvocation`，execution owner 先建立/批准 `ControlledOperation`，deep-research owner 先建立 engine invocation；broker 只验证 owner 已存在并将 provider result 回写到该 owner。artifact sealing 统一委托现有 boundary，public projection 只读取 allowlisted provider summary。

## Alternatives considered

- 把所有 provider 都改成 execution controlled operation：治理统一，但会把普通文献 enrichment 误建模为 executor/HPC 工作并扩大 approval 面，不采用。
- 保留三套完全独立实现：局部简单，但 direct/deep/execution 证据保证会持续漂移，不作为长期方案。
- 只共享 HTTP client：本 Goal 已采用作为过渡，但不能统一 owner、artifact 和 projection closure。
- broker 自动选择 fallback provider：会改写 agent 科学策略并可能生成替代证据，明确禁止。

## Migration plan

1. 以当前 `ProviderCallResult`、source-ref provenance migration 和 external artifact ingress 作为兼容基线。
2. 为 direct research、deep research 和 execution provider 分别增加 broker adapter；先 shadow-compare envelope，不改变 owner state machine。
3. 把 provider-specific timeout/retry/schema parsing逐项迁到 broker plugin，保留 provider parser 的独立测试。
4. 将 engine-private临时 provider asset 迁到 artifact boundary；旧临时 staging 字段标为 non-cutover 后退役。
5. workspace/events/UI 改为读取统一 safe provider summary；完成外部调用方审计后移除旧 projection fields。

Rollback 只切回原 owner adapter，不删除已封存 artifact、attempt 或 failure evidence，也不恢复 synthetic fallback。

## Compatibility and rollback

- `ProviderCallResult` 和当前 direct-tool `ResearchObservation` 保持读取兼容；broker 以 additive adapter 接入。
- controlled operation digest、approval continuity 和 execution call budget 不得因 broker 引入而变化。
- rollout 期间若同一 owner 同时产生 legacy/broker envelope，只有被 manifest pin 的一种可进入 cutover bundle，禁止择优取成功。
- 回滚后 broker-produced artifacts 仍是合法 immutable catalog records，可由旧 reader 作为普通 artifact/source ref 读取。

## Risks

- broker 可能成为领域巨石：provider parser、quorum policy 与 caller strategy 必须保持插件化和显式输入。
- ownership 不清可能产生双终结：owner transition 使用 compare-and-set/idempotency key，broker 不直接创建第二 owner。
- license policy错误可能封存受限全文：默认 citation metadata allowlist，原始内容必须由 provider-specific license policy显式允许。
- 迁移可能改变 operation digest：先 shadow envelope，再 major-version contract，不能静默更新已批准 operation。

## Acceptance criteria

- direct、deep-research 与 execution provider paths 对同一 fixture 产生相同 outcome/attempt/provenance taxonomy，同时保留各自 canonical owner。
- provider I/O 在 owner record 之前发生的故障注入测试全部 fail closed。
- success、empty、degraded、failed 与 artifact-seal failure 均终结原 owner，且 crash replay 不产生第二 operation。
- required/enrichment quorum、source refs、sealed artifacts、events 与 workspace projection 可从一个 safe envelope 重建。
- secret/private URL/path corpus 在 error、artifact metadata、event、workspace 和 report projection 中零命中。
- broker 不自动创建 task、选择 provider fallback、修改 query、批准 operation 或完成业务 task。
