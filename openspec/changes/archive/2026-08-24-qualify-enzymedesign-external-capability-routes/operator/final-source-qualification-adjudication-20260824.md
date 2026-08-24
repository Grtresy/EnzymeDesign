# 最终源码资格裁定（2026-08-24）

## 裁定基线

- exact source commit：`bb6af997c369dd03d4d637ca27c284d9006447fd`
- source identity：`sha256:3ceccf46d690cb913d245b71368d055e393da9aefe51a53ee403388687d0502c`
- operator：`operator.enzymedesign-owner`
- fallback：禁止
- cutover：本 change 不执行

## Batch 1

Batch 1 的 44 个 unit 已在 exact source 下终态闭合。执行报告与独立 receipt-set verifier 均给出
`qualified=true`、`cutover=false`；44 个 unit 均有当前 receipt、预算结算和所需清理证据，没有缺失 unit，
也没有 fallback。

- dry plan：`sha256:c18ea92b041444601bf16c410a69b7d0521c38460ffb53bce45f02f8adbe18e0`
- authority：`sha256:93d62fe02bcf82dcede84fe062a0ad75ded8d77127efaf5b04ae35a2a64ece06`
- execution report：`qualification-report-authorization.qualification.batch-1.sealed-bb6af99-20260824T090540+0800.json`
- execution report digest：`sha256:6c0f1317cae994f11cd307034a7d90777db790892fccd3f4e9234196ed8fcf92`
- receipt set：`qualification-receipt-set-authorization.qualification.batch-1.sealed-bb6af99-20260824T090540+0800.json`
- receipt-set report digest：`sha256:9c71d03ec1d9e2c85de89dc72d4f2d72d99569c235d12c2c52d2e4592c133dbe`

较早的 `20260824T091000+0800` occurrence 因 authority 的 `authorized_at` 晚于实际执行时刻而被 verifier 拒绝。
它只作为失败审计证据保留，不参与当前 receipt set，也不得被 cutover 消费。

## AlphaFold Batch 2

AlphaFold 的 exact job `233284` 请求 `Diannan/3090` 的一张 GPU，但持续处于
`PENDING (Resources)`。容量核查显示健康节点的 GPU 均已分配，多台其余节点处于 GPU health、`/opt` mount
等 drain 状态。排队期间实际 GPU 运行时间为 0。operator 指示在 HPC 没有计算资源时跳过该实验，因此 exact job
已取消并观测到 `CANCELLED` 终态；Slurm、SSH 与工作区清理均完成。

- dry plan：`sha256:f7a224c1988cf9d638eba9c08201bb0f6658cab8ac6cf4675e71794055d90d1a`
- authority：`sha256:8de25ac38bff66e10439800af3315507f761367b43bf61f4bb14ae1bc617dbed`
- execution report digest：`sha256:7cdfb4237e7ab026dd157c6bb1204fbd2c6d4509d047de4a25013d9843a4b63f`
- receipt-set report digest：`sha256:419f100920f94a74666c496efa5ab30367ceb51f4f037f888ec95bfba9b9290b`
- result：1 个 terminal failed outcome、0 receipt、`qualified=false`、`cutover=false`

因此 AlphaFold 的最终状态是 `deferred_optional_profile_capacity_unavailable`，不是 qualified。当前 runtime
不得发布、采用或切换 AlphaFold profile，也不得自动改用本地 route、其他分区或另一个 target。未来启用必须重新建立
source-bound plan、一次性 authority、真实 qualification receipt 和独立 adoption/cutover 决策。

## Cutover handoff

本次 cutover 的准入范围由 `approved-alphafold-capacity-deferral-20260824.json` 覆盖原 P0–P16 决策包中的
AlphaFold 顺序和 receipt policy：只允许消费未过期、exact-source 的 Batch 1 receipt。其余 P0–P16 决策继续有效。
这不会把 `selected`、`runtime_mounted`、`qualified`、`cutover` 与某一次 `live occurrence` 合并：Batch 1 当前仅为
qualified；AlphaFold 仅为已挂载但未资格通过的可选能力；全部能力当前仍未 cutover。
