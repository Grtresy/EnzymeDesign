## Why

当前 session 只有 `project_id`，sandbox 也没有可恢复的 canonical Git remote、base revision 或 LFS policy，无法为每个 agent 建立独立 clone。文件化 workspace 必须先有 Host 管理、版本化且不依赖当前 Host checkout 的项目仓库绑定。

## What Changes

- 新增 `ProjectRepositoryBinding`，固定 Host-managed internal Git/LFS remote、上游 `origin`、object format、default base revision、ref namespace 和 policy digest。
- session 创建时固定 binding version；同一 session 恢复不得漂移到另一个 remote、base 或 policy。
- 内部协作 remote 与 GitHub upstream 分离：agent private refs 和 immutable publication refs 只存在于内部 remote，upstream push/PR 属于另一个显式外部 effect。
- Host 负责 repository/LFS 服务身份与 credential issuance；agent-visible projection 不暴露 Host path 或长期 credential。
- 禁止使用当前 EnzymeDesign checkout、ambient cwd 或缺失配置时的本地目录 fallback。

## Capabilities

### New Capabilities
- `project-repository-binding`: 定义项目内部 Git/LFS remote、版本化配置、ref authority 和 session pinning。

### Modified Capabilities

## Impact

影响 `openzyme-domain`、Host repository/configuration、数据库迁移、session 创建/恢复、部署配置与 Git/LFS 服务。它是 agent clone、publication、HPC clone 和历史数据迁移的共同前置。
