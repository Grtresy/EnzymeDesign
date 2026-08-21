# openzyme-hpc-ssh

HPC Plugin 的 SSH/SFTP/rsync Adapter。

本包实现 target-scoped Workspace Runtime Adapter：`WorkspaceObservationPort`、
`WorkspaceFilesystemPort`、`WorkspaceProcessPort` 与 `WorkspaceTransferPort` 分别映射到受控
SSH/SFTP/rsync transport。公开请求只含 opaque workspace binding 与 root-relative path；hostname、remote root、
login alias 和 credential claim 仅存在于私有 locator。普通进程只接受 bounded foreground argv，Adapter 永不
授予 scheduler submit authority。

响应丢失返回 `dispatch_in_doubt`；`reconcile()` 只查询同一 operation/request digest，不重新发送，也不切换
target/provider。owner、local/remote generation、target qualification 或 root identity 漂移均在 transport 前以
`no_effect` 拒绝。exact Adapter manifest 已存在，但尚未被 Distribution 选中，因此当前状态是
`target_implemented_not_cutover`，wheel 安装本身不构成激活。

```bash
.venv/bin/pytest -q packages/openzyme-hpc-ssh/tests
```
