# EnzymeDesign 真实 subject identity 缺口与解决方案

本文件来自 2026-08-22 的只读、非 secret 发现。它只描述候选方案，不表示操作员已经选择，也不授权读取凭据、
访问 Provider、创建 Git repository/container、连接 SSH/Slurm/HPC 或执行科学程序。机器可读 packet 由以下命令从
同目录安全快照和当前 checkout 重新生成，并绑定当次 source identity：

```bash
OPENZYME_ALLOW_LIVE=0 uv run python \
  scripts/build-external-qualification-dry-plan.py \
  openspec/changes/qualify-enzymedesign-external-capability-routes/operator/safe-identity-snapshot-20260822.json \
  /tmp/enzymedesign-qualification-operator-packet.json \
  --decision-selections \
  openspec/changes/qualify-enzymedesign-external-capability-routes/operator/approved-identity-resolution-selections-20260822.json
```

## Operator selection status

2026-08-22 已确认 D1、D2、D4、D5、D7 采用推荐项，D3 改为只创建本地隔离 Git/LFS repository、暂不向
GitHub 或其他托管平台同步，AlphaFold 保持独立 Batch 2。机器可读 selections 固化这些 candidate 与硬约束；它们
只允许生成 identity-preparation plan，不把任何 partial/missing observation 改写为 `resolved`，也不授权首次 effect。

## 已闭合且仍未 qualified

UniProt、RCSB、InterPro 的公共只读 endpoint identity 已从 Adapter 源码闭合为 `resolved`。这只允许它们进入
dry plan；没有真实 HTTP smoke、negative closure 和 terminal receipt，仍不是 `qualified`。

## D1：LLM Provider subject

当前已知 `https://www.micuapi.ai/v1`、`gpt-5.5`、Chat Completions；缺 account/project locator digest 与 credential
scope digest。

- 推荐：保留当前 endpoint/model，创建或确认一个只用于资格验证的逻辑 credential locator；由 operator 配置
  credential-free account/project locator digest 和最小 scope digest。material 仍只在获批 occurrence 内临时解析。
- 备选：创建同 Provider 的全新 dedicated qualification account，再生成上述 locator/scope identity。
- 停用：保持 required `base` 为 `blocked_identity`；不能删掉 LLM unit 后宣称 Batch 1 完整。

已选择：现有 intended account 的专用 qualification locator。

## D2：Tavily Provider subject

当前只有 query route、topic 与结果上限；缺 official service endpoint identity、account locator digest 和 credential
scope digest。

- 推荐：固定官方 Tavily Search/Extract service identity，并采用 dedicated qualification account/locator。
- 备选：使用现有 Tavily account，但为 qualification 建立独立最小 scope locator 和可追踪 account digest。
- 停用：`research-provider` 保持显式阻塞，不影响其他 profile 的单独事实，但 Batch 1 不能声称五个 profile 全通过。

已选择：新建 dedicated qualification account/locator。

## D3：本地隔离 Git/LFS subject

本机 `git`/`git-lfs` 存在，但还没有 dedicated local repository、local LFS endpoint 与 repository policy。

- 已选择：在受控本地 operator workspace 新建隔离 qualification bare repository 与 local LFS endpoint；使用专用
  branch/namespace，payload 硬上限 10 MiB，覆盖 clone/checkpoint/publish/LFS fetch/response-loss reconcile，结束后
  清理 repository/artifact。禁止 push 或同步到 GitHub/其他托管服务。
- 未来若要资格验证 hosted Git，必须形成新的 real-subject identity、dry plan 和授权，不能扩大本地 receipt。
- 停用：required `base` 保持阻塞。

## D4：Podman 与本地科学软件 closure

已知本机 rootless Podman 4.3.1、Linux/amd64、VFS；现有 pipeline sandbox image 不是 HMMER/Vina/fpocket/
preprocess 的 exact qualification closure，本机也未发现对应二进制/模块。

