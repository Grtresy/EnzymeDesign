## Why

OpenZyme V3 已经具备严格的 artifact、sandbox、approval、provider 与 HPC 边界，但当前 AOX/HMM 评测仍缺少产品化的真实位点评分合同、必需文献证据语义和可重复的 blank-world cutover 证明。旧 S15 历史结果与现行 fail-closed doctrine 不一致，因此必须以当前代码、真实外部数据和可离线复核的证据重新建立 GO 基线。

## What Changes

- **BREAKING**：把 AOX 候选筛选中的 `activity_score` 更正为版本化 `aox_motif_rule_score@1` / `motif_rule_score`，明确它是参考位点规则启发式分数，不代表实验活性预测。
- 从只读 reference notebook/runner 提取坐标映射、位点、残基集合、权重和阈值，建立独立实现、源码摘要、golden tests 与严格科学前置错误。
- 建立真实文献证据 quorum：PubMed/PMID/DOI 为 cutover 必需证据，Semantic Scholar/Tavily 为可降级 enrichment；禁止 provider 失败后生成替代证据。
- 建立一次 exact-14 NCBI fetch 到“13 条 HMM model reference + `AAB57849.1` 坐标 reference”的两条显式选择链，再与 EBI HMMER `refprot` → score-filtered UniProt accession → UniProt sequence → identity-preserving length join → scoring-input/HMMalign → motif/CD-HIT/相似度图闭合为端到端身份与 digest 链。
- 建立机器可验证的 blank-world campaign：clean roots、cache bypass、与正式科学 artifact 严格隔离的 known-positive probe、由封存 artifact 重算的 healthy-empty branch/operation omission、无伪造 provider digest 的 skip receipt、sealed evidence bundle 与 tamper verification。
- **BREAKING**：把 motif candidate、conditional-empty 与 normalized final bundle 从 agent-local source snapshot 提升为版本化 exact calculation/finalization capability；Host 在任何 normalized artifact catalog write 之前原子预验证完整 17-deliverable bundle，并签发绑定 session/task/attempt/selection/sandbox source 的 validation receipt。没有 exact passed receipt 时，attempt closure、execution completion 与 report handoff 均 fail closed。
- **BREAKING**：退役已完成但与 current close contract 永久不相容的 closure-stage live diagnostic/authority/reconstruction/CLI 产品链；保留 migration `035`、历史 SQLite rows、封存 evidence 的只读验证和 formal non-adoption gate。
- **BREAKING**：把 sandbox-local pre-admission failure 纳入 canonical typed causal chain：Host 在 operation admission 前封存 `hpc_stage_ref_required/no_effect`，terminal run 封存 source-bound `sandbox_exec_nonzero` wrapper，failed ToolResult、`ENGINE_COMPLETED` wake 与 AOX formal observer 复用同一证据；删除 AOX one-shot handoff/drain override，由普通 bounded drains、selected-chain closure 与显式业务终态收敛。
- **BREAKING**：在 r56 暴露首个 eligible result 前的 framework defect 后，将单 positive、永久 non-cutover 的 diagnostic live run 与 exact-three formal acceptance campaign 拆成 schema/authority/root/evidence 互斥的两类；diagnostic 不生成 `@3` bundle、不进入 reducer，也不降低或替代正式 GO 门槛。
- 以同一 commit/config 下两次独立正向 live E2E 和一次故障注入作为 local Live cutover GO 门槛，并同步修正旧 S15 历史结论、UI/approval 验收与稳定架构文档。

## Capabilities

### New Capabilities

- `aox-motif-scoring`: 版本化 AOX motif rule scoring、坐标映射、golden reference 与科学 fail-closed 合同。
- `scientific-evidence-quorum`: 必需文献/provider 证据、可降级 enrichment、数据身份与 provenance 语义。
- `blank-world-live-cutover`: clean-root live campaign、known-positive/empty-result、sealed evidence、离线复核和 GO 判定。

### Modified Capabilities

无。现有 OpenSpec 主规格只覆盖 MCP knowledge 与 HPC runner；本变更新增 V3 科学产品能力规格，不修改其既有 requirement。

## Impact

- 影响 `packages/openzyme-{research,runtime,core,engines,pipeline,tools,execution}` 的科学合同、provider adapter、执行与 artifact evidence。
- 影响 `apps/openzyme-host-api` 的 foundation、eval/live gate、统一 AOX final validator/finalizer、selected-formal failure observation、证据聚合、API projection，以及 Web UI 的 approval/report/evidence 呈现；删除 closure-stage runnable CLI surface 与 one-shot AOX recovery path。
- 影响 AOX/HMM workflow pack、S15 文档、主架构文档、live pytest markers 与 campaign 命令。
- 真实运行继续依赖现有 MICU 500M 持久账本（历史 usage 不重置）、NCBI identity、UniProt/EBI/PubMed 网络能力、可信 Host-only HPC runner 和 immutable sandbox/toolchain identity。
