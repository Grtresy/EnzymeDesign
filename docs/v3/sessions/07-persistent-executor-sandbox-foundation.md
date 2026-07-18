# Session 07：Persistent Executor Sandbox Foundation

## 目标

把 execution sandbox 从一次性 pipeline runner 升级为 executor 的持久工作区底座。每个 executor 在 session 内拥有独立、可恢复的 `sandbox_workspace_id` identity；Host 可以按该 identity 重新挂载 `/workspace` 并投影安全状态。sandbox 仍是受控 working copy/cache；canonical state 继续由 task board、engine invocation、artifact catalog、run、approval 和 report 表达。

本 session 只做 foundation：`sandbox_workspace_id` identity、持久目录/volume、manifest、quota、安全 projection、状态接口和隔离验收。不实现 `sandbox.file.*`、`sandbox.exec`、provider/HPC bridge、approval resume 或真实外部能力。

## 当前缺口

- 当前 pipeline sandbox 以 invocation 为单位创建和销毁，agent 需要把很多临时文件、脚本和中间状态转成 artifact 才能继续工作。
- CODE artifact 被当成日常源码编辑主路径，导致简单迭代也要走 catalog patch/diff 工具，工作流笨重。
- executor-facing 工具和 prompt 仍可能把 `execution.pipeline.start` 描述成主路径；这会继续强化一次性 pipeline 心智模型。
- local Apptainer、HPC runner、provider adapter 和 sandbox 文件系统混在 execution 概念里，executor 难以形成稳定心智模型。
- 后台 scheduler 如果同时负责推进、恢复、后端选择和 fallback，会接管 agent 判断并制造本地/HPC 不一致。

## 已锁定决策

- `sandbox_workspace_id` 由 `session_id + agent_member_id` 唯一决定；同一 session 内同一 executor agent member 复用同一个 persistent sandbox workspace。`agent_id` 只作为展示、兼容和 tool/result 可读字段，不参与 identity 派生。
- `sandbox_workspace_id` 固定派生为 opaque id：`sw_{sha256(session_id + ":" + agent_member_id)[:24]}`。`agent_member_id` 是 control-plane 中 session-scoped agent member 的稳定 id，不使用用户可控 label、task subject、lane name 或 Host path。
- sandbox workspace registry/repository 属于 core/control-plane canonical state。`packages/openzyme-engines` 只负责按 `sandbox_workspace_id` 启动、attach、运行和释放 runtime envelope，不能成为 workspace identity 的唯一真相。
- `create_or_get(session_id, agent_member_id)` 必须幂等，并在 core/control-plane repository 层以 `(session_id, agent_member_id)` 建立唯一约束；并发调用只能得到同一个 canonical sandbox workspace record，不能创建第二个 workspace identity。当前单进程 SQLite 合同下，所有 service instance 还必须按 resolved root + workspace id 共用进程内临界区，使 canonical lookup、exclusive filesystem create/既有 layout 校验和 record save 成为同一串行步骤；竞争方在前一调用保存后重新 lookup 并验证同一 READY record，不得把刚建立的 leaf 误判为 orphan 后以 CORRUPT 覆盖。该临界区不构成多进程部署承诺。
- sandbox workspace root 是 Host composition 注入的 deployment/attempt-scoped 依赖；status service、runtime/file service、显式/隐式 workspace lookup 和恢复路径必须使用同一个 root，不能分别实例化后回落到共享 `/tmp` 默认值。
- `task_id` / `lane_id` 只是当前 focus metadata。切换 task 或 lane 更新 focus，不创建新的 sandbox workspace，也不改变 `sandbox_workspace_id`。
- s07 的默认模型是多个 executor 使用同一个 Host-configured sandbox base image digest，分别启动各自的 rootless container process，并挂载各自独立的 persistent sandbox `/workspace` volume。image layer 可以共享，sandbox workspace 绝不能共享。
- “persistent sandbox” 指 sandbox workspace volume、sandbox workspace manifest、projection summary 和 canonical records 持久化；container process/container id 是可丢弃的 runtime envelope。Host 可以为了性能复用存活容器，但产品语义不能依赖容器一直存在。
- executor sandbox base image 由 s07 的 Host-level image registry / bootstrap contract 定义和管理；真实 MAFFT、CD-HIT、HMMER、Apptainer SIF、HPC runner 等领域工具/backend 镜像由 s14 或后续 toolchain/backend registry 管理。
- s07 起文档口径切到 sandbox-first：executor-facing 主路径是 `sandbox.workspace.status` 加后续 s09 的 `sandbox.file.*` / `sandbox.exec`。`execution.pipeline.start` 不再作为 executor 必须调用的主路径；当前代码中仍存在的 `execution.pipeline.start(code_artifact_id=...)` 只作为迁移兼容和实现 debt 记录。
- s07 验收只证明 Host-managed workspace foundation；跨 work turn 的真实文件 CRUD 与命令执行由 s09 验收。

