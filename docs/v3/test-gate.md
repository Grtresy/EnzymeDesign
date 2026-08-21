# V3 Repository Test Gate

状态：optimized `mainline_authoritative` runner 已完成 shadow、forced-serial、
fixed-worker、reverse/shuffled、同源 legacy parity、最终五对 cold/warm 性能门和
二十 case replay；用户已于 2026-07-29 明确同意该 immutable corpus 作为二十个 clean
revisions 的等价 cutover 证据。`scripts/check-mainline.sh` 现已原子切换为唯一当前
non-live merge authority；顺序实现冻结为明确非权威的 rollback comparison。

## Authority table

| Surface | Purpose | Merge authority | Admission / AOX / live authority |
| --- | --- | --- | --- |
| `focused_diagnostic` | 显式路径、contract group 或 exact node 快速反馈 | no | no |
| `affected_scope_diagnostic` | 版本化 dependency map 下的 local change 扩张 | no | no |
| `replay-corpus` | 二十个 immutable green/fail-closed contract transformations | no | no |
| shadow/candidate receipt | 完整非 live merge contract 的诊断、测量与 fault proof | no | no |
| optimized `scripts/check-mainline.sh` | 当前完整 non-live merge gate；默认 fixed four | yes | no |
| architecture qualification `diagnostic` / `premerge_subset` | GAP/P0 定位与 mainline stricter owner subset | no | no |
| architecture qualification `admission` | clean full architecture admission | no merge authority | architecture admission only; still no AOX/live launch by itself |

Test-gate artifact 只属于 repository/operator plane，不得写入或被接受为 V3
session、task、lane、approval、artifact、report、scientific attempt 或 campaign truth。

## Commands

所有 evidence root 必须是 checkout 外、尚不存在的绝对路径。

```bash
# 精确 focused feedback
uv run python scripts/run-test-gate.py focused-diagnostic \
  /tmp/openzyme-focused-example \
  --pytest-path packages/openzyme-kernel/tests/test_protocol_application.py

# 以显式 local base 扩张 staged/unstaged/untracked change
uv run python scripts/run-test-gate.py affected-scope-diagnostic \
  /tmp/openzyme-affected-example \
  --base-ref HEAD

# 二十 case immutable replay；仍是 focused diagnostic receipt
uv run python scripts/run-test-gate.py replay-corpus \
  /tmp/openzyme-replay-example

# 当前唯一权威 wrapper；自动创建并保留 checkout-external evidence，
# 完整运行后立即调用独立 pure verifier
./scripts/check-mainline.sh

# 同一 plan/owner/coverage/frontend/qualification 合同的一 worker 对照
./scripts/check-mainline.sh --forced-serial

# 非权威 complete candidate，仅用于诊断/比较
uv run python scripts/run-test-gate.py run-mainline-candidate \
  /tmp/openzyme-mainline-fixed4 --workers 4
uv run python scripts/run-test-gate.py run-mainline-candidate \
  /tmp/openzyme-mainline-forced-serial --forced-serial

# 非权威 candidate receipt 的纯重验
uv run python scripts/run-test-gate.py verify-mainline-receipt \
  /tmp/openzyme-mainline-fixed4

# 当前 authority receipt 的独立纯重验；路径由 wrapper 输出
uv run python scripts/run-test-gate.py verify-mainline-authoritative \
  /tmp/openzyme-mainline-authoritative.XXXXXX/evidence
```

Focused、affected 与 replay 命令会显式输出
`authoritative=false`、`admission_eligible=false`、`live_eligible=false`。即使它们选择
完整 Python/frontend 工作，也不能升级为 merge authority。未知 affected path 会扩大到
complete-safe non-live + frontend，不会静默省略。

## Exact mainline contract

`scripts/test-gate.toml` 固定七个 stage 的依赖顺序：

1. source Ruff；
2. compatibility-audit Ruff；
3. compatibility semantic audit；
4. `premerge_subset` architecture qualification；
5. exact general non-live pytest；
6. Web UI `npm test`；
7. Web UI `npm run build`。

