# Verification Report: qualify-enzymedesign-external-capability-routes

## Summary

| Dimension | Status |
| --- | --- |
| Completeness | 52/52 tasks；18 requirements；49 scenarios |
| Correctness | 18/18 requirements mapped；focused regression `86 passed` |
| Coherence | proposal、design、delta specs、主规格、实现与 operator adjudication 一致 |

## Completeness

- identity discovery、gap/candidate、preparation、dry plan、budget、one-shot authority、protected ledger、receipt-set verifier、Adapter/Driver bridges、workspace helper deployment 与 manual workflow 均有当前实现和测试。
- Batch 1 的 44-unit exact-source receipt set 已独立验证为 `qualified=true`、`cutover=false`。
- AlphaFold Batch 2 已真实提交 exact job；目标无可调度 GPU 后按 operator 指示取消并清理，记录为明确的 deferred/non-qualified optional profile，未删除、未 fallback、未采用。
- 六个 delta spec 已幂等同步到主规格，其中 `enzymedesign-external-route-qualification` 为新增 capability。

## Correctness

- contracts：`packages/openzyme-contracts/src/openzyme_contracts/external_route_qualification.py`、`external_qualification.py`。
- composition/live coordination：`packages/enzymedesign-distribution/src/enzymedesign_distribution/`。
- protected persistence：`packages/openzyme-store-sqlite/src/openzyme_store_sqlite/`。
- exact owner bridges 与 target helper：各 LLM/Tavily/Bio/Git/LFS/Podman/SSH/Slurm Adapter 及 HMMER/Vina/fpocket/preprocess/AlphaFold Driver packages。
- live/CI boundary：`.github/workflows/external-qualification-live.yml` 仅 `workflow_dispatch`；普通 non-live workflow 固定 `OPENZYME_ALLOW_LIVE=0`。
- 当前 focused command：
  `uv run pytest -q packages/openzyme-contracts/tests/test_external_route_qualification.py packages/openzyme-contracts/tests/test_external_qualification.py packages/enzymedesign-distribution/tests/test_qualification_planning.py packages/enzymedesign-distribution/tests/test_qualification_live_runtime.py packages/enzymedesign-distribution/tests/test_qualification_live_bridges.py packages/enzymedesign-distribution/tests/test_qualification_compute.py packages/enzymedesign-distribution/tests/test_qualification_workspace_runtime.py packages/openzyme-store-sqlite/tests/test_external_qualification_ledger.py packages/openzyme-hpc-ssh/tests/test_workspace_runtime.py packages/openzyme-hpc-ssh/tests/test_workspace_runtime_deployment.py`
  → `86 passed in 3.50s`。
- 本 change 与涉及的六个主规格均通过 strict OpenSpec validation；遥测 flush 的 `EAI_AGAIN edge.openspec.dev` 在结构校验成功后发生，未改变退出成功的校验结果。

## Coherence

- `selected`、`runtime_mounted`、`ready_non_live`、`qualified`、`cutover` 与某次 `live occurrence` 继续分别建模。
- Batch 1 的真实 qualification 没有改写 Session binding、部署 inventory 或 live-by-default 状态。
- AlphaFold 的容量不足没有触发 route/target/profile fallback；后续启用要求新的 source-bound plan、authority、qualification 与 adoption。
- 当前 cutover handoff 只允许消费未过期、exact-source 的 Batch 1 receipt；其余 P0–P16 部署和恢复决定保持有效。

## Issues

- CRITICAL：无。
- WARNING：无。
- SUGGESTION：无。

## Final Assessment

全部核验通过，可以归档。仓库中既有 `mcp-enzyme-design-knowledge` 主规格的全库 strict validation 失败与本 change 无关；本 change 及其六个受影响主规格均已分别 strict-valid。
