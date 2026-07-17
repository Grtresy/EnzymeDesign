# Deferred: dual-tier scientific evidence boundary

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Problem evidence

科学复核同时需要两类数据：一类是可进入 workspace、event、report 和 campaign manifest 的安全 public attestation；另一类是可能包含 licensed full text、provider 原始响应、内部 locator、Host staging 信息或大体积序列的受限 artifact bytes。当前各能力面主要依赖字段级 safe projection，而 cutover verifier 又需要读取完整 artifact closure。若把两类内容放进同一 envelope，会在“证据不够完整”和“公共投影泄露私有内容”之间反复取舍。

AOX 当前数据基本公开，可在专用 verifier 中采用严格文本扫描；把这一做法直接推广到所有 scientific workflow 会迫使 agent 丢弃合法的受限证据，或让公共 bundle 承载不应投影的原始数据。建立双层证据边界需要 artifact policy、authorization、report projection 和 export tooling 的共同迁移，本 Goal 不实施。

## Agent impact

- agent 应能引用受限 source 的存在、digest、license class 和可验证结论，而不必把原文复制进 prompt、tool result 或 report。
- reporter 应收到可安全引用的 source ref 与 claim link；只有获授权的 validator 才能读取 restricted bytes。
- executor 不应因为 Host path 或 provider locator 不能公开而失去 artifact lineage；private locator 由 catalog 保管，public ref 使用 opaque identity。
- access denied 必须是明确 evidence gap，不能静默降级为无来源结论或 synthetic summary。

## Target invariants

1. artifact catalog 是 bytes 与访问策略的唯一 owner；public attestation 只持有 opaque artifact id、content digest、provenance digest、license/projection class 和允许公开的摘要。
2. restricted bytes、credential、private URL、Host/runner path 永不进入 tool errors、events、workspace、report body 或 exported campaign manifest。
3. offline verifier 通过显式 authorization capsule 读取所需 bytes；capsule 不包含 credential，只包含 scope、expiry/epoch 和 artifact allowlist identity。
4. report claim 能证明“引用了哪个受限证据及验证结果”，但不能反向泄露原文。
5. projection policy 失败即 fail closed；不得为了让 agent 继续而把 restricted bytes 变成 prompt fallback。

## Proposed model

```text
RestrictedArtifactRecord
  artifact_id / content_digest / provenance_digest
  license_class / projection_class / retention policy
  private storage locator (catalog only)

PublicEvidenceRef
  source_ref_id / artifact_id / digests
  provider/release/retrieved_at / safe citation metadata
  allowed claim summary / restriction reason

VerificationAuthorizationCapsule
  verifier_id / artifact allowlist digest
  policy version / campaign scope / expiry or epoch

PublicAttestationExport
  refs, digests, validator outcomes, warnings, degradations
  no private locator or raw restricted content
```

artifact ingress 在写入时确定 license/projection class；source-ref service 只从 allowlist 构造 `PublicEvidenceRef`。offline verifier 运行在受限环境，通过 catalog resolver 和 capsule 读取 bytes，输出仅含稳定 error code、artifact identity 和重算 digest。campaign export 封存 public manifest；restricted artifact 仍由 catalog 的 immutable closure 保管，不复制到 export 目录。

## Alternatives considered

- 所有 artifact 都公开导出：最易复核但违反许可和私密边界，不采用。
- 所有 artifact 只保留 digest：无法执行真正科学重算，digest 会退化成自声明，不采用。
- 让每个 provider 自定义 redaction：仍需统一 catalog policy 和 verifier authorization，可作为 plugin 但不能替代边界。
- 把原文交给 LLM 后只保存 summary：丢失可复核 bytes 且扩大敏感 prompt 面，不采用。

## Migration plan

1. 盘点 artifact metadata 中现有 license、provider、storage URI、source ref 与 projection 字段，定义不改变 bytes 的分类 sidecar。
2. 为 artifact ingress 增加 versioned projection policy result；先 audit-only 标注，不阻断现有非 cutover workflow。
3. 建立 public ref DTO 和 secret/path corpus tests，把 UI/events/report/campaign export 逐面迁移到 DTO。
4. 增加 verifier resolver/capsule，在无网络、无通用文件系统权限的进程中验证 allowlisted artifacts。
5. 对 AOX 和一个含受限全文的 workflow 做 shadow export；证明 public export 安全且 restricted closure 可授权重算。
6. 外部调用方审计完成后，退役 public projection 中的 storage locator、raw provider payload 和临时路径字段。

## Compatibility and rollback

- 旧 artifact records 保持可读；分类 sidecar additive 写入，不移动或重写 bytes。
- 迁移期 legacy projection 只能标为 non-cutover，不能与新 public ref 混合后择优取成功。
- 回滚 public DTO 不撤销已写 license/projection classification，也不把 restricted bytes重新公开。
- capsule/schema 变更采用 major version；历史 verifier 只能读取其认识的版本。

## Risks

- 错误分类导致泄露：默认 restricted，provider-specific policy 只能显式放宽最小字段。
- 错误分类导致 agent 缺证据：workspace 显示 restriction reason 和可请求的授权动作，而不是隐藏 source。
- capsule 被当成通用文件 token：resolver 只接受 artifact id，绑定 campaign/verifier/epoch，并记录每次读取。
- public digest 可能成为敏感内容 oracle：对高度敏感材料允许 salted policy identity，但科学 content digest 仍只留 catalog/private verifier。

## Acceptance criteria

- secret、private URL、Host/runner path、licensed full-text corpus 对 workspace/event/report/public campaign export 零命中。
- authorized offline verifier 能读取并重算 restricted artifact；未授权读取返回稳定 denial 且不暴露 locator。
- report claim 对 public 与 restricted source 都能回链 source ref、artifact identity、provider/release 和 validator outcome。
- agent 可观察 evidence gap、restriction reason 和下一步授权需求，不需要接触 private bytes。
- migration/rollback 不重写 artifact bytes、不改变既有 content digest、不产生双 source truth。
