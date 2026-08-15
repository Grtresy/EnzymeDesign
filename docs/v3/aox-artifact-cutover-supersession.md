# AOX/HMM artifact cutover supersession

状态：`aox-hmm-blank-world-cutover` 已由
`supersede-aox-hmm-artifact-cutover` 裁决为 `legacy_no_go`。旧 change 和 c001 只保留历史取证价值；
没有任何 live、恢复、重放、replacement、adoption 或 main-spec sync 权限。

## 冻结事实

旧 campaign 的 source pin 是 `e47fe4ce24f7e08a7cf202eab970a5ab54ea9cdf`。c001 精确绑定：

- campaign `aox_campaign_9b88525edafde6cb643da624`；
- launch `formal-slot-be41f223f1ebea0d8389a3fa`；
- session `sess_aox_formal_ffcec8565dd7abe16b88dbe1c68e12ea`；
- attempt `attempt_8f5b8e0430c5bfb036abea08`，仍为 active/open frozen；
- selection `selection_8430d343987b39ca03687857`，仍为 draft frozen；
- earliest typed cause `failure_c9bfd006a706eedb3878 / hpc_stage_ref_required / no_effect /
  same_phase_safe`；hmmbuild operation 从未 admission 或 dispatch；
- slot 2/3、bundle、attestation tree 与 campaign decision 均未创建；finalizer 因一个 nonterminal mutation
  scope 拒绝，因此没有 canonical GO/NO-GO。

旧 change 中保持 pending 且永久不得执行的六项 live tasks 精确为 8.3、8.4、8.5、8.6、8.7、8.8。
8.3a 是另一个已经明确 retired-without-execution 的历史项，不属于这六项，也不是任何 successor prerequisite。

## 机器裁决与 operator gate

权威治理文档位于
`openspec/changes/supersede-aox-hmm-artifact-cutover/operator/`：

- `aox_artifact_cutover_frozen_inventory@1` 绑定旧 change 的 frozen/current Git trees、c001 identity、
  authority、roots、receipts、SQLite projections、artifact records 与 sealed byte manifests；
- `aox_artifact_cutover_supersession@1` 固定 `decision=legacy_no_go`、`live_authorized=false`、
  `adoptable=false`、`merge_to_main_specs=false`；
- `aox_artifact_cutover_operator_index@1` 对旧 change、c001、旧 authority/roots/receipts/bytes 和
  8.3--8.8 返回同一个 `legacy_aox_artifact_cutover_superseded` closed decision，并要求在 session、attempt、
  provider、HPC、MICU、Chrome 或其他 effect 前拒绝；
- `c0_governance_gate_receipt@1` 与最终
  `aox_artifact_cutover_supersession_acceptance@1` 是后续 C1/C2 的强制前置 receipt。

这些 schema 只属于 repository/operator governance，不进入应用 runtime，不新增 fallback。校验使用 canonical
JSON/SHA-256；字段缺失、额外字段、task omission、receipt omission、digest tamper、legacy authority reuse、
byte adoption 或 main-spec sync 都直接失败。完整 source 校验只读取本地 Git 和 frozen c001 source，不联系
provider、HPC、MICU 或 Chrome。

## 历史 bytes 与后继准入

后续 Git/LFS 历史迁移可以保存 byte-equivalent 内容，但每个 mapping 必须携带 supersession identity 和
`historical_import_non_adoptable`。历史 bytes 不得成为 `PublishedRevision`、fresh input/result、scientific
evidence、attempt outcome、campaign outcome 或文件化架构验收证明。

未来 AOX/HMM cutover 只能由另一个明确命名的 OpenSpec change 发起，并重新冻结 file-workspace 架构下的
source revision、workflow/policy digest、input identities、budget、authorization、attempts、receipts 与 campaign
decision。任何 c001 identity、effect、authority、root、receipt、task 或 byte 都不能满足其中任一 admission
条件。

## 只读校验命令

```bash
python3 openspec/changes/supersede-aox-hmm-artifact-cutover/operator/verify_supersession.py \
  --require-acceptance
```

仅在原 c001 本地源仍存在时，可附加 `--verify-legacy-sources` 重算 source projections。两种模式都为零 live、
零 external effect；失败直接报错，不生成部分成功结果。