## 实施范围

- 为每个 executor 建立 persistent sandbox workspace identity：
  - `sandbox_workspace_id`：按 `session_id + agent_member_id` 派生为稳定 opaque id，必须稳定、不可由用户输入直接指定为 Host path。
  - `session_id`
  - `agent_member_id`：identity 派生源和权限校验主体。
  - `agent_id`：agent-facing 展示/兼容字段，不参与 identity。
  - `task_id` / `lane_id` focus：可更新的当前焦点，不参与 `sandbox_workspace_id` identity。
  - `status`：`ready` / `attached` / `detached` / `corrupt` / `quota_exceeded` / `missing_image` / `image_incompatible`。
  - `image_ref`
  - `image_digest`
  - `image_version`
  - `sandbox_protocol_version`
  - `volume_digest` 或安全 workspace summary
- 容器可重启，sandbox workspace volume 持久化；Host 可以按 `sandbox_workspace_id` 恢复该 executor 的 `/workspace`。
- sandbox image 由 Host-level sandbox image registry/config 管理，不按 user session 或 executor 动态创建。s07 只要求默认 image 可解析到固定 digest、可用于启动 rootless sandbox、并把 digest 写入 manifest/projection；如果 image 缺失，返回 `missing_image` / `sandbox_image_missing`，不得自动换成 `latest` 或其它可运行镜像。
- attach/bootstrap 也是幂等操作。若同一 `sandbox_workspace_id` 已有可用 runtime envelope，Host 可以复用；若没有可用 envelope，Host 可以按 manifest 和 image digest 重建。runtime envelope、container id 和 attach lease 都不能成为 canonical workspace identity。
- 持久化 volume 只挂载为 `/workspace`；默认目录结构：
  - `/workspace/src`：executor 可编辑脚本和 notebooks-like Python modules。
  - `/workspace/input`：Host materialized catalog artifacts，默认只读。
  - `/workspace/work`：中间工作区。
  - `/workspace/output`：准备注册的正式输出。
  - `/workspace/logs`：命令与 SDK 日志。
  - `/workspace/manifest`：safe digest、操作记录、snapshot 指针。
- repository 无 canonical row 时，派生 workspace leaf 必须不存在，并由 Host 以 no-replace/exclusive-create 建立上述六目录；leaf 已预存为目录、文件或 symlink 时返回 `corrupt` / `sandbox_volume_corrupt`，不得接管、补建或修改现场。repository 已存在 record 时，status/recovery 只能验证现有根及六目录均为真实非 symlink 目录；缺失、类型错误或 symlink 同样 fail closed。
- `/openzyme/control.sock` 只作为运行时 Host supervisor IPC，不持久化；旧 `/openzyme/input|work|output|logs` 若继续存在，只能是兼容 symlink/bind view 或实现细节，不作为 executor 长期心智模型。
- sandbox 默认无公网、非 root、资源受限；不得挂载 Host repo、用户 home、`.ssh`、runner config、provider credential、database private mount 或 HPC secret。
- container id、runtime command、host-side volume path 和 image local store path 都不是 public/canonical state；sandbox workspace recovery 必须能通过 `sandbox_workspace_id + image_digest + manifest` 重新 attach 或重建容器 envelope。
- workspace 需要 quota 与生命周期策略：
  - 默认 per-session/per-agent storage cap，s07 文档默认值为 `2GiB`，实现可通过 Host settings 覆盖。
  - s07 只验收 create/attach/status/recovery 阶段的 quota scan、quota summary 和超限状态投影；文件写入时的逐操作 enforcement 由 s09 的 `sandbox.file.*` / `sandbox.exec` 实现。
  - 成功后可清理 transient work，但保留 manifest、registered outputs、code snapshots 和必要 command summaries。
  - 失败后保留诊断摘要、日志 artifact refs、最近错误和必要 workspace snapshot。
  - 超限返回结构化 `sandbox_quota_exceeded`，status 仍可读；Host 不能为恢复到 ready 而静默删除仍需审计的文件。后续 cleanup 必须是显式 operator/service 动作，并保留 bounded audit summary。
