# Session 02：Code Artifact 驱动 Execution

## 目标

让 `execution.pipeline.start(code_artifact_id=...)` 成为 executor 启动 pipeline 的主路径。Host 从 artifact catalog 读取精确源码，校验源码 artifact 类型，计算 digest，并把该源码送入受控 sandbox。execution 输出 artifact、run、engine invocation 和 workspace projection 必须记录源码 artifact provenance。

## 当前缺口

- 现有 execution pipeline 入口以 inline `code` 为主，源码不是稳定 artifact 工作面。
- dry-run、approval、run record 和 output artifact 缺少 `source_code_artifact_id` 与 `source_code_digest` 的强制关联。
- 如果 inline `code` 和未来的 `code_artifact_id` 同时存在，冲突语义尚未明确。
- execution engine 需要明确从 catalog 读取源码，而不是接收任意 Host path 或 agent 提供的本地文件路径。

## 实施范围

- 修改 `execution.pipeline.start` 参数，源码入口固定为 `code_artifact_id`。
- Host 根据 session/task/lane 权限从 artifact catalog 读取源码 artifact。
- 校验 artifact 必须是 pipeline source：`kind=code`，`format=python`，`metadata.semantic_type="pipeline_source"`。
- Host 对精确源码内容计算 stable digest，digest 算法固定为 SHA-256。
- dry-run 和正式运行使用同一份 digest 绑定的源码内容。
- sandbox 只接收 Host 从 catalog 解析出的源码 bytes，不接收 Host path。
- execution invocation、run record、output artifact provenance、events 和 workspace projection 记录：
  - `source_code_artifact_id`
  - `source_code_digest`
  - `source_code_version`
  - `pipeline_invocation_id`
- `execution.pipeline.start` 传入 inline `code` 时一律失败，不执行、不进入 dry-run。

## 接口变化

- `execution.pipeline.start` 输入：
  - `code_artifact_id`：必填，指向当前 session 内 pipeline source artifact。
- 缺少 `code_artifact_id` 时必须显式失败，错误码固定为 `missing_code_artifact_id`。
- 传入 inline `code` 时必须显式失败，错误码固定为 `unsupported_inline_pipeline_code`。
- 同时传 `code` 和 `code_artifact_id` 时也使用 `unsupported_inline_pipeline_code`，因为 inline source 字段本身不受支持。
- 如果 `code_artifact_id` 不存在、跨 session、不是源码 artifact、不是 Python、内容不可读或 digest 校验失败，必须显式失败。
- dry-run response 和 approval payload 必须展示源码 artifact id、版本、digest、artifact reads、SDK operations、expected outputs、资源/配额估计。
- dry-run 生成的 approval 必须绑定 `source_code_digest`；正式执行时 catalog 中源码内容必须与 approval 绑定 digest 完全一致。
- output artifact provenance 增加 `source_code_artifact_id`、`source_code_digest` 和 `source_code_version`；public projection 只展示安全摘要，不展示完整源码。

## 测试/验收

- 使用有效 `code_artifact_id` 启动 dry-run，返回 plan 并包含源码 artifact id、版本和 digest。
- approval 绑定 plan digest、源码 digest、artifact reads、HPC operation list、expected outputs 和资源估计。
- 正式执行后，run、engine invocation、output artifact 和 workspace projection 都能回链到源码 artifact 与 digest。
- 缺少 `code_artifact_id` 时失败，错误码为 `missing_code_artifact_id`。
- 传入 inline `code` 时失败，错误码为 `unsupported_inline_pipeline_code`。
- 非 code artifact、跨 session artifact、已删除或不可读 artifact、源码版本变更导致 digest 不一致时失败。
- public workspace 和 events 不暴露源码全文、Host path、sandbox host path 或 `storage_uri`。
- unit/fixture tests 必须覆盖 `code_artifact_id` dry-run、approval digest 绑定、正式执行 provenance、缺少源码 artifact 错误和 inline `code` 拒绝。

## 明确不做什么

- 不保留 inline `code` 执行路径。
- 不在本 session 增加外部网络数据库能力。
- 不把 notebook、repo 文件路径或用户本地路径作为 execution 输入。
- 不允许 sandbox 在运行时重新读取 Host catalog 中的源码或自行替换源码。
- 不把 `Pipeline sandbox completed` 当作面向用户的业务结果。
