# Batch 1 最终 source-bound occurrence 裁决（2026-08-23）

## Exact binding

- source commit：`f7ab05d767fc8d3b98e0ad0cd1b981e0c5c5c1de`
- source identity：`sha256:90051e5a0cf95ad67e22bca41701edda43a7b6947c6f070588ea12d734352c7e`
- post-preparation packet：`sha256:d9c0605bac5e049f58ab35df03bac6766e39e2cd897597389dcaadc5feff72fd`
- Batch 1 dry plan：`sha256:c18ea92b041444601bf16c410a69b7d0521c38460ffb53bce45f02f8adbe18e0`
- scope：44 units，`max_retries=0`，无 fallback，不含 AlphaFold，不执行 adoption 或 cutover

## Full occurrence

- authorization：`sha256:487c6478c2c6b19376764556b4ce94231fcd330bb09607f0c45ad5b07372d5c9`
- execution report：`sha256:87e6f99f4cea5c367dd34c4e19b5bfb873795156833f0f5ffac2b512d5854517`
- receipt-set report：`sha256:fa8681233fe725490f8e7ad5882151e49106d39dcb7b785e5a942c3c8db5128f`
- result：44 outcomes，42 safe receipts，2 failed；`qualified=false`，`cutover=false`
- cleanup：Git workspace removed/repository preserved，Podman container absent，SSH workspace removed，Slurm cleanup accepted

本轮证明大型科学输入分块 staging 已在真实 route 生效，Vina HPC 实际执行并形成 safe receipt。它同时保留了
Provider、Git/LFS、Podman、SSH、Slurm、本地科学 route、preprocess 与其余已成功 route 的 source-bound receipts。

## Exact-unit follow-up 与最终 blocker

### HMMER HPC

- unit：`sha256:471456a15dd81316b428f82c3155848d0d3f800928ae6bf40d313c797424dd51`
- authorization：`sha256:b9aca8c6778c367e171253c3cbb721714306d69483822651cfcd8fe74ec317b1`
- report：`sha256:74af7b6f741c927d28a5c94689681b17727c3f142862d81c9661bf8ea78dcbde`
- terminal error：`qualification_compute_remote_command_failed`
- bounded cause：SSH return code 255，Diannan port 22222 主动关闭连接
- cleanup：`workspace_removed=true`

### fpocket HPC

- unit：`sha256:b3c68ec8fbe3d4bff968e92db198adeba5a3d53e9d2f58c99cc9826f5cb13af1`
- authorization：`sha256:d74a25bea45da0f449b91be65ac0e5a0f90cb23e173661a1f2f46a2cf9d604ff`
- report：`sha256:171f640efea0a7d2ecb543bbcf3ecb39ea0820a4662e987eb01c5888d63367f4`
- terminal error：`qualification_compute_remote_command_failed`
- bounded cause：SSH connect timeout to Diannan port 22222
- cleanup：`workspace_removed=true`

最终 cross-occurrence receipt-set report 为
`sha256:339b28d25cfbd974e44f9177d880ddce5dec070eebd11157465d28fcaf70e956`，选择 42 张当前
source receipt，缺失项仅为上述两个 unit。旧 source、缺少 occurrence scope 或身份不匹配的 receipt 均被拒绝，
没有用于补足当前集合。

## Adjudication

Batch 1 当前状态为 `42 qualified / 2 blocked_qualification`，不能提升为全批 `qualified`。HMMER 与 fpocket
在同一目标条件下重复出现 SSH 连接关闭或超时，已达到有界 follow-up 的停止条件；不得继续签发 occurrence 来掩盖
目标不稳定，也不得采用本地 route、其他 target 或自动 fallback 替代。

在 Diannan 登录连接稳定性得到独立恢复证据前：

1. 不创建或执行 cutover change；
2. 不将 Batch 1 写成整体 qualified；
3. 不把 prior-source 的 HMMER 成功或任何非当前 receipt 迁移到本 source；
4. AlphaFold Batch 2 继续保持独立、未授权、未执行。

## Implementation defects closed during adjudication

- `61b2c7c2054febca0c9d72fd58721d03986a89b6`：为 scientific HPC workspace 建立 authority-bound owner marker，使外层 cleanup 能安全删除 exact workspace，并对未知 owner fail closed。
- `f7ab05d767fc8d3b98e0ad0cd1b981e0c5c5c1de`：将大型 Vina/fpocket 输入改为有界分块 staging，消除本地 `execve` 单参数 `E2BIG`，并在远端验证 exact size 与 SHA-256。

