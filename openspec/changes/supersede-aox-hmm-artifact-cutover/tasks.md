## 1. C0 前置治理 gate 与冻结 inventory

- [x] 1.1 在本 change 的 operator manifest 中写入 `c0_scope_gate@1`，绑定当前 Git revision、允许改动范围仅为本 change OpenSpec、相关 docs 与 operator manifest，并明确禁止修改应用代码、现有 `aox-hmm-blank-world-cutover`、c001 或 8.3--8.8。
- [x] 1.2 以只读方式枚举旧 change、c001、8.3--8.8、现有 receipts、authority identities、roots 与 byte manifests，记录每项 source path、schema/id、digest 和当前状态，不执行或改写任何旧 task。
- [x] 1.3 为冻结 inventory 生成 canonical serialization 与 digest，并证明 8.3--8.8 各出现一次、c001 identity 唯一且不存在被遗漏的相关 authority/receipt/byte identity。
- [x] 1.4 记录零 live 前置事实：未访问 provider、HPC、MICU、Chrome 或 active Host，未创建 session/attempt/effect/authorization，也未消费旧 authority。
- [x] 1.5 在开始后续重构 change 前发布可机器读取的 `c0_governance_gate_receipt@1`；receipt 缺失、digest 不闭合或 scope drift 时，C1--C4 均不得开始。

## 2. Immutable supersession operator manifest

- [x] 2.1 在本 change 下定义 `aox_artifact_cutover_supersession@1` operator manifest 的 closed fields、canonical ordering、digest rules 和只读验证约束，不新增应用 runtime schema。
- [x] 2.2 填充 manifest，使其精确绑定旧 change id/revision、c001、完整 frozen inventory、8.3--8.8、`legacy_no_go`、`live_authorized=false`、`adoptable=false` 与 `merge_to_main_specs=false`。
- [x] 2.3 将所有旧 authority、root、receipt 和 byte identities 标记为不可恢复、不可 replay、不可 replacement、不可作为 successor admission 输入，同时保持历史内容逐字不变。
- [x] 2.4 写入 fresh successor admission 合同，要求新的 OpenSpec、source pin、workflow/policy digest、input identity、budget、authorization、attempts、receipts 与 campaign decision。
- [x] 2.5 为 historical Git/LFS migration 写入 `non_adoptable` 传播约束，禁止迁移行为创建 `PublishedRevision`、fresh scientific evidence 或 GO。
- [x] 2.6 使用现有只读 JSON/hash 工具验证 manifest schema、canonical digest、inventory 完整性和字段闭合；任何缺项必须使验证失败，不得生成部分成功 receipt。

## 3. OpenSpec 与 operator admission 封存

- [x] 3.1 在新 supersession change 的 operator index/manifest 中把旧 change 投影为 superseded，并要求所有旧入口在 live preflight、session、attempt 或 external effect 前返回同一个 closed decision。
- [x] 3.2 记录旧 artifact/catalog/`HpcStageRef`/17-item bundle delta 不得 sync 到 main specs 的显式 gate，同时保留旧 OpenSpec 与 evidence 为只读历史。
- [x] 3.3 增加负向 operator checklist，逐项证明 c001 resume、8.3--8.8 execution、旧 authority reuse、旧 byte adoption 和旧 spec sync 均被治理 gate 拒绝且零 effect。
- [x] 3.4 审计本 change 实施 diff，证明没有修改 `openspec/changes/aox-hmm-blank-world-cutover/**`，没有把 8.3--8.8 标成 completed，也没有创建 successor attempt/campaign/GO。

## 4. 文档、验证与 C0 验收 receipt

- [x] 4.1 运行 focused manifest tests，覆盖完整 inventory、缺 receipt、task omission、digest tamper、legacy authority reuse、byte-equivalence adoption 和 main-spec sync 拒绝，保存零 live 输出摘要。
- [x] 4.2 更新 `docs/OpenZyme架构设计.md` 与相关 `docs/v3/` AOX/operator 文档，说明 legacy NO-GO、不可恢复/不可采纳、C0 全计划首 gate 和 future fresh cutover admission；不得修改旧 AOX change。
- [x] 4.3 运行 `DO_NOT_TRACK=1 openspec validate supersede-aox-hmm-artifact-cutover --type change --strict --no-interactive` 并保存通过结果。
- [x] 4.4 运行 `./scripts/check-mainline.sh`，确认仅 OpenSpec/docs/operator-manifest 改动未破坏主线；不得以 live marker 或外部服务补足失败。
- [x] 4.5 审计 `git status`、diff 和允许路径，证明 apps/packages、旧 AOX change、c001、8.3--8.8 及任何 live state 均未被触碰。
- [x] 4.6 生成 immutable `aox_artifact_cutover_supersession_acceptance@1` change receipt，绑定 manifest/inventory digests、focused tests、docs、strict OpenSpec、mainline、scope audit 与 `eligible_successors = [C1, C2]`；任一证据缺失则保持 NO-GO。
