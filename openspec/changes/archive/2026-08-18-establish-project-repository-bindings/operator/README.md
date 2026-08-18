# C1 项目仓库绑定 operator contract

本目录闭合 `establish-project-repository-bindings` 的实施基线、部署配置、真实 native-client
验收、恢复演练与最终 acceptance。它建立项目级不可变 Git/LFS repository universe，不创建
agent workspace、不发布 workspace revision、不执行 upstream push/PR/release，也不代替 C2 的
正式 `AgentCapabilityLease` 签发路径。

## Canonical documents

- `implementation-baseline.json`：绑定 C0 publication `9b78ec6a...`、schema 37、实施前 Host/auth
  surface、OpenSpec 摘要和 C1/C2/C3/C4 gate。
- `repository-policy-v1.json`：固定 smart HTTP v2、LFS Batch v2/basic、ref ACL、read visibility、
  scoped bearer 和无 fallback policy；整个 JSON 的 canonical digest 是 binding 的 policy digest。
- `local-development-binding.json`：批准的本地 `ProjectRepositoryBinding` version 1；保存 safe
  service identity、canonical HTTPS endpoint、独立 upstream identity、exact base commit 和 policy
  digest，不保存 Host root 或 secret。
- `durable-root-preflight-receipt.json`：记录实际 writable/fsync、owner/mode、binary/hook/TLS、
  binding inventory 与 exact base preflight。root 只以 path digest 出现。
- `standard-protocol-implementation-receipt.json`：绑定 Host-owned bare repository、独立 TLS
  transport app、Git smart HTTP v2、Git LFS Batch v2/basic、pre-receive ACL 及实现文件摘要。
- `local-protocol-acceptance-receipt.json`：记录 native Git/Git-LFS clone、private ref push、LFS
  upload/download、动态 HTTPS health、service restart、lease hold 释放后的写拒绝、credential revoke
  与 zero upstream effect。该次 credential 仅使用 `c1_acceptance_only` typed lease assertion；它明确
  不证明 C2 的生产 lease issuance。
- `local-restore-rehearsal-receipt.json`：记录 provider reconstruction 和逻辑 backup/restore 前后
  binding、refs、LFS objects、session pin、ACL identity 相同。
- `acceptance-receipt.json`：只有 focused/native tests、文档、forbidden-pattern audit、strict
  OpenSpec、mainline、scope audit 和完整 implementation snapshot 全部通过后才发布。

所有带自身 digest 的 JSON 都使用同一 canonical preimage：移除 digest 字段，以 UTF-8、key 排序、
`(',', ':')` 紧凑分隔和 `ensure_ascii=false` 序列化，再计算 SHA-256。数组顺序属于合同。缺字段、
额外字段、摘要漂移、C0 失配、未完成 task 或产品边界越界直接失败。

## 批准的本地部署

本次 local-development acceptance 使用：

- control plane：`/home/grtresy/.local/state/openzyme/control-plane.sqlite3`
- bare Git root：`/home/grtresy/.local/share/openzyme/repository-service/git`
- LFS root：`/home/grtresy/.local/share/openzyme/repository-service/lfs`
- backup root：`/home/grtresy/.local/state/openzyme/backups`
- repository HTTPS origin：`https://localhost:8443`
- repository id / project id：`openzyme`
- exact base：`9b78ec6a883f90ec4239d113e9300098120f68bd`

Git、LFS、backup 三个 root 是不同目录但位于同一 device `65024`。因此当前演练只证明本地逻辑
恢复和进程重启持久性，`failure_domain_separated=false` 且
`production_disaster_recovery_proven=false`；不得将它表述为生产级灾备证明。

## Verification

验证 receipts、C0 prerequisite 和 closed product boundaries：

```bash
uv run python \
  openspec/changes/establish-project-repository-bindings/operator/verify_repository_binding.py
```

最终验收同时要求 acceptance、40/40 task 和 exact working/published implementation snapshot：

```bash
uv run python \
  openspec/changes/establish-project-repository-bindings/operator/verify_repository_binding.py \
  --require-acceptance --verify-current-sources
```

校验器只读，不捕获或改写失败。缺 receipt、摘要漂移、未完成任务、scope 越界、production lease/DR
过度声明或 fallback 直接非零退出。实际部署初始化、preflight、read-only audit、TLS serve、binding
activation/mapping/retirement 与 restore rehearsal 命令见
`docs/v3/repository-service-operations.md`。

C1 acceptance 单独通过后，C3 仍不可开始；只有
`establish-agent-capability-leases` 的 C2 acceptance 也通过，才满足 C3 的双前置条件。
