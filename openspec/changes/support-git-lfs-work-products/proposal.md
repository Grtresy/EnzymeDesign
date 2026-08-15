## Why

研究数据、HPC 输出和模型文件可能远大于适合普通 Git blob 的尺寸；任意传输又不应自动变成共享真相。标准 Git LFS 可以让正式大文件与同一个 commit/publication 绑定，而无需重新引入 agent-facing CAS 或 artifact catalog。

## What Changes

- 在 Host-managed internal Git remote 上提供标准 Git LFS protocol/backend，并将 repository-specific patterns、blob threshold、quota 和 retention 纳入 binding policy。
- Podman 与 HPC login workspace 使用原生 Git LFS；compute node 不需要 Git 或 LFS。
- publish 前验证 commit 所引用的每个 LFS pointer、OID、size 和实际 bytes 均完整可读；缺失或不一致时直接失败。
- 超过 project threshold 的普通 Git blob 在 publish 时被拒绝，并给出明确修正信息；系统不自动改写 `.gitattributes` 或 commit。
- published revisions 引用的 LFS objects 不得被 GC；private/scratch data 只受 workspace/private-ref retention 管理。
- 任意 rsync/scp/curl 上传下载仍可留在私有 workspace，只有 agent commit 并 publish 后才成为共享文件真相。

## Capabilities

### New Capabilities
- `git-lfs-work-product`: 定义 Git LFS policy、object closure、发布完整性与大文件保留合同。

### Modified Capabilities

## Impact

影响内部 Git/LFS 部署、repository binding、Podman image、HPC login 环境、publication validator、GC/retention 和大文件测试。不会新增通用 ContentStore/CAS 产品接口。
