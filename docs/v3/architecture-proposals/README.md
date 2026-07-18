# Deferred V3 architecture proposals

本目录记录实施中发现、会影响 agent 发挥但超出局部修复边界的架构调整。每份文档对应一个独立计划；它们不是当前产品合同，也不表示代码已实现。

进入本目录的调整通常涉及顶层真状态、跨包 ownership、scheduler/approval/protocol 语义或 workflow schema 的整体迁移。当前 Goal 只允许记录问题、目标、不变量、方案、迁移、风险与验收，不实施这些大调整。

当前提案：

- `role-scoped-workflow-composition.md`：把一个显式 workflow 选择拆成可验证的 role-scoped knowledge bindings，同时避免固定 agent 拓扑。
- `unified-provider-evidence-broker.md`：统一 direct/deep-research/execution provider mechanics 与证据 envelope，同时保留各调用面的 canonical owner 和 agent 策略自由。
- `generic-scientific-campaign-attestation.md`：把跨 workflow 的 clean-root、snapshot、offline verifier 与 GO/NO-GO reducer 收敛为 Host-owned 证明服务，不形成第二套 control plane。
- `dual-tier-scientific-evidence-boundary.md`：分离受限 artifact bytes 与 public attestation projection，让 agent 保留完整证据能力而不泄露许可内容、私有 locator 或 Host path。
- `artifact-derived-conditional-capability-closure.md`：让 workflow 从封存 artifact 推导实际到达的科学分支与 capability closure，避免静态 required-operation 列表惩罚 agent 的正确早停。
- `verified-artifact-materialization-handoff.md`：把 adapter input integrity 的已验证只读 materialization 变成 provider/compiler/runner 实际消费的唯一输入，并在 staging 前后绑定 approved digest；当前 Goal 只证明 pre-dispatch byte-flip canonical fail-closed，不实施跨层 handoff/ownership 迁移。
- `single-source-hpc-toolchain-contract-registry.md`：未来把 runner manifest、route policy、command template、跨层 DTO 与 verifier 的 toolchain 常量收敛到单一 versioned logical contract；当前 Goal 只落地 same-SSH-shell runner attestation，不实施该跨包迁移。
- `immutable-hpc-sif-execution-snapshot.md`：为每次 HPC operation 建立 runner-protected immutable SIF snapshot、lease 与 execution binding，消除全局 locator 的 hash-to-open TOCTOU；当前 Goal 只保留 pre/post path hash。
- `runner-owned-hpc-command-compiler.md`：让 runner 从 typed tool intent 编译并封存 execution plan，退役对 caller shell text 的 parser/rewriter；当前 Goal 只保留 strict direct Apptainer grammar validation。