- Host 提供只读 projection：sandbox workspace status、`sandbox_workspace_id`、image ref/digest/version/protocol、安全目录摘要、最近命令、最近错误、registered artifact refs；不暴露 host-side volume path。
- sandbox workspace manifest 至少记录：
  - `manifest_version`
  - `sandbox_workspace_id`
  - `session_id`
  - `agent_member_id`
  - `agent_id`
  - `focus_task_id`
  - `focus_lane_id`
  - `image_ref`
  - `image_digest`
  - `image_version`
  - `sandbox_protocol_version`
  - `created_at`
  - `last_attached_at`
  - `quota_summary`
  - `directory_summary`
  - `materialized_input_artifact_ids`
  - `registered_artifact_ids`
  - `source_code_artifact_ids`
  - `last_command_summary`
  - `last_error`
- manifest 和 `directory_summary` 必须可稳定断言：
  - `directory_summary` 只覆盖 `/workspace/src`、`/workspace/input`、`/workspace/work`、`/workspace/output`、`/workspace/logs` 和 `/workspace/manifest` 的安全相对路径摘要。
  - summary 至少包含每个目录的 file count、total bytes、latest mtime summary、content digest summary 和 truncated 标记；path 按字节序稳定排序。
  - digest 计算只使用相对路径、文件类型、size 和 content digest，不使用 host-side volume path、container id、runtime command 或本地 image store path。
  - timestamp 字段可以记录在 manifest 中，但不能影响 `volume_digest` / directory digest；否则 restart recovery 测试无法稳定复现。
  - volume 损坏、manifest schema 不可读或 summary 计算失败时返回 `sandbox_volume_corrupt` 或 `sandbox_status_unavailable`，不得 fallback 到空 summary。
- s07 只需要 Host-side service/test seam 证明同一 `sandbox_workspace_id` 的目录和 manifest 能恢复；不要求 agent 在本 session 里已经能通过文件工具写入或读取文件。

## Sandbox Image Registry / Bootstrap Contract

s07 必须定义 executor sandbox base image 的 Host-level registry / bootstrap contract。该 registry 不是 user session state，也不由 executor agent 修改；它是 Host 启动 sandbox workspace 的受控配置面。

- Host config 至少指定默认 `image_ref`，并在 bootstrap 时解析为固定 `image_digest`。`image_ref` 只是可读别名或 operator 配置项，sandbox workspace identity 和 provenance 必须使用 resolved digest。
- production/cutover 配置应 pin digest；如果只配置 mutable tag，Host 必须在 bootstrap/status 中暴露 resolved digest，并把该状态标记为非 cutover-grade，不能把 tag 当作可复现身份。
- operator-facing image install、pull、build、trust 或 registry refresh 必须是独立显式动作，不由 executor tool、scheduler wakeup、workspace status 或 `create_or_get` 自动触发。S07 只要求 status/preflight 能报告缺失或不兼容，并给出 operator 可读 hint。
- image registry record 至少包含：
  - `image_ref`
  - `image_digest`
  - `image_family`
  - `image_version`
  - `sandbox_protocol_version`
  - `manifest_schema_version`
  - `capabilities_declared`
- `capabilities_declared` 至少声明：
  - rootless Podman compatible
  - non-root default user
  - no-network default policy
  - `/workspace` mount point
  - `/openzyme/control.sock` runtime mount point
  - expected `bash`
  - expected `python`
  - expected `openzyme_pipeline` import path / SDK version
