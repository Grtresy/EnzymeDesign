# Session 08：Sandbox Artifact Boundary

## 目标

明确 persistent sandbox working copy 与 artifact catalog 的边界。executor 可以在 sandbox 内自由编辑和处理文件，但只有通过 Host-supervised SDK 登记、materialize 或 snapshot 的内容才能进入 canonical workspace。

## 当前缺口

- 当前 `artifacts.get/register` 语义围绕一次性 `/openzyme/input` 和 `/openzyme/output`，不适合持久 `/workspace`。
- 如果 persistent sandbox 文件自动等同于 artifact，会产生隐藏状态、不可复现输出和 provenance 缺口。
- 如果仍要求所有脚本编辑都通过 `artifact.patch_text`，persistent sandbox 的工作间价值会被抵消。
- 如果 `register` 只把 `/workspace/output` 的可变路径写入 artifact record，而不把内容复制封存到 Host-owned storage，后续 sandbox 文件修改会污染已经登记的 artifact。
- 如果 artifact identity、内容 digest 和展示路径混在一层，同名输出、重试和不同版本会被错误实现成覆盖、合并或不可复现的“当前文件”。

## Artifact Storage Model

S08 采用两层 artifact 架构，不在本 session 引入 canonical Alias/View 层：

- Blob 层：Host-private 内容存储，按 file `content_digest` 或目录 `tree_digest` 去重和校验。BlobStore root 由 Host 配置管理，不是 public API；executor、UI、agent tool result 和 workspace projection 都不得暴露 BlobStore path、Host path 或 `storage_uri`。
- Artifact 层：不可变语义记录，按 `artifact_id` 唯一，记录 session/task/lane/run/invocation、kind、format、validation result、producer metadata、provenance、sealed digest 和展示用 `relative_path`。
- `storage_uri` 或后续等价 Host-private storage field 必须指向 sealed Blob/Artifact storage；当前若仍指向 mutable sandbox workspace output path，只能作为 migration debt，不能作为 S08 目标语义。
- `relative_path` 只是 workspace-facing 展示路径和 UI tree hint，不是唯一身份，不参与内容封存路径，也不能替代 `artifact_id` 授权。
- 重复 `relative_path` 必须保留为多个 artifact leaf，并以 `artifact_id` 区分；Web UI / CLI 可以按 `created_at`、version、run 或 artifact id 展示重复项。
- Blob 可按 digest 去重；Artifact 不因 Blob digest 相同而自动合并，因为不同路径、producer、validation、run 或 provenance 代表不同语义记录。
- sealed Blob 的保留期独立于 sandbox workspace cleanup；清理 `/workspace`、回收 sandbox volume 或删除 workspace working copy 不得影响已被 Artifact record 引用的 sealed Blob。
- temporary/orphan Blob 只能由 Host Blob GC/cleanup 处理；GC 必须先检查 Artifact record 引用，不得删除仍被任一 visible Artifact record 引用的 sealed Blob。
- “current/latest/default” 只允许作为 projection 计算或 UI 排序策略，不作为 S08 canonical state；如未来需要可变指针，必须通过单独 Alias/View 设计补充，并且复现路径仍必须绑定 `artifact_id + digest`。

## 实施范围

- 引入三类边界操作：
  - `artifacts.materialize(artifact_id, target=None, mode="copy|readonly")`
  - `artifacts.register(path, kind, format=None, metadata=None)`
  - `artifacts.snapshot_code(paths, entrypoint, metadata=None)`
