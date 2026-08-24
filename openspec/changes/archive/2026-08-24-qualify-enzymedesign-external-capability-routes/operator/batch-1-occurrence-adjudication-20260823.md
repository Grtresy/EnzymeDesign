# Batch 1 首次真实 occurrence 裁决（2026-08-23）

## 绑定与终态

- source commit：`748050c41c603ef2bb2ef6aae58cea2caeb6a07a`
- dry plan：`sha256:ae24ac9d81e8e71628b9b194773f3efb748098c996fb3ae46b0078ec68cfb776`
- authorization：`sha256:b31e5ccf676c04851b4a3f4039d9ccd208dd7cf1e1b2f2aa2523a175da585d62`
- execution report：`sha256:7684c427fe6bd85d58e0de587f875e0194f4a21d2c1c64760fb1288dfc31e607`
- scope：Batch 1，44 units，`max_retries=0`，无 fallback，不含 AlphaFold，不执行 cutover
- verdict：25 succeeded outcomes，18 failed，1 `reconcile_required`；21 safe receipts；`qualified=false`，`cutover=false`

该 authorization 已被一次性消费并终态，后续不得重跑或用于新 source/dry plan。

## 已证明的真实 route

真实成功 outcome 包括 bounded LLM turn、三个公共 Bio HTTP read smoke、Git clone/checkpoint/LFS fetch/response-loss reconcile、九个 Podman Adapter operation、Slurm cancel/reconcile、local HMMER search 和 RDKit `smiles_to_3d`。其中只有同时满足 cleanup closure 的 21 个 unit 形成 safe receipt；成功 outcome 不能单独提升为 `qualified`。

## 失败归因与修正

1. Git publish 使用固定 `refs/heads/qualification`，与旧 occurrence 发生 non-fast-forward。修正为按 occurrence workspace 生成稳定 ref，并让 LFS fetch 绑定同一 exact tracking ref。
2. HPC locator 使用不可写的 `/data/openzyme/qualification/workspaces`，使 SSH workspace、Slurm submit/observe 和所有 HPC scientific unit 成串失败。配置改为已部署 helper 绑定的 `/home/grtresy/.local/state/openzyme-executor-workspaces`，且 factory 在 effect 前强校验 login principal、workspace root 和 helper absolute path。
3. HMMER build expected output 误取输入 argv；fpocket expected output 误加 `inputs/` 前缀。二者按实际 argv/cwd 修正。
4. 本地 docking image 缺 Meeko 所需 SciPy 与 Open Babel wheel 所需 Xrender runtime。recipe 固定补入 `scipy==1.14.1` 和 `libxrender1`，新 output ref 为 `localhost/openzyme-qualification-docking:20260823-r2`；本地 image subject 另行绑定当前 source recipe digest。旧 image digest 不得冒充新 recipe，后续需要新的 image preparation authority。
5. Tavily 返回 `provider_unavailable` 且 effect certainty 为 `dispatch_in_doubt`；同 attempt reconcile 后仍非终态。该 attempt 不重派发。受保护 diagnostic 现可记录 Adapter 已去敏的 provider status/summary，public outcome 仍不泄露该内容。
6. 旧 report 只保存 cleanup 和 budget digest。新 occurrence evidence 会在 protected SQLite 中持久化 exact cleanup resources 与逐 unit budget settlement payload，并在完整恢复时校验。
7. 旧 discovery 只绑定 HPC software fact/image digest，没有把 observed version 与 selected Plugin requirement 比较。unit schema 现升级为 `external_qualification_unit@2`，显式绑定 `subject_version_spec`；HPC banner 规范化为 per-capability version，缺失/不可解析/不满足 spec 均保持 blocked。

## Operator 已决策：route-specific 双版本

已批准 D-V1：Diannan `/home/grtresy/containers/vina.sif` 固定 `==1.1.2`，采用 legacy `--log` 与
poses/log 结果合同；本地 route 固定 `>=1.2,<2`，采用不含 `--log` 的 modern CLI，并从 poses
`REMARK VINA RESULT:` 形成正式 score artifact。Plugin 顶层范围仅表达支持闭包，route admission、workload、
result 与 qualification subject 分别绑定 exact profile。

该决策不授权远端安装、重建、route 切换或 fallback。仍需要新的 source seal、effect-free rediscovery、必要的本地
image preparation plan、重建 dry plan 和单独 occurrence authorization。
