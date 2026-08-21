# openzyme-execution-sdk

受控 sandbox 的通用 execution SDK。它拥有：

- `/openzyme/control.sock` 上有界、单帧、closed JSON-RPC transport；
- `ExecutionSdkError` 安全错误信封；
- parsed `ExecutionWorkloadSpec` 与 exact `ExecutionRouteIdentity`；
- revision-bound submit/observe/cancel protocol；
- `openzyme_execution_file_workspace@1` 内部 SDK identity。

SDK identity 不是公共 workspace projection 版本。Host/CLI/UI 的当前公共 contract 是
`file_workspace_public@2`；sandbox SDK 只向已受控的 Host supervisor 提交 typed Compute request，不读取公共
projection，也不自行选择 target、SSH、Slurm 或 fallback。正式提交必须由 Host 绑定 exact publication/revision、
workspace generation、capability binding、route、inventory 与 ControlledOperation identity。

该包只依赖 implementation-free execution contracts，不包含 AOX、HMMER、Vina、Science、SSH 或 Slurm 语义，
也不拥有 admission、canonical state 或外部效果。旧 `openzyme_pipeline.*` SDK namespace 已删除，不能作为
兼容 alias 恢复。
