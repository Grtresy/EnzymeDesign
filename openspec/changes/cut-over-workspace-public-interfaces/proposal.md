## Why

即使内部 writer 已迁移，只要 Host API、tool catalog、SDK、projection 和 Web UI 仍展示 artifact/catalog/stage，agent 就仍被迫理解已删除的万能概念。需要一次明确的 breaking public-surface cutover，使文件、Git revision、publication 和 job 成为唯一当前工作物料语言。

## What Changes

- **BREAKING**：Host workspace projection 改为 files、Git status、private/published revisions、reports、scientific deliverables、external jobs 和 lease facts，不再返回 `artifacts`/`artifact_index`。
- 删除 model-visible `artifact.*`、`artifacts.*`、`scientific.artifact.*`、`hpc.stage_artifact` 及相应 SDK/API schema；原生 filesystem/Git/HPC tools 成为工作面。
- Web UI 从 artifact tree/detail 改为 workspace file tree、commit/publication history、handoff paths、large-file status 和 remote job/workspace view。
- CLI、`world.inspect`、restore context、tool reflection、prompts、events 与 evals 同步使用新术语和 closed refs。
- 同步 `docs/OpenZyme架构设计.md`、相关 `docs/v3/` 稳定文档及 execution-pipeline 文档；不保留“缺新字段则读旧 artifact”的 hidden fallback。
- breaking API/version 和 migration prerequisite 必须明确，错误直接报告 stale client/schema。

## Capabilities

### New Capabilities
- `file-workspace-public-interfaces`: 定义文件/Git/publication/HPC 作为唯一当前 public work-product surface。

### Modified Capabilities

## Impact

影响 Host API、CLI、Web UI、core projections/world inspection/restore、tool catalog/prompts、pipeline SDK、events/evals、文档与所有相应测试。
> `operator/source-only-public-cutover-gate.json` 保留原文件名作为 gate 审计槽，
> 当前内容已升级为 `file_workspace_public_release_gate@2`：C10/C11 精确完成
> receipt、统一 release bundle、静默期与本地 deployment activation evidence 均已
> 绑定，`file_workspace_public@1` 已激活；该 gate 只允许后续离线历史迁移准入，
> 不授予 live/provider/HPC effect，也不把 activation 视为迁移或删除完成。
