## Why

当前 `artifact.*`、`artifacts.materialize/register/snapshot_code`、`sandbox.file.*` 和 `hpc.stage_artifact` 把同一文件拆成多次 catalog/stage 生命周期，阻碍 researcher 产物直接成为 executor pipeline 输入。独立 Git workspace 建立后，这些通用 artifact 边界应由普通文件与 commit identity 取代。

## What Changes

- **BREAKING**：sandbox 和 execution pipeline 直接在 agent clone 中使用普通文件、目录和原生 shell；不再要求 materialize、register 或 source snapshot。
- 移除 model/SDK-facing `artifact.*`、`artifacts.*`、`sandbox.file.*` compatibility authoring 和 `hpc.stage_artifact`；文件 CRUD 由 shell/OS/Git 完成。
- external execution 的 source identity 绑定 clean private/published Git revision，而不是 `source_snapshot_artifact_id`。
- sandbox-to-Host typed context 只保留 approval、publication、external-job record 等 control-plane effects，不再代理普通文件或网络 I/O。
- 删除 `HpcStageRef` 作为目标合同；迁移完成前的旧调用只能由历史迁移读取，不能成为 current fallback。
- 不捕获宽泛异常、不猜测路径、不自动创建替代输入；OS/Git/runner 错误原样形成明确失败。

## Capabilities

### New Capabilities
- `file-workspace-sandbox`: 定义 clone 内普通文件、原生命令和 revision-bound execution 的 sandbox 合同。

### Modified Capabilities
- `sandbox-host-authority`: 把 typed Host gateway 收缩到真正 control-plane effects，并移除 artifact publisher/stage authority。

## Impact

影响 `openzyme-core` sandbox runtime/tool catalog、`openzyme-runtime` artifact boundary、`openzyme-engines` pipeline sandbox、`openzyme-pipeline` SDK、domain records、migrations、prompts、tests 和 execution docs。
