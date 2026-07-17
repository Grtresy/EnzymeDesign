# Deferred: generic scientific campaign attestation

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Problem evidence

AOX/HMM cutover 需要把 clean-root proof、provider/toolchain receipts、approval continuity、task business exits、artifact closure、report publication、MICU ledger 和多 attempt GO/NO-GO 聚合为一个离线可验证合同。当前实现把这一合同放在 Host API 的 AOX 专用模块中，并由 AOX collector 显式构造。这能在当前 Goal 内严格 fail closed，但如果后续每个科学 workflow 都复制一套 campaign schema、record digest、append-only sealing 和 state machine，将产生多个相互漂移的“准 control plane”。

这一问题不能通过把更多字段塞进 AOX 模块解决。通用化会改变 Host、artifact、operation、report、live-eval 和 operator tooling 的 ownership，属于顶层 harness 调整，因此本 Goal 只记录方案。

## Agent impact

- agent 应自由选择科学策略、provider 顺序和局部工具，但不应自己发明“什么算已封存、独立、可 cutover”的证明语义。
- researcher、executor、reporter 产生的 durable records 应自然成为 attestation 输入，不应要求 agent 在最终回答中复制隐藏 ID 或拼装 digest。
- failure、empty result 和 degraded enrichment 都应保留真实业务语义；attestation 只能验证事实，不能替 agent 把 task 自动完成或改写科学结论。
- operator 应从一个稳定命令得到最小 blocker，而不是理解每个 workflow 的私有 bundle 实现。

## Target invariants

1. session、task、lane、approval、controlled operation、artifact、source ref 与 report 继续是唯一产品真状态；attestation service 只读取已提交事实。
2. attestation 不创建或完成业务 task，不批准 operation，不选择 fallback，不修改 agent query，不合成 artifact。
3. workflow-specific science validator 以 versioned plugin 输入；generic layer 只验证共同的 identity、closure、independence、ledger、sealing 和 campaign state machine。
4. attempt 必须绑定一次 Host launch receipt 和一组不可变 control-plane snapshots；不能由调用方只提交布尔值证明 canonical path。
5. GO 是 deterministic reducer 的输出；任何缺失、schema drift、重算失败或 driver failure 都只能得到带稳定 blocker 的 NO-GO。
6. attempt、failure evidence 和 decision 均 append-only；重跑必须使用新 campaign/attempt identity，不能覆盖失败历史。

## Proposed ownership and model

引入 Host-owned `ScientificAttestationService`，但不引入第二套 scheduler：

```text
AttestationManifest
  campaign_id / workflow_selection_ref / validator_ref
  required attempt sequence and independence keys
  required provider/toolchain/task/report classes
  ledger policy / projection policy / fault policy

AttemptLaunchReceipt
  attempt_id / root_identity / runtime_config_digest
  session_id / entry_message_id / cache policy
  sqlite/blob/artifact/sandbox/HPC bindings

AttemptAttestation
  immutable snapshot refs
  provider/toolchain/approval/operation/task refs
  artifact closure / report ref / final response ref
  validator result / ledger before-after / outcome

CampaignDecision
  ordered attempt digests / deterministic blocker / GO|NO-GO
```

Host repository 读取 canonical records 并生成 snapshot refs；workflow validator 只接收授权 artifact bytes 和 manifest 参数，返回结构化重算结果。generic reducer 校验 attempt 顺序、同一 manifest identity、root/session/task/operation/provider invocation/HPC job 独立性以及连续 ledger snapshots。AOX 的 motif、similarity、identity-chain validator 作为第一个 plugin，而不是被提升为通用字段。

## Alternatives considered

- 继续每个 workflow 自建 JSON bundle：实现局部快，但会形成多套不可比较的 sealing 和 GO 语义，不作为长期方案。
- 让 agent 在最终回答中输出 attestation：缺少 durable snapshot、容易遗漏或伪自声明，不采用。
- 把 attestation 合并进 scheduler drain：会把 runtime progression 与 cutover governance 混为一体，并隐式改变 task 状态，不采用。
- 只用 pytest 作为 campaign owner：测试进程不是产品真状态 owner，也不能提供 operator-visible append-only history，不采用。

## Migration plan

1. 冻结当前 `aox_blank_world_attempt_bundle@1` 和 decision schema，作为行为基线而非永久公共标准。
2. 提取 generic canonical JSON、append-only write、record binding、ledger continuity 和 reducer tests；先 shadow 生成，不改变 AOX decision。
3. 增加 Host launch receipt repository，由 Host 初始化 clean roots 时写入，AOX collector 改为引用 receipt 而非重复布尔字段。
4. 定义 validator plugin SPI，将 AOX scorer/similarity/identity-chain 离线重算移入首个 plugin；对 shadow 与 AOX 专用 verifier 做逐 issue 比对。
5. generic service 达到等价且经历故障测试后，发布 major-version manifest，迁移 operator CLI；旧 AOX reader 保留只读验证。
6. 确认无外部调用方后退役 AOX 专用 campaign writer，但永久保留历史 bundle reader 和 digest verification。

## Compatibility and rollback

- 迁移不改写已封存 AOX bundle、artifact 或 decision。
- generic service 的 shadow 输出不得参与 GO；只有 manifest 明确选择的一个 reducer 能产生权威 decision。
- 回滚只切回 AOX writer，不删除新的 launch receipt 或 snapshot；它们仍是合法审计记录。
- schema 升级必须 major-version，禁止在同一 schema id 下改变 canonical bytes、blocker 优先级或独立性字段。

## Risks

- service 变成“万能科学引擎”：必须限制在证明 mechanics，科学选择留给 workflow validator 和 agent。
- snapshot 与 live record 之间发生 TOCTOU：snapshot 必须在同一读事务或 content-addressed immutable export 中建立。
- plugin 私自联网：offline verifier runtime 使用无网络 capability，并记录 validator implementation digest。
- reducer blocker 顺序漂移：blocker precedence 是版本化合同并由 golden tests 固定。
- 通用 schema 过度拟合 AOX：至少用一个非序列 workflow shadow 验证后才宣布通用。

## Acceptance criteria

- AOX 专用与 generic shadow 对相同 success、empty、degraded、tampered、driver-failure fixtures 产生等价 pass/fail 和 blocker identity。
- Host launch receipt 可从 repository 证明所有 clean roots、runtime config、session/message 和 cache policy 的绑定。
- 两个内容相同但 invocation/job/task/session 相同的 positive attempt 被判不独立；内容相同但 receipts 独立时允许通过。
- verifier 在无网络环境重算全部 artifact closure 和 workflow plugin，malformed input 永不崩溃或泄露 Host path。
- append-only 并发测试证明 attempt/failure/decision 不被覆盖，crash recovery 不产生两个权威 decision。
- agent-facing tools 不增加 attestation 拼装负担，且 service 不改变 task、approval 或科学策略。
