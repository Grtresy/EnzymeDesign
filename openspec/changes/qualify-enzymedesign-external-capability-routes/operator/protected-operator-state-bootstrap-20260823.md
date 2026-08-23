# Protected operator state bootstrap（未授权草案）

本文只定义首次 preparation effect 前必须由 operator 私下完成或单独授权的本地状态布局；它不是
`ExternalIdentityPreparationOccurrenceAuthorization`，也不授权读取凭据、建仓、build image 或 SSH。

## 私有布局

operator 选择一个不在源码仓库内的绝对路径，通过 `OPENZYME_QUALIFICATION_STATE_ROOT` 传入。公共 artifact 只记录
`qualification.operator-state.primary` 与 policy digest，不记录该路径。

```text
<private-root>/                         mode 0700, current uid, no symlink
  layout.json                           mode 0600
  credentials.json                      mode 0600
  qualification.sqlite3                 mode 0600, first authorized write creates
  private-evidence/                     mode 0700, first authorized write creates
  git-lfs/                              mode 0700, Batch 1 action creates
  hpc-qualification/config.json         mode 0600, Batch 1 action creates
```

`layout.json` 的 exact 内容为：

```json
{
  "schema_version": "enzymedesign_qualification_operator_layout@1",
  "layout_id": "qualification.operator-state.primary"
}
```

`credentials.json` 使用 `enzymedesign_qualification_credential_bundle@1`，必须包含以下三个 exact locator；值只写在
受保护文件中，不进入 Codex 对话、Git、dry plan 或 public receipt：

- `credential.llm.micuapi.qualification`：`token`、`account_locator_id`、`scope_id`；
- `credential.tavily.qualification`：`token`、`account_locator_id`、`scope_id`；
- `credential.hpc.diannan.qualification`：`ssh_host`、`ssh_user`、`identity_file`、`known_hosts_file`、
  `credential_provider_id`、`authenticator_id`、`login_alias`、`workspace_root`、`sidecar_root`、
  `isolation_command`、`slurm_policy_id`。

HPC identity file 必须是 current uid 的 regular file 且 group/other mode bits 为零；known-hosts file 必须是 direct
regular file。SSH observer 固定 `-F /dev/null`、`BatchMode=yes`、`IdentitiesOnly=yes`、
`StrictHostKeyChecking=yes`，不使用 `SSH_AUTH_SOCK` 或用户 ssh config fallback。

## 首次 effect 门

在 operator 确认以下三项前，不创建上述目录或文件，也不解析 locator：

1. 私有状态根已经由 operator 准备，或明确授权 Codex 只创建 root/layout 骨架；
2. exact Batch 1 preparation plan digest 与 `batch-1`；
3. 明确的 `valid_from` / `valid_until` 与 operator identity。

凭据 bundle 缺失、字段不全、权限不安全或 locator 不匹配时，执行必须停在 effect 前；不得读取 ambient env、使用
相邻账号、SSH agent、当前 Git repository、hosted Git 或现有 runner config 作为 fallback。

## 受控命令边界

root/layout 骨架只能在 operator 单独确认 exact 私有路径后运行：

```text
OPENZYME_ALLOW_LIVE=0 \
OPENZYME_QUALIFICATION_STATE_ROOT=<private-root> \
uv run python scripts/bootstrap-external-qualification-operator-state.py \
  --confirm-layout-id qualification.operator-state.primary
```

该命令不创建 `credentials.json`，不解析 locator，也不创建 ledger、Git repository、image 或 HPC 配置。operator 必须通过
私有通道自行写入 exact `0600` credential bundle，禁止把 token、SSH key 或真实私有路径放入 Git、OpenSpec 工件或对话。

收到 exact plan/batch/window/operator 授权后，先以 `OPENZYME_ALLOW_LIVE=0` 生成 canonical authorization JSON；只有随后
显式设置 `OPENZYME_ALLOW_LIVE=1` 的本地执行命令才可进入 preparation。Batch executor 会重新计算当前 source identity、逐字
比对 packet 内的 Batch 1 plan、验证 authorization window，然后一次性预检三个 locator；任一 locator 缺失或字段不全时，
必须在 Git/image/HPC mutation 前失败。执行器不实现 retry/fallback；已记录 occurrence 只按 exact plan 与 authorization 恢复，
未记录但已有 Git/image/HPC residual state 时停止并要求人工 reconcile。成功输出仍是
`prepared_not_qualified`，只允许下一步 effect-free rediscovery，不构成 qualification authority。
