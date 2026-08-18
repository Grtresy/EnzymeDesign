# C0 AOX artifact cutover supersession operator contract

本目录是 `supersede-aox-hmm-artifact-cutover` 的只读治理边界，不是应用运行时 schema，也不提供任何
live、恢复、重放或迁移能力。

## Canonical documents

- `scope-gate.json`：`c0_scope_gate@1`，绑定实施基线与允许/禁止改动范围。
- `frozen-inventory.json`：`aox_artifact_cutover_frozen_inventory@1`，绑定旧 change、c001、六项未执行
  live tasks、authority、roots、receipts、bytes 与只读 source projections。
- `supersession-manifest.json`：`aox_artifact_cutover_supersession@1`，发布唯一 `legacy_no_go` 裁决。
- `operator-index.json`：将旧 change 投影为 `superseded`，并为所有旧入口返回同一个 closed
  `legacy_aox_artifact_cutover_superseded / no_effect` decision。
- `negative-checklist.json`：封存 c001 resume、8.3--8.8 execution、旧 authority reuse、旧 bytes adoption
  与旧 spec sync 的零 effect 负向结果。
- `c0-governance-gate-receipt.json`：在 C1/C2 开始前必须通过的 `c0_governance_gate_receipt@1`。
- `acceptance-receipt.json`：只有 focused tests、文档、strict OpenSpec、mainline 与 scope audit 全部通过后
  才发布的最终 `aox_artifact_cutover_supersession_acceptance@1`。

每份文档都是 closed JSON object。其 canonical preimage 是移除自身 digest 字段后的对象，再以 UTF-8、
按 key 排序、`(',', ':')` 紧凑分隔且 `ensure_ascii=false` 序列化；digest 为该 bytes 的 SHA-256，并使用
`sha256:<hex>` 表示。数组顺序属于合同。任何缺字段、额外字段、重复 identity、task omission、source drift
或 digest mismatch 都直接失败，不生成部分成功 receipt。

## Frozen source boundary

c001 绑定 clean source `e47fe4ce24f7e08a7cf202eab970a5ab54ea9cdf`。治理实施基线为
`3c7774345baa4fd0635586faa27e7d7fa2156868`。旧任务集合精确为 8.3、8.4、8.5、8.6、8.7、8.8；
8.3a 是早已退役且未执行的独立历史项，不属于这六项，但仍由完整旧 tasks tree digest 覆盖。

本清单只保存 legacy identity、状态、source path 与 digest，不复制或迁移旧 bytes。c001 的 SQLite
`-shm` / `-wal` 是非权威运行时 sidecar，明确排除在稳定 tree digest 外；权威 `control-plane.sqlite3`、
56 条 public API receipt projection、28 条 artifact record projection、9 个 sealed file 与 10 个 sealed
source tree 则全部进入闭合摘要。后续历史 Git/LFS 迁移必须保持
`historical_import_non_adoptable`，不得由 byte equivalence 创建 current truth。

## Verification

仅验证已提交治理文档，不依赖任何外部服务：

```bash
python3 openspec/changes/supersede-aox-hmm-artifact-cutover/operator/verify_supersession.py
```

在冻结 c001 本地源仍可读时，额外逐项重算 Git trees、task lines、文件树、SQLite projections、receipt
chain 与 sealed byte manifests：

```bash
python3 openspec/changes/supersede-aox-hmm-artifact-cutover/operator/verify_supersession.py \
  --verify-legacy-sources
```

C0 最终验收还必须要求 acceptance receipt：

```bash
python3 openspec/changes/supersede-aox-hmm-artifact-cutover/operator/verify_supersession.py \
  --require-acceptance
```

校验器不捕获或改写失败：缺项、漂移和解析错误直接以非零退出暴露。它不访问 provider、HPC、MICU、
Chrome，也不创建 session、attempt、authority 或 external effect。

manifest 一经随本 change 提交即视为发布，不得原地改写。治理纠正只能通过另一个显式 superseding
decision；旧 change、c001、旧 authority/roots/receipts/bytes 与 8.3--8.8 永久不能恢复、重放、replacement
或满足 successor admission。