- s07 的 bootstrap check 只负责“存在、可解析、可启动、可投影”：Host 能解析 `image_ref` 到 digest，确认本机 image digest 可用，启动 rootless container envelope 并挂载独立 `/workspace`，把 image metadata 投影到 sandbox workspace status。
- s07 不验收 Python/bash 交互、`openzyme_pipeline` SDK import、`sandbox.exec` 执行或 SDK supervisor RPC；这些由 s09 的 command runtime 验收。
- 如果 image 不存在或 digest 不可用，`sandbox.workspace.status` 返回 `status="missing_image"` 和 `sandbox_image_missing`，不得自动 pull、自动换 tag、自动换 fallback image，除非 operator 显式执行独立的 image install/bootstrap 动作。
- 如果 image 的 `sandbox_protocol_version`、`manifest_schema_version` 或 declared capability 与 Host 期望不兼容，`sandbox.workspace.status` 返回 `status="image_incompatible"` 和 `sandbox_image_incompatible`，不得降级到旧 runner 或旧 `execution.pipeline.start` 路径。
- s07 不把 MAFFT、CD-HIT、HMMER、Apptainer SIF、HPC runner、database mount 或 provider credential 放入 executor base image。领域工具 packaging、backend route 和 runtime packaging digest 由 s14 管理。

## 接口变化

- 新增 executor-facing 只读状态能力：
  - `sandbox.workspace.status(sandbox_workspace_id=None)`
- 权限语义固定：
  - `sandbox_workspace_id=None` 时只返回当前 executor agent member 在当前 session 内自己的 sandbox workspace status。
  - 显式传入 `sandbox_workspace_id` 时，Host 必须校验该 workspace 属于当前 `session_id + agent_member_id`；跨 session、跨 agent member、未知 workspace 或非 executor actor 访问返回结构化失败。
  - 显式与隐式 lookup 必须经过同一 context-root-aware service；workspace id 的显式存在不能跳过 ownership、root continuity、layout 与 image compatibility 检查。
  - workspace id 是 opaque id 但不能作为唯一安全边界；权限校验必须基于 canonical repository 中的 session/member 绑定。
- sandbox workspace status 至少返回：
  - `sandbox_workspace_id`
  - `agent_member_id`
  - `agent_id`
  - `task_id`
  - `lane_id`
  - `status`
  - `image_ref`
  - `image_digest`
  - `image_version`
  - `sandbox_protocol_version`
  - `image_compatibility`
  - `quota_summary`
  - `directory_summary`
  - `last_command_summary`
  - `last_error`
  - `registered_artifact_ids`
  - `source_code_artifact_ids`
- 结构化错误码固定为：
  - `sandbox_workspace_not_found`
  - `sandbox_image_missing`
  - `sandbox_image_incompatible`
  - `sandbox_volume_corrupt`
  - `sandbox_quota_exceeded`
  - `sandbox_workspace_forbidden`
  - `sandbox_status_unavailable`
- `sandbox_workspace_forbidden` 用于 actor/session/member 不匹配；`sandbox_workspace_not_found` 只用于当前 actor 有权访问范围内确实不存在的 workspace，不能用 not found 掩盖权限语义。
- agent-facing 执行入口的稳定目标是 s09 的 `sandbox.exec`；Host 内部可以创建 sandbox run、SDK operation、backend run、approval 和 provenance record，但不把 `execution.pipeline.start` 作为 executor 必须调用的工具。
- `ArtifactKind.CODE` 仍保留，但含义调整为执行相关源码的不可变审计快照，不再是 executor 日常编辑主路径。

## 后续代码实现落点

本次计划如果进入实现，预期只改文档以外的下列代码面；这些代码改动不属于当前文档-only 工作：

- 在 core/control-plane 增加 sandbox image registry/config 与 workspace registry/service，负责 image ref/digest bootstrap、compatibility check、`create_or_get(session_id, agent_member_id)`、focus update、quota summary、manifest read/write 和 safe status projection。
- 在 `packages/openzyme-engines` 中只增加 runner/runtime adapter，按 core/control-plane 返回的 `sandbox_workspace_id` attach workspace，不分配 workspace identity，也不保存唯一 canonical registry。
- 将当前 invocation-scoped `PodmanPipelineSandboxRunner` 迁移为可绑定已有 `sandbox_workspace_id` 的 runner；runner 可以继续创建 per-run process，但不能删除 executor 的 persistent `/workspace`。
- 在 executor tool descriptor / prompt 中新增 `sandbox.workspace.status`，并移除或弱化 `execution.pipeline.start(code_artifact_id=...)` 作为 executor authoring 主路径的描述。
- 在 workspace projection 中增加 sandbox summary 分区，只暴露 `sandbox_workspace_id`、status、digest、artifact refs 和 bounded diagnostic summary。
- 增加 `sandbox_workspace_id` identity、agent/session 隔离、quota、projection sanitizer 和 manifest recovery 回归测试。

