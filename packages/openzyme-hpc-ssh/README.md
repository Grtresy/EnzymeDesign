# openzyme-hpc-ssh

HPC Plugin 的 SSH/SFTP/rsync Adapter。

本包实现 target-scoped Workspace Runtime Adapter：`WorkspaceObservationPort`、
`WorkspaceFilesystemPort`、`WorkspaceProcessPort` 与 `WorkspaceTransferPort` 分别映射到受控
SSH/SFTP/rsync transport。公开请求只含 opaque workspace binding 与 root-relative path；hostname、remote root、
login alias 和 credential claim 仅存在于私有 locator。普通进程只接受 bounded foreground argv，Adapter 永不
授予 scheduler submit authority。

每次 mutating dispatch 前都必须在注入的 `WorkspaceOperationLedgerPort` 中原子 reserve exact
provider/operation/intent/workspace generation identity；transport 返回的 terminal 或 uncertain receipt 会写回
同一持久 occurrence。响应丢失返回 `dispatch_in_doubt`；Host/Adapter 重启后，重复调用只读取原 receipt，
`reconcile()` 只查询同一 operation/request digest，不重新发送，也不切换 target/provider。owner、local/remote
generation、target qualification 或 root identity 漂移均在 transport 前以 `no_effect` 拒绝。SQLite restart
测试覆盖 terminal receipt recovery 与 uncertain occurrence 在新 Adapter epoch 中的 original-route reconcile。
远端唯一允许调用的 `/usr/local/libexec/openzyme-workspace-runtime` 已建模为
`software.openzyme-workspace-runtime == 1.0.0` resource capability。其 build digest、qualification receipt、target
inventory generation/digest 会进入私有 locator 与 transport envelope；缺失 exact resource fact 时，Kernel
affordance resolver 会把 `hpc.workspace.*` 标为 `blocked_qualification`。Adapter manifest 已被产品组合识别和
identity-mounted，但本 change 没有在真实 target 上安装或探测 helper；wheel 安装、manifest selected、non-live
runtime mount 都不构成 live cutover。

```bash
.venv/bin/pytest -q packages/openzyme-hpc-ssh/tests
```
