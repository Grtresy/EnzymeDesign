## Context

活动 change `aox-hmm-blank-world-cutover` 的当前验收合同仍把 artifact catalog、`HpcStageRef` 与 17 件 artifact bundle 作为正式工作物料边界。c001 已冻结为 blocked/noncanonical incident，8.3--8.8 的 live campaign 工作也没有形成可在新架构下继续消费的有效授权。与此同时，本轮 breaking refactor 已选择普通文件、独立 Git clone、显式 publication 与 revision-bound HPC 作为后继真相。

两套合同不能同时保持“当前可继续”的地位。这个 change 只负责给旧 cutover 一个不可歧义的 legacy NO-GO 终点，并保留历史审计价值；它不修改产品代码、不运行旧 task，也不产生任何 provider、HPC、MICU、Chrome 或 scientific effect。

## Goals / Non-Goals

**Goals:**

- 以一份机器可读、不可变、可复核的 supersession decision 封存旧 change、c001、相关 receipts/authority/bytes 与 8.3--8.8。
- 阻止旧 artifact/staging 合同继续获得 live admission，或被合并为 main specs 的当前合同。
- 明确历史材料只能作为 legacy provenance，不能被 adoption 为文件化架构的 fresh evidence。
- 为未来 AOX cutover 固定 fresh OpenSpec、fresh pin、fresh authorization 与新架构 evidence 的准入条件。

**Non-Goals:**

- 不修复、恢复、补跑或重新解释 c001，也不执行 8.3--8.8。
- 不迁移、删除或改写任何 legacy artifact bytes、receipts、数据库记录或 OpenSpec 历史；这些工作属于后续历史迁移和 artifact 删除 changes。
- 不定义文件 workspace、Git publication、Git LFS 或 revision-bound HPC 的实现。
- 不创建 successor scientific attempt、campaign decision 或 GO 结论。

## Decisions

### 1. 用独立的 immutable supersession manifest 记录裁决

该 change 将发布版本化 `aox_artifact_cutover_supersession@1` manifest。它至少绑定旧 change id、冻结 source revision、c001 identity、既有 receipt/authority/byte manifest digests、8.3--8.8 task ids、`decision = legacy_no_go`、`live_authorized = false`、`adoptable = false`、`merge_to_main_specs = false`、裁决者和时间，以及后继准入条件。manifest 自身使用 canonical serialization 与 digest，并由纯只读 verifier 重算闭合。

选择单独 manifest，而不是编辑旧 change 或重写旧 receipts，是为了保持历史证据逐字不变，并让“历史发生了什么”和“现在是否允许继续”成为两个可独立验证的事实。仅在旧任务上打勾被否决，因为它不能表达 bytes/authority 非复用和 main-spec merge 禁止；删除旧证据也被否决，因为会破坏审计链。

### 2. Supersession 是 admission gate，不是新的 scientific outcome

任何以旧 change、c001、旧 authority、旧 root 或 8.3--8.8 为来源的 live 请求，必须在 provider、HPC、MICU、Chrome、session、attempt 或 external effect 之前被裁决为 superseded。manifest 只表达 legacy NO-GO 和不可继续，不伪造 c001 的 terminal scientific state，也不把未执行 tasks 写成已执行。

选择在 admission 边界拒绝，而不是等待 runner 或 provider 失败，是为了保证零 effect。把 supersession 映射成新的 AOX campaign GO/NO-GO reducer 输入被否决，因为它会把治理裁决冒充实验结果。

### 3. 旧 artifact/staging delta 永不进入 main specs

归档或检查旧 change 时，OpenSpec 流程必须把 supersession manifest 视为阻断其 artifact/catalog/staging delta 合并的权威记录。旧 change、archived evidence 与 repository history仍可只读保留，但不得重新成为 current specification、compatibility writer 或迁移后的运行时 fallback。

选择显式禁止 merge，而不是依赖后续实现“碰巧不再引用”旧规格，是为了消除双重真相。把旧 delta 先 merge、再由后继 change 删除的方案被否决，因为中间态会把已裁决淘汰的合同提升为主规格。

### 4. 后继 cutover 必须从新架构重新 admission

文件化架构达到其独立验收门槛后，AOX/HMM 只能通过另一个明确命名的 OpenSpec change 开始。后继 change 必须冻结新的 source revision、workflow/policy digests、输入 identity、预算与 authorization，并生成新架构下的 fresh attempts 和 receipts。历史 c001 bytes 可在 historical namespace 中保留和核对，但不得直接成为 `PublishedRevision`、fresh input、fresh result、scientific evidence 或 GO 依据。

选择 fresh admission，而不是转换旧 artifact ids 到新 Git paths 后延续 campaign，是因为 identity、authority、I/O 边界和失败语义都已经 breaking change。自动 adoption 或“等价字节即等价证据”的替代方案被否决。

## Risks / Trade-offs

- [旧 change 仍留在活动目录，操作者可能误认为可运行] → 机器 manifest、OpenSpec 索引/验收检查与 operator runbook 都必须投影同一个 superseded fact，并在任何 live prerequisite 之前拒绝。
- [历史 bytes 后续迁移到 Git/LFS 时被误认成 current publication] → 历史映射必须携带 `non_adoptable` 与 supersession identity，且不得创建 `PublishedRevision`。
- [manifest 漏列 receipt、authority 或 task] → verifier 必须从冻结旧 change 和 evidence inventory 计算全集并比较 digest；缺项使 supersession 验收失败，而不是静默忽略。
- [不可变裁决降低回滚便利] → 在发布 manifest 前可以修正文稿；发布后不原地改写，任何治理纠正都只能通过另一个显式、可审计的 superseding decision。

## Migration Plan

1. 在零 live 环境中冻结旧 change revision，枚举 c001、相关 receipts/authority/byte manifests 与 8.3--8.8，并生成确定性 inventory digest。
2. 生成 `aox_artifact_cutover_supersession@1`，以纯只读 verifier 证明字段、全集、digest、legacy NO-GO、non-adoption 和 no-main-spec-merge 约束。
3. 让 OpenSpec/operator admission 与索引投影该 decision；验证所有旧入口在任何外部依赖或 effect 前返回明确 superseded 结果。
4. 保留旧目录和 bytes 只读，供后续 `migrate-historical-artifacts-to-git-lfs` 消费；不得在本 change 中移动或删除它们。
5. 回滚仅允许发生在 manifest 正式发布前。发布后保持记录不变；未来只能由新的用户授权 change 提出新的治理裁决，不能恢复旧 live authority。

## Open Questions

无。旧 cutover 的 legacy NO-GO、不可恢复、不可采纳和 fresh successor admission 边界均已裁决。
