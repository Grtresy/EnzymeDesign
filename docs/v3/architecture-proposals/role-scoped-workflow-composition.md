# Deferred: role-scoped workflow composition

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Problem evidence

当前 workflow manifest 只有一组全局 `capability_requirements`、`tool_requirements` 和 `knowledge_refs`。例如 AOX/HMM pack 要求 `role:executor` 与 execution tools；如果 master 的 active workflow 被原样传播给 researcher 或 reporter，teammate 会在首次 provider call 前因 role requirement 不满足而失败。当前 Goal 已用一个局部 correctional change 修复隐式传播：`task.delegate.workflow_refs` 必须显式选择授权子集，省略/空数组表示不绑定。

这解决了错误约束，却没有表达“同一个科学 workflow 对 researcher、executor、reporter 各有不同知识和验收责任”。master 目前只能分别选择多个独立 pack、在 task instructions 中传递角色上下文，或让非 executor teammate 无 pack 工作。长期看，这增加 prompt 重复、遗漏 quorum/report contract 的概率，也迫使 agent 在 pack 粒度与角色粒度之间做人工适配。

## Agent impact

- researcher 需要知道 PubMed required、Semantic Scholar/Tavily enrichment 和 citation provenance，但不应获得 executor-only sandbox recipe。
- executor 需要 scoring/tool/artifact constraints，但不应被 reporter 的 publication checklist 限制工具面。
- reporter 需要 claim-source、empty-result 和 cutover disclosure contract，但不应继承 execution engine requirement。
- master 应自由决定任务拓扑、并行方式和何时委派；harness 只应验证所选 binding 是否真实可用，不能从 workflow 自动生成固定 graph。

## Target invariants

1. 顶层产品真状态仍是 session/task/lane/approval/protocol/artifact/report；workflow composition 不成为第二套 scheduler。
2. 选择必须来自用户或 agent 的显式完整 digest ref，不能由领域关键词自动激活。
3. 每个 role binding 有独立 knowledge/capability/tool digest，delegation 只携带选中的 binding snapshot。
4. manifest 不规定 teammate 数量、task DAG、执行顺序或替代策略。
5. missing、unknown、digest drift、role/tool/engine mismatch 在 claim 前 fail-closed，无副作用。
6. agent 可以选择不绑定、绑定一个 compatible role view，或在明确兼容时组合多个 view。

## Proposed model

未来可为 workflow manifest 增加显式、版本化 `role_bindings`：

```json
{
  "workflow_id": "aox-hmm-live",
  "version": "2.0.0",
  "role_bindings": {
    "researcher": {
      "knowledge_refs": ["...literature-quorum..."],
      "capability_requirements": ["role:researcher"],
      "tool_requirements": ["pubmed.search"]
    },
    "executor": {
      "knowledge_refs": ["...aox-execution...", "...scoring-contract..."],
      "capability_requirements": ["role:executor", "engine:execution"],
      "tool_requirements": ["sandbox.exec", "artifacts.register"]
    },
    "reporter": {
      "knowledge_refs": ["...report-acceptance..."],
      "capability_requirements": ["role:reporter"],
      "tool_requirements": ["report.publish"]
    }
  }
}
```

选择 ref 必须包含 workflow manifest digest 和 binding key/digest，例如 `workflow:aox-hmm-live@2.0.0#sha256:<manifest>/binding:researcher#sha256:<binding>`。`task.delegate` 仍由 agent 显式传 ref；runtime 只解析、验证和持久化。

## Alternatives considered

- 一个 pack 同时要求所有角色：会让任何单 teammate 都不兼容，且暗示固定拓扑，不采用。
- 按角色维护完全独立 workflow ids：当前即可实现，迁移简单，但共享科学合同容易漂移；可作为过渡方案。
- harness 根据 task kind 自动挑 role binding：降低显式性并可能改写 agent 意图，不采用。
- workflow manifest 直接声明 task graph：把领域 recipe 提升为顶层编排器，违反 agent 策略自由，不采用。

## Migration plan

1. 先保持当前显式 subset 合同稳定，并用独立 researcher/executor/reporter packs 验证真实需求。
2. 为 manifest schema 添加可选 `role_bindings`，旧 v1 pack 保持可读但不自动转换。
3. 扩展 registry selection ref、digest 计算、tool schema、payload snapshot 和 restore validation。
4. UI/inspection 只显示实际绑定的 role view，不暴露 repo path 或完整私有知识内容。
5. AOX pack 发布新的 major version；旧 executor-only pack 明确 deprecated/non-cutover 后退役。

Rollback 保留新 manifest 只读解析，但停止发出 binding refs；不恢复隐式 parent inheritance。

## Risks

- schema 复杂度可能超过实际需要：先以三份独立 pack 收集重复证据，再决定是否实施。
- 多 binding 组合可能产生冲突：要求规范排序、独立 digest、显式 conflict error，不能 last-write-wins。
- agent 可能选错 role view：在 claim 前以真实 tool/capability surface 校验并返回可读可恢复错误。

## Acceptance criteria

- 同一 workflow 的 researcher/executor/reporter binding 可独立选择、持久化、恢复与 drift 验证。
- 任一 binding 不会隐式传播到未选择的 teammate。
- master 可自由创建不同 task topology；manifest 不自动创建、claim 或 finish task。
- incompatible/unauthorized/drifted binding 在 teammate creation 和 task claim 前失败且无 canonical side effects。
- compaction/restart 后 exact binding identity 和 safe manifest snapshot 可从 control plane 恢复。