- `materialize` 只能读取当前 session/task/lane 授权 artifact，默认落到 `/workspace/input/...`，返回 sandbox-local path 与 artifact digest，不返回 Host `storage_uri`。显式 `target` 必须规范化后仍位于 `/workspace/input` 下，并拒绝 `..`、symlink escape、Host absolute path、对 readonly view 的写入、文件/目录类型冲突，以及同一 target 已存在不同 digest 内容。
- `register` 只接受 `/workspace/output` 下的文件或目录，并在登记前通过 Host-owned validator registry 执行非空、格式和 required columns 校验。
- validator registry 的最低校验由 `kind + format` 决定；`metadata.required_columns` 只能收紧 CSV 等结构化格式要求，不能绕过非空、FASTA、HMM、CSV 或其它内置 validator。
- `register` 默认执行 copy/seal：Host 读取 candidate output，计算 source digest/tree manifest，复制到 Host-owned temporary Blob，对 sealed copy 重新计算 digest；只有 sealed digest 与 source digest 一致后才创建 immutable Artifact record。
- `register` 必须把 source digest/tree manifest、validation、temporary Blob write、sealed digest recheck 和 Artifact row commit 作为一个 Host-supervised 事务序列处理；任一步失败都不创建 visible Artifact record，也不得 fallback 到 workspace path。
- register 期间如果 source 文件/目录的 size、mtime、content digest 或 tree manifest 在稳定性检查中发生变化，返回 `artifact_source_unstable`，不得封存半写文件或目录。
- S08 v1 不提供 `storage_mode="link"` 或其它 no-copy register 模式；不得把 mutable sandbox path、sandbox host path 或 runner path 写成 canonical artifact storage。
- `snapshot_code` 把 `/workspace/src` 中与执行相关的源码冻结为 `ArtifactKind.CODE`，记录：
  - `sandbox_workspace_id`
  - `entrypoint`
  - `source_tree_digest`
  - `file_digests`
  - `parent_source_code_artifact_id`（如有）
  - `task_id` / `lane_id` / `invocation_id`
- CODE artifact 是审计快照；executor 日常修改走 sandbox file tools，不要求每次编辑都创建新 CODE artifact。
- Host 必须在每次 `sandbox.exec` 启动命令前自动创建或绑定 source snapshot；该 snapshot 固定覆盖整个 `/workspace/src`，同一 `sandbox_run_id` 内的 `register`、受控 SDK operation、approval 和 backend run 都必须绑定同一个 `source_snapshot_artifact_id`。
- 如果 `/workspace/src` 为空、不可读、digest 计算失败或 CODE artifact commit 失败，`sandbox.exec` 必须 fail-closed，不启动命令，也不允许后续 `register` 补救。
- artifact catalog 仍是跨 teammate、UI、report、future run 的 canonical asset source。
- sandbox workspace manifest 记录 materialized input digests、registered output ids、source snapshots 和 command summaries。

## Resource Identity / Lifecycle

本 session 锁定三类 Host-owned 资源对象：`MaterializationRecord`、`RegisteredArtifact` 和 `SourceSnapshot`。sandbox 文件本身不是 canonical truth；只有这些记录回链到 artifact catalog 或 CODE artifact 后才成为可复查状态。

- `MaterializationRecord`
  - identity：`materialization_id = sandbox_workspace_id + artifact_id + artifact_digest + target_path + mode`。
  - owner：Host artifact/materialization service 创建和更新，executor 只能通过 SDK 请求。
  - lifecycle：同一 `artifact_id + artifact_digest + target_path + mode` 幂等复用；目标路径已有不同 digest 内容时失败，不覆盖。
  - path safety：`target_path` 必须由 Host 规范化和解析，最终 sandbox path 只能在 `/workspace/input` 下；任何 symlink escape、`..`、Host absolute path、readonly view 被写入、同一路径不同 digest 或文件/目录类型冲突都 fail-closed。
  - persistence：record、artifact digest、sandbox-local path 和 manifest entry 持久化；实际 sandbox copy/view 可由 Host 根据 record 重新 materialize。
  - `mode="copy"` 表示 sandbox-local managed copy；`mode="readonly"` 表示受控只读 view/copy，不能暴露 Host path，也不能被 executor 写入。