## 测试/验收

- 同一 session 内同一 `agent_member_id` 连续获取 sandbox workspace status 时得到同一 `sandbox_workspace_id`；切换 `task_id` / `lane_id` 只更新 focus metadata。
- 并发 `create_or_get(session_id, agent_member_id)` 和重复 attach 返回同一 canonical workspace record；不能创建重复 workspace identity，不能把 container id/lease id 写成 canonical identity。
- `sandbox.workspace.status()` 默认只返回当前 executor 自己的 workspace；传入其它 executor 或其它 session 的 `sandbox_workspace_id` 返回 `sandbox_workspace_forbidden`，不泄露 private manifest、volume path 或 directory summary。
- 删除 engine-local registry 后，重启 Host 仍能从 core/control-plane repository 恢复 `sandbox_workspace_id`、manifest pointer、image digest 和 focus metadata。
- 不同 executor 或不同 session 的 sandbox workspace 彼此隔离，不能跨 sandbox workspace status 或 manifest 读取私有状态。
- workspace projection 不泄露 Host volume path、container runtime command、runner config 或 credential。
- sandbox foundation restart 后 manifest 和 workspace directory summary 仍可恢复；container 进程退出不等于 task completed。
- quota 超限、image 缺失、image 不兼容、volume 损坏、workspace 不存在都返回上述结构化错误码。
- S07 能证明默认 image ref 解析为固定 digest，并把 `image_ref`、`image_digest`、`image_version` 和 `sandbox_protocol_version` 写入 manifest/status；缺失或不兼容时不自动 fallback 到其它 image。
- S07 能证明 image 缺失或不兼容不会触发自动 pull/build、自动换 tag、自动换旧 runner 或自动创建替代 image；status/preflight 只返回结构化错误和 operator hint。
- manifest / directory summary digest 在 restart 前后稳定；digest 不受 `last_attached_at` 等 timestamp 变化影响，且 projection 不包含 Host path、container id、runtime command 或 image local store path。
- quota scan 超限时 status 返回 `sandbox_quota_exceeded` 和 bounded summary；不会静默删除 workspace 文件或把超限 workspace 伪装成 ready。
- scheduler 只能唤醒 executor 继续既有 task/workspace 或等待中的 SDK operation，不得因为 sandbox 存在而自动规划、自动 fallback、自动切换 backend 或自动完成 task。
- `rg "execution.pipeline.start" docs/v3` 后，相关表述不得再说 executor 必须直接调用它作为 authoring 主路径；若提到，只能作为 migration/internal Host bridge/debt 或 legacy/current-code context。
- 实现 S07 时，executor prompt、tool descriptor 和相关 prompt/eval regression 也必须切到 sandbox-first：不得继续要求 executor 先创建 CODE artifact 再调用 `execution.pipeline.start(code_artifact_id=...)` 作为 authoring 主路径。当前代码中仍存在的旧提示词属于本验收门槛覆盖的 implementation debt，本 docs-only patch 不提前修改运行代码。

## 明确不做什么

- 不实现 `sandbox.file.*`、`sandbox.exec`、文件 CRUD、命令执行或 approval resume。
- 不实现 provider、bio_tools 或 HPC backend。
- 不把 MAFFT、CD-HIT、HMMER、Apptainer SIF、HPC runner 或领域 database mount 打包进 executor base image。
- 不开放 sandbox 直接 SSH、Slurm、公网、Host path 或 runner config。
- 不把 sandbox workspace 当作 canonical artifact catalog。
- 不在本 session 决定领域 SDK 形状；`hpc` placement namespace 和旧 shorthand 的处置由 Session 11 锁定。