Planner 先收集完整 `G`、qualification harness `Qh` 与 selected scenario `Qs`。同一
invocation 的 qualification sidecar 是唯一允许 general stage 执行
`G - (Qh ∪ Qs)` 的证据；`Qh ∪ Qs` 保留 stricter qualification owner，其他 scenario
仍属于 general。missing/mismatched sidecar、skip/xfail/unproven invariant、report
verification failure 或 collection drift 都在 general 前 fail closed，不回退成普通 pytest
重跑。

General residual 使用 exact manifest。resource manifest 未分类默认
`serial_unknown`；只有 `parallel_pure` 与 `parallel_temp_root` 可进入固定
`pytest-xdist --dist=loadfile` 分区。worker count 是显式 `1..4`，从不使用 `auto`。
最新切换后 shadow collection 为 `G=2,817`、`Qh∪Qs=97`、residual `2,720`：
当前已审计 1,292 个 parallel nodes，1,428 个 conservative serial nodes；bounded
service、signal、shared SQLite、sandbox/HPC 与未知资源保持串行。

## Receipts and rollback

每次 plan/receipt 绑定 commit、tracked diff、relevant untracked source、config、lock、
Python/Node/uv/npm、environment、collection、owner、resource manifest、stage output、
qualification report/sidecar 和 frontend outcome。source 在 stage 间漂移会使 invocation
失败。stdout/stderr 只保留完整 digest、byte count 与 bounded tail。

`--forced-serial` 使用同一个 plan/owner/coverage/frontend/qualification contract，只把
eligible partition 固定为一 worker；它是当前完整 gate 的并行回归对照，不是缩小后的
gate。顺序实现冻结为 `scripts/check-mainline-legacy.sh`；该命令在开始和结束时都明确
输出 `LEGACY ROLLBACK COMPARISON`，其结果不能与当前
`mainline-authoritative-receipt.json` 混淆。只有 `scripts/check-mainline.sh` 是当前
merge authority；底层 CLI 是该 wrapper 的实现层，frozen legacy 和 shadow/candidate
命令都不是第二权威入口。

```bash
# 仅用于顺序 rollback comparison；当前不会生成 optimized authority receipt
./scripts/check-mainline-legacy.sh
```

最终同源五对 evidence 绑定同一 source/toolchain：legacy cold/warm median 分别为
424.62 / 424.14 s，fixed-four optimized 分别为 255.04 / 253.77 s，缩短
39.94% / 40.17%；planning/receipt overhead median 2.157%、maximum 2.202%。每个
benchmark candidate 都执行当时 source 的 2,808/2,808 distinct nodes，qualification
和两项 frontend 均通过并完成离线纯重验。随后新增的四个 authority/rollback 回归在最新
shadow 中按默认策略进入 conservative serial；未把旧 timing 错当成新 source 的运行证明。
实测稳定下限约 252.41 s，现实中位数约 4 分 14–15 秒。

切换后的 fixed-four 权威 receipt 总计 `256.877 s`，forced-serial 总计
`393.332 s`；两者各自独立纯重验通过，2,817 个 exact node 的
collection/owner/outcome、qualification `84 + 13`、Web UI 和 stage outcome 全部一致。
原始 checkout-external 路径、文件摘要及归一化 projection digest 见
`openspec/changes/optimize-authoritative-mainline-testing/authority-cutover-evidence.md`。

## Immutable replay corpus

`scripts/test-replay-corpus.json` 是 closed
`openzyme_test_replay_corpus@1`，固定二十个代表性 green/fail-closed transformation，
每个 case 绑定 exact proof node、boundary、change shape 与 expected projection；摘要为
`sha256:136cacea60eb8022fbe58672c0c4801545a381cb00343c455c7a2406f898d202`。
case count/order、green closure、proof node、摘要或当前 `G` membership 漂移都会失败。

用户已明确同意该 corpus 作为二十个 clean revisions 的 immutable equivalent，因此
cutover replay 前置条件已经满足；该同意不改变 corpus receipt 永久非权威的身份。
最新当前 source 重放证据位于 `/tmp/openzyme-final-replay-v5-precutover-r1`：
20/20 proof nodes 通过且纯重验通过；
legacy/optimized 同源原始结果中的相同二十节点也全部存在、结果一致。
完整映射见
`openspec/changes/optimize-authoritative-mainline-testing/replay-corpus-evidence.md`。