- `RegisteredArtifact`
  - identity：artifact catalog 分配不可变 `artifact_id`；目录注册还必须记录 stable tree digest 和 file digest manifest。`relative_path` 可重复，不是唯一键。
  - owner：Host artifact catalog service 创建 immutable Artifact record；Host BlobStore service 创建或复用 sealed Blob；sandbox workspace 只提供 candidate output。
  - lifecycle：按 `source digest/tree manifest -> validation -> temporary Blob write -> sealed digest recheck -> Artifact row commit` 顺序推进；所有步骤通过后才创建 canonical Artifact record，partial failure 不创建 artifact，也不把残留文件当作 output。
  - atomicity：Artifact row commit 是唯一 visible artifact 边界；validation 失败、Blob 写失败、sealed digest mismatch、provenance 不完整或 row commit 失败时都不得暴露半成品 artifact。
  - cleanup：Artifact row commit 失败后，已写入的 temporary/orphan Blob 进入 Host GC/cleanup 队列；如果无法立即清理，返回或记录 `artifact_blob_gc_pending`，但仍不得创建 visible Artifact record。
  - TOCTOU guard：Host 必须在 copy/seal 前后检查 source 文件/目录的 size、mtime、digest 或 tree manifest 稳定性；不稳定时返回 `artifact_source_unstable`。
  - validation：validator registry 由 Host 拥有并按 `kind + format` 选择最低 validator；缺失 validator 返回 `artifact_validator_missing`，validator 失败返回 `artifact_validation_failed`，metadata 只能增加约束不能降低内置校验。
  - copy/seal：file artifact 复制为 sealed blob；directory artifact 复制为 sealed tree，记录 normalized relative path、file digest manifest 和 tree digest。seal 完成后，后续 `/workspace/output` 文件修改不得改变已登记 artifact 内容。
  - idempotency：S08 service seam 以 `sandbox_workspace_id + source_path + source_digest/tree_digest + source_snapshot_artifact_id + metadata digest` 幂等；S09 接入 `sandbox.exec` 后，run-bound register 必须把 `sandbox_run_id` 或 `invocation_id` 纳入幂等键，避免不同 run 的 producer provenance 被误合并。
  - repeated paths：同一 `relative_path` 的不同 digest 创建新的 Artifact record，不覆盖旧 artifact；若调用方表达版本语义，只能通过 metadata 中的 `version`、`parent_artifact_id` 或 `replaces_artifact_id` 建立 lineage。
  - provenance：S08 必须记录 `sandbox_workspace_id`、`source_snapshot_artifact_id`、source digest/tree digest、sealed digest/tree digest、input artifact digests、validation result 和 source workspace-relative path；S09 接入 `sandbox.exec` 后，run-bound output 还必须记录 `sandbox_run_id` 或 `invocation_id` 以及 producer command/operation id。当前 session 范围内任一 S08 必填项缺失都返回 `artifact_provenance_incomplete`。
  - persistence：Artifact record、sealed digest/tree manifest、validation result、producer metadata、provenance、Blob reference 和 source workspace-relative path 持久化；workspace output 文件只是来源证据，不是 canonical storage。
- `SourceSnapshot`
  - identity：`source_tree_digest` 由 normalized relative path + file digest 计算；`source_snapshot_artifact_id` 是不可变 CODE artifact id。
  - owner：Host snapshot service 创建；executor 不能直接伪造 source snapshot metadata。
  - lifecycle：显式 `snapshot_code` 可创建审计快照；每次 `sandbox.exec` 启动前 Host 必须自动创建或绑定 run source snapshot，并将其写入 `SandboxRun`、registered artifact provenance、SDK operation、approval 和 backend run。
  - automatic scope：自动 run snapshot 固定覆盖整个 `/workspace/src`；不做 entrypoint dependency inference，不接受 executor 为 run snapshot 指定 paths。
  - canonicalization：只允许 `/workspace/src` 下路径；按 normalized relative path 排序；排除 `/workspace/input`、`/workspace/work`、`/workspace/output`、`/workspace/logs`、cache、临时锁文件和隐藏 runtime metadata。
  - run binding：同一 `sandbox_run_id` 内即使 `/workspace/src` 后续变化，也不改变该 run 的 `source_snapshot_artifact_id`；若 executor 要用新源码产生正式 artifact，必须启动新的 `sandbox.exec`。
  - parent：`parent_source_code_artifact_id` 只指向上一个 CODE snapshot；不存在可留空，不从任意 CODE artifact 猜测。

固定错误码：

- `artifact_scope_forbidden`
- `artifact_digest_mismatch`
- `artifact_materialization_conflict`
- `artifact_materialize_target_forbidden`
- `artifact_materialize_type_conflict`
- `artifact_register_invalid_path`
- `artifact_source_unstable`
- `artifact_validator_missing`
- `artifact_validation_failed`
- `artifact_provenance_incomplete`
- `artifact_seal_failed`
- `artifact_sealed_digest_mismatch`
- `artifact_blob_store_unavailable`
- `artifact_commit_failed`
- `artifact_blob_gc_pending`
- `source_snapshot_empty`
- `source_snapshot_required`
- `source_snapshot_failed`
- `source_snapshot_unavailable`

## 接口变化

- `openzyme_pipeline.artifacts.get(...)` 的长期目标改为 `materialize(...)` 的兼容层或别名；新文档与 examples 使用 `materialize`。
- `artifact.create_text` / `artifact.patch_text` / `artifact.diff_text` 不再是 pipeline source 日常编辑主路径；保留用于小型文本 artifact、兼容和直接 catalog 编辑场景。
- workspace projection 增加 sandbox/artifact relationship 摘要：
  - materialized input artifact ids
  - registered output artifact ids
  - source snapshot artifact ids
  - safe file count / size summary