- 推荐：不修改 Host 全局环境，构建并 digest-pin 三类隔离 image：基础 Workspace/Podman smoke、HMMER、Docking
  （Vina + fpocket + RDKit + Meeko + Open Babel，可在依赖冲突时拆分）。每个 image 记录软件版本、build/config digest
  与固定 smoke input/output schema。
- 备选：采用已有可信 image，但必须先固定 registry identity、manifest digest、SBOM/license 和目标架构。
- 停用：只保留对应 local route 为 `blocked_identity`；不得自动改走 HPC route。

已选择：下一阶段仅在 exact preparation occurrence 获批后构建/pull digest-pinned qualification images。

## D5：HPC/SSH/Slurm target 与科学软件

已知 deployment `aox-live-local`、SSH alias `Diannan`、partition `3090`、ControlMaster transport；缺
`executor_workspace@2` target profile、inventory generation/digest、native proofs、credential provider/authenticator、
Slurm account/QOS policy，以及 HMMER/Vina/fpocket software facts。

- 推荐：把当前 `Diannan/3090` 迁移为完整 `executor_workspace@2` safe profile；在首次 live 授权后依次执行 helper
  identity、版本、受限 CRUD/exec、same-attempt response-loss、最小 submit/observe/cancel/reconcile，并从同一 target
  生成科学软件 inventory/smoke receipts。
- 备选：选择另一个已具备结构化 inventory/proof 的 HPC target；必须形成不同 real-subject digest，不能借用
  `Diannan` 的发现结果。
- 停用：`hpc-primary` 及所有 HPC scientific routes 保持阻塞，不回退到 local。

已选择：采用 `Diannan/3090` 作为第一批真实 target，并在后续 exact preparation/qualification authorization 下分别
补齐 v2 profile/inventory 与真实 proof。

## D6：AlphaFold 第二批

已确认 AlphaFold 作为独立 Batch 2。当前缺 GPU image、model parameters、database closure、GPU capability fact 与
固定 monomer input digest。

- 推荐：Batch 1 完成后单独建立 digest-pinned GPU image/model/database closure；一次 GPU、30 分钟、一个小型
  monomer、一个 seed，只证明实际推理 closure，不声称科学准确性。
- 备选：采用另一个已存在且能给出 exact asset/license identity 的 AlphaFold target。
- 停用：Batch 2 保持 `blocked_identity`，不影响 Batch 1 exact receipts。

## D7：protected ledger 与 private evidence root

代码只提供 protected SQLite ledger interface 和 secret-safe JSON export；部署位置尚未选择。

- 推荐：在现有 OpenZyme operator state root 下创建独立受权限保护的 SQLite ledger 与 private evidence root，二者
  不进入 Git checkout；public artifact 只保留安全 receipt 与 `diagnostic_id`。
- 备选：使用你指定的受控加密 volume/object store，但需要独立 storage/policy digest 和 retention/backup 规则。
- 临时：继续只输出 `/tmp` plan-only packet；该位置不能用于 real receipt 或 cutover evidence。

已选择：采用现有 operator state root；exact private path 不进入公共 artifact。

## 预算与首次 effect 门

- LLM：USD 5 告警、USD 25 occurrence 硬上限，最多 3 requests，`max_retries=0`。
- Tavily：USD 2 告警、USD 10 occurrence 硬上限，一个 bounded query、最多 3 results。
- Batch 1：USD 20 告警、USD 100 硬上限。
- AlphaFold Batch 2：USD 25 告警、USD 100 硬上限；另有 30 GPU-minute 硬上限。

告警不阻断、不缩小 probe；硬额度不足才在 dispatch 前 `blocked_budget`。无论预算是否充足，当前仍不允许首次
effect。当前 candidate 已闭合，但 subject identity 尚未闭合。系统先生成 exact identity-preparation plan；只有它
获得绑定 batch/window 的独立 occurrence authorization，preparation credential resolver 或 effect 才可能被调用。
Preparation 完成并重新发现 identity 后还要重建 qualification dry plan，并另行授权真实 qualification probe。