- workspace projection 的 `artifacts[]` 继续以 `artifact_id` 作为 leaf identity；`relative_path` 可重复，重复 leaf 不合并。
- 后续实现该 session 时需要同步更新 `docs/v3/02-control-plane.md`、`docs/v3/04-public-interfaces.md`、`docs/v3/sessions/09-sandbox-file-command-runtime.md` 和 `docs/v3/execution-pipeline-docs/artifacts.md`，明确 artifact copy/seal、Blob/Artifact 两层、`relative_path` 非唯一、artifact-producing `sandbox.exec` 必须返回 `source_snapshot_artifact_id`，以及 public projection 不暴露 BlobStore/Host path。

## 建议实施顺序

S08 开工时先落资源边界和原子服务，不要直接从 SDK handler、临时路径判断或旧 `/openzyme/output` register 逻辑开始：

1. Schema / repository foundation
   - 增加 migration，删除或替换 `session_artifact_records(run_id, relative_path)` 的 unique index；`artifact_id` 是唯一身份，重复 `relative_path` 必须可保留为多个 artifact leaf。
   - 为 S08 增加 create-only Artifact row commit API；新的 `RegisteredArtifact` 路径不得使用会覆盖 `storage_uri`、`relative_path` 或 metadata 的 mutable upsert。旧兼容 producer 如仍需 upsert，必须与 S08 immutable commit 路径分开。
   - 增加 Host-private BlobStore 配置、temporary/sealed layout、digest-addressed sealed storage 和 GC/cleanup 队列骨架；`storage_uri` 或等价私有字段只能指向 sealed storage，不能指向 mutable workspace output。
2. Pure artifact boundary services
   - 建立 `ArtifactBoundaryService`（或等价 service），内部组合 BlobStore、materialization record、validator registry、source snapshot service 和 artifact catalog commit；SDK/agent handler 只做参数转发和结构化错误包装。
   - 先实现 path normalization、symlink escape 检查、digest/tree manifest、register transaction、idempotency lookup、provenance completeness check 和 validator registry，再接入 executor-facing tools。
   - register 事务顺序固定为 `source digest/tree manifest -> validation -> temporary Blob write -> sealed digest recheck -> Artifact row commit -> workspace manifest update`；最后一步失败时 Artifact 不可见，temporary/orphan Blob 进入 GC。
3. Workspace and source snapshot integration
   - 成功 materialize/register/snapshot 后原子更新 sandbox workspace manifest/read model：`materialized_input_artifact_ids`、`registered_artifact_ids`、`source_code_artifact_ids` 和安全摘要。
   - 先实现显式 `snapshot_code` 与 `/workspace/src` canonicalization；`sandbox.exec` 自动绑定 `source_snapshot_artifact_id` 的执行入口可由 S09 接线，但 S08 必须提供可调用 service seam，并让缺失 source snapshot 的 register fail-closed。
4. SDK / supervisor compatibility surface
   - 给 `openzyme_pipeline.artifacts` 增加 `materialize` 和 `snapshot_code`，并把新 `register` 主路径切到 `/workspace/output`；`get` 和 `/openzyme/*` 只作为 compatibility alias/bridge，不作为新合同。
   - Host supervisor RPC handler 调用 S08 service，不在 handler 内复制 digest、validation、path safety 或 commit 逻辑。
5. Focused verification and docs sync
   - 先补 service/repository 单元测试覆盖 atomicity、path safety、validator、Blob retention/GC、repeated `relative_path` 和 idempotency，再补 SDK/RPC smoke。
   - 完成代码后同步本文件列出的稳定文档；若实现选择 metadata schema 承载 sealed digest/provenance，必须在 docs 中明确哪些 metadata key 是 S08-required canonical fields。

## 测试/验收

- materialize 同一 artifact 时校验 session scope、digest 和安全路径；跨 session artifact 返回结构化错误。
- materialize 同一 artifact digest 到同一路径时复用 `MaterializationRecord`；digest 不一致或目标路径冲突返回 `artifact_materialization_conflict`，不得覆盖。
- materialize 拒绝 symlink escape、`..`、Host absolute path、写 readonly view、文件/目录类型冲突和同 target 不同 digest；路径越界返回 `artifact_materialize_target_forbidden`，类型冲突返回 `artifact_materialize_type_conflict`。
- register 非 `/workspace/output` 路径、空文件、坏 FASTA/HMM/CSV、缺 required columns 时失败。
- CSV `metadata.required_columns` 只能收紧 validator；坏 FASTA/HMM/CSV 不能通过 metadata 绕过内置校验，缺失 `kind + format` validator 时返回 `artifact_validator_missing`。
- register 时源文件/目录被并发修改，或 size、mtime、digest、tree manifest 任一稳定性检查不一致，返回 `artifact_source_unstable`，不创建 Artifact record。
- register 目录时必须生成 tree digest、file digest manifest 和 validation result；partial failure 不创建 canonical artifact。
- validation 失败、Blob 写失败、sealed digest mismatch、provenance 缺失、Artifact row commit 失败分别不产生 visible Artifact record；row commit 失败返回 `artifact_commit_failed`，temporary/orphan Blob 进入 GC/cleanup 队列。
- register 成功后修改原 `/workspace/output` 文件，已登记 artifact 的 sealed digest 和读取内容不变。
- register 同一路径不同 digest 时创建不同 `artifact_id`，旧 artifact 不被覆盖；workspace projection 用 `artifact_id` 区分重复 `relative_path`。
- register 同一 source digest、同一 source snapshot/run/invocation 和同一 metadata digest 重试时幂等返回同一 `artifact_id`，不重复写 Blob。
- register 不同路径但相同 content digest 时可复用 Blob，但必须保留不同 Artifact records 和各自 provenance。
- BlobStore 写入失败、sealed copy digest 与 source digest 不一致或 BlobStore 不可用时返回结构化错误，不创建 Artifact record，也不得 fallback 到 workspace path。
- `SessionArtifactRecord.storage_uri` 或后续等价 Host-private storage field 指向 sealed artifact/blob storage，不得指向 mutable sandbox workspace output path。
- workspace cleanup 后，sealed artifact 仍可按 `artifact_id` 读取；temporary/orphan Blob 只能由 Host GC 清理，且 GC 不删除仍被 Artifact record 引用的 sealed Blob。
- snapshot_code 生成不可变 CODE artifact，并能回链到 `sandbox_workspace_id`、entrypoint、file digests 和 parent snapshot。
- snapshot_code 的 digest canonicalization 对路径排序、排除目录和 parent 选择必须稳定，重复 snapshot 同一 tree 返回相同 source tree digest。
- S08 service seam 必须让缺失 source snapshot 的 `register` 返回 `source_snapshot_required` / `source_snapshot_unavailable`，不创建 artifact。
- workspace 内未 register 的中间文件不会出现在 artifact catalog 或 public workspace artifacts 列表。
- public payload 不暴露 Host path、sandbox host path、volume path、`storage_uri` 或完整源码全文。

S09 carry-over integration gate：

- `sandbox.exec` 启动时自动生成或绑定覆盖整个 `/workspace/src` 的 CODE artifact，并在 `SandboxRun` 中记录 `source_snapshot_artifact_id`、`source_tree_digest` 和 entrypoint/argv 摘要。
- 同一 `sandbox_run_id` 内多个 `artifacts.register(...)` 输出、受控 SDK operation、approval 和 backend run 都绑定同一个 `source_snapshot_artifact_id`。
- 本地 Python/bash 派生输出也必须绑定 source snapshot；缺失 source snapshot 时 `register` 返回结构化错误，不创建 artifact。
- `sandbox.exec` 启动后修改 `/workspace/src` 不会改变该 run 已绑定的 source snapshot；新源码产出正式 artifact 必须通过新的 `sandbox.exec` 生成新 snapshot。
- source snapshot 失败时命令不运行，错误为 `source_snapshot_required`、`source_snapshot_failed` 或 `source_snapshot_unavailable`。

## 明确不做什么

- 不把 persistent sandbox 做成 artifact catalog 的替代存储。
- 不支持任意 Host path register。
- 不新增 `register` 参数，继续保持 `artifacts.register(path, kind, format=None, metadata=None)`。
- 不支持 `register` 的 no-copy/link 模式；未来若需要，只能在单独设计中限定为 Host-owned immutable backend，不能链接 mutable sandbox path。
- 不引入 canonical Alias/View 层；`current/latest/default` 不作为 S08 持久真状态。
- 不在本 session 实现外部 provider/HPC 执行。
