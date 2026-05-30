# Session 12：统一 Bio / Bio Tools Adapter Contract

## 目标

在 persistent sandbox 模型下统一 `bio.*`、`bio_tools.*`、`structure_tools.*` 与 `docking.*` 的 adapter contract，并接入 Session 10 的 generic SDK supervisor RPC 底座与 Session 11 定义的 `hpc` placement / stage-fetch contract。

本 session 只锁定 adapter approval/result envelope、route/runtime references、artifact/provenance 字段和 drift/failure 语义。真实 provider adapter 由 Session 13 实现，真实 HPC runner stage/run/fetch 由 Session 14 实现。executor 只感知 logical SDK、`sandbox_workspace_id`、placement、artifact refs、declared outputs、bounded summary 和结构化错误，不感知 provider/local/HPC 私有路径、runner 细节或完整 backend command。

## 当前缺口

- 旧 adapter contract 围绕一次性 pipeline step 和静态 local/HPC route table，不能完整表达 persistent sandbox workspace、source snapshot、SDK approval continuation 和 HPC placement stage/fetch declarations。
- Session 10 只定义 generic controlled-operation record；仍需要在本 session 把 S11 的 public SDK operation 映射为统一 adapter approval/result envelope。
- S11 已明确 `fetch_refs`、output sealed digest、`registered_artifact_ids` 和 backend run id 是 post-run provenance；S12 必须避免把这些运行后字段误放入 pre-run approval digest。
- provider 输出、HPC declared outputs 和 sandbox 派生输出的 artifact 登记责任需要重新划清。
- SDK operation approval 后需要冻结 backend、params digest、source snapshot digest、input artifact digests、expected outputs、route/runtime references 和 planned fetch intent。

## 实施范围

S12 采用双层 envelope，而不是把 approval 前后字段混在同一个对象里。

### `AdapterApprovalEnvelope`

`AdapterApprovalEnvelope` 是 pre-run / approval-facing envelope。它由 S10 的 `ControlledOperation` 扩展而来，进入 `operation_digest`，并在真实 provider/HPC/local work 前创建。字段固定为：

- `adapter_envelope_schema_version`
- `sandbox_workspace_id`
- `sandbox_run_id`
- `operation_id`
- `operation_digest`
- `approval_id`
- `approval_state`
- `sdk_module`
- `function_name`
- `source_snapshot_artifact_id`
- `source_snapshot_digest` 或 `source_tree_digest`
- `input_artifact_ids`
- `input_artifact_digests`
- `params_digest`
- `placement`
- `hpc_workspace_id`（仅当 `placement="hpc"`）
- `stage_refs`
- `selected_backend`
- `route_reason`
- `route_policy_id`
- `runtime_packaging_id`
- `toolchain_id`
- `provider_config_digest`
- `resource_class`
- `resource_estimate`
- `expected_outputs`
- `planned_fetch_intent`
- `approval_requirement`

pre-run approval digest 只能覆盖以上字段。`fetch_refs`、output sealed digest、`registered_artifact_ids` / `output_artifact_ids`、`backend_run_id`、`provider_request_id` 和实际 validation result 都是运行后字段，不能参与 pre-run approval digest。

### `AdapterResultEnvelope`

`AdapterResultEnvelope` 是 post-run / result-facing envelope。它记录真实 provider/backend work 或 declared fetch/register 之后的安全结果和 provenance，字段固定为：

- `adapter_envelope_schema_version`
- `operation_id`
- `operation_digest`
- `sandbox_run_id`
- `status`
- `backend_run_id`（适用于 S14 tool/HPC backend）
- `provider_request_id`（适用于 S13 provider adapter）
- `fetch_refs`
- `registered_artifact_ids`
- `output_artifact_ids`
- `validation_results`
- `bounded_summary`
- `warnings`
- `error`
- `safe_diagnostics_ref`

`AdapterResultEnvelope` 必须回链同一个 `operation_id` / `operation_digest`，但不得原地修改已 approved 的 `AdapterApprovalEnvelope` 冻结字段。运行后新增字段只作为 provenance、SDK result 和 public projection 的安全摘要。

### Adapter 责任边界

- `bio.*` 由 Host provider adapter 执行，sandbox 不直接联网；provider 成功输出可以由 Host provider adapter 自动登记 artifact，并通过 `AdapterResultEnvelope` 返回 bounded artifact refs。
- `bio_tools.*` / `structure_tools.*` / `docking.*` 的当前 AOX/HMM 主线由 versioned route policy 固定为 `hpc`、`disabled` 或 prerequisite failure；Host-local、sandbox binary、sibling backend 和 fixture 都不是 fallback。
- 未来若 route policy 引入 local backend，只能作为 versioned policy 的显式 backend，不得在 S12 或 runtime 中根据可用性自动切换。
- 当 operation 使用 `placement="hpc"` 时，`AdapterApprovalEnvelope` 必须携带 S11 定义的 `hpc_workspace_id`、stage refs、workspace-relative paths、declared outputs 和 planned fetch intent；真实 runner 文件流仍由 Session 14 实现。
- HPC placement operation 完成时不得 eager persist visible artifacts，也不得在 run handle 中暗示 declared outputs 已登记。HPC declared outputs 只能通过 `hpc.Workspace.fetch_outputs(run)` 经 S08 `ArtifactBoundaryService` validation、copy/seal、sealed digest recheck 和 immutable Artifact row commit 后，进入 `AdapterResultEnvelope.fetch_refs` / `registered_artifact_ids`。
- pipeline 自己派生的 filtered CSV、scoring CSV、nodes/edges 等继续由 executor 显式 `artifacts.register(...)` 登记，不由 adapter 自动登记。
- adapter params 必须是 typed allowlist，不接受 raw shell、`extra_args`、path override、raw passthrough string、database mount、Host path、HPC remote path 或 arbitrary command。

## Route / Runtime References

`route_policy_id` 指向 versioned route policy；S12 envelope 只记录该 id，不冗余 `evidence_ref` 或 `parameter_inventory_ref`。route policy record 必须包含：

- Session 06 evidence 或后续 live prerequisite probe 的 `evidence_ref`。
- Session 06 parameter inventory 的 `parameter_inventory_ref`。
- `selected_backend`、`route_reason`、`resource_class`、`runtime_packaging_id`、`toolchain_id` 或 `provider_config_digest`。
- expected outputs、approval requirement、prerequisite/failure mapping 和 disabled/unsupported state。

缺 route policy、policy 与 evidence 不兼容、缺 runtime packaging、缺 toolchain/provider config 或 prerequisite 不满足时返回结构化 failure。`prerequisite_missing` 是非通过状态；不能用 deterministic fixture、Host-local observation、sandbox binary 或 sibling backend 替代。

`runtime_packaging_id` 指向 Host-managed packaging record；只有 safe digest 进入 provenance。`toolchain_id` 由 Session 14 toolchain registry 管理。`provider_config_digest` 由 Session 13 provider registry 管理，不能反推 credential。

## 接口变化

- 所有 SDK result 只返回 bounded summary、warnings、error 和 artifact refs。
- provider output artifact metadata 必须携带 operation id、placement、selected backend、input digests、params digest、source snapshot、provider request id、declared output path 和 validation result。
- HPC output artifact metadata 必须携带 operation id、placement、selected backend、stage refs、fetch refs、input digests、params digest、source snapshot、backend run id、declared output path 和 validation result。
- public projection 不展示 Host path、sandbox host path、runner path、remote path、SIF path、provider credential、database mount、`storage_uri` 或 complete command。
- error/warning envelope 固定字段为 `code`、`stage`、`retryable`、`summary`、`details_ref`、`safe_diagnostics`；完整 private command、provider secret 和 private path 只能留在 Host-private diagnostics。

## Resource Identity / Lifecycle

本 session 锁定 `AdapterApprovalEnvelope`、`AdapterResultEnvelope` 和 route/runtime reference 字段的 schema contract。

- `AdapterApprovalEnvelope`
  - identity：`operation_id` 由 S10 创建；`operation_digest` 由 approval-facing frozen fields 生成；`adapter_envelope_schema_version` 固定 approval envelope 结构。
  - owner：Host supervisor/adapter layer 创建并持久化；sandbox SDK 只能通过受控 RPC 触发。
  - lifecycle：进入 approval digest 后，selected backend、params digest、resource class、source snapshot digest、input artifact digests、expected outputs、planned fetch intent 和 route/runtime references 不得原地修改。
  - persistence：approval envelope、operation digest、approval id、artifact reads、route/runtime refs、resource estimate 和 expected outputs 持久化。
- `AdapterResultEnvelope`
  - identity：绑定同一 `operation_id` / `operation_digest`；provider request、backend run、fetch refs 和 output artifacts 各自使用 S13/S14/S08 定义的稳定 id。
  - owner：Host provider adapter、HPC/backend service 或 artifact boundary service 创建；sandbox SDK 只接收 bounded summary、warnings、error 和 artifact refs。
  - lifecycle：provider/tool/backend/fetch/register 完成后追加 result/provenance；不得改变已 approved 的 pre-run envelope。
  - persistence：warning/error summary、artifact refs、validation result、safe diagnostics ref 和 provenance 持久化；private backend command 和 path 不进 public projection。
- drift policy：任何 approved digest 覆盖字段漂移必须创建新 operation/approval 或返回 S10 的 `operation_drift_detected`，不能静默复用旧 approval。

固定错误码：

- `adapter_schema_incompatible`
- `operation_drift_detected`
- `route_policy_missing`
- `runtime_packaging_missing`
- `fixture_backend_forbidden`

## 本轮实现记录

S12 本轮实现落在 Session 10 controlled-operation supervisor seam 上，只锁定 adapter contract、route/runtime references、approval/result envelope 和 drift/failure 语义，不提前实现 S13 真实 provider client 或 S14 真实 runner stage/run/fetch。

- `ControlledOperation`、repository 和 SQLite migration 已持久化 S12 pre-run fields 与双层 envelope：`adapter_approval_envelope_json` 保存 approval-facing frozen fields，`adapter_result_envelope_json` 保存 post-run bounded provenance。
- `sandbox_runtime` 继续保留 S10 `s10.controlled_operation` RPC method，同时接受 `schema_version="s12.adapter_envelope.v1"` 的 adapter envelope；S10 generic payload 兼容保留。
- S12 `operation_digest` 只覆盖 pre-run approval fields：SDK module/function、params digest、source snapshot digest、input artifact ids/digests、placement、stage refs、route policy、runtime packaging/toolchain/provider config、resource estimate、expected outputs、planned fetch intent 和 approval requirement。`fetch_refs`、registered/output artifact ids、backend run id 和 provider request id 不参与 digest。
- `AdapterApprovalEnvelope` 在真实 work 前创建并持久化；approval id 创建后会回写 envelope，但运行后字段不会原地追加到 approval envelope。
- `AdapterResultEnvelope` 在 approved operation 完成后追加，回链同一 `operation_id` / `operation_digest`，并只暴露 bounded summary、warnings、error、safe diagnostics ref、provider/backend request id 和 artifact/fetch refs。
- route policy lookup 现在 fail-closed：缺 `route_policy_id`、未知 policy、policy 与 SDK module/function 不匹配、fixture backend、prerequisite missing、缺 runtime packaging、缺 provider config 或缺 toolchain 都返回结构化错误，不做 fallback。
- S11 HPC placement contract 已接入 approval envelope：static `hpc` route 必须显式传入 `placement="hpc"`、`hpc_workspace_id`、S11 `hpc_stage_ref` 和 planned fetch `declared_outputs`；workspace path 只接受 normalized POSIX relative path。
- public result/approval payload 对 Host path、sandbox host path、runner/remote path、SIF path、provider credential、database mount、`storage_uri`、raw/complete command 和常见 secret/config key 做 scrub；warning/error 被归一化为固定 envelope 字段。

本轮 focused 验收：

- `uv run pytest packages/openzyme-core/tests/test_migrations.py packages/openzyme-core/tests/test_repositories.py -q`
- `uv run pytest packages/openzyme-core/tests/test_sandbox_runtime.py -k "controlled_operation or s12" -q`
- `uv run pytest packages/openzyme-core/tests/test_sandbox_runtime.py -q`
- `uv run pytest packages/openzyme-core/tests -q`
- `uv run ruff check packages/openzyme-domain/src/openzyme_domain/control_plane.py packages/openzyme-core/src/openzyme_core/repositories.py packages/openzyme-core/src/openzyme_core/sandbox_runtime.py packages/openzyme-core/tests/test_migrations.py packages/openzyme-core/tests/test_repositories.py packages/openzyme-core/tests/test_sandbox_runtime.py`
- `git diff --check`
- `./scripts/check-mainline.sh`

## 推荐实施顺序

这一段是 S12 动工顺序，不是当前完成状态。每一步先补 focused failing test 或 schema/repository assertion，再改实现；只在前一步验收通过后进入下一步，避免把 S13 provider 或 S14 runner backend 提前塞进 S12。

1. 先扩展 domain / repository / migration：在 `ControlledOperation` 或其相邻 S12 schema 中持久化 `AdapterApprovalEnvelope` 的 pre-run 字段，并补齐 repository round-trip。新增字段至少覆盖 `sdk_module`、`function_name`、`route_policy_id`、`placement`、`hpc_workspace_id`、stage refs、`resource_class`、`planned_fetch_intent`、`runtime_packaging_id`、`toolchain_id`、`provider_config_digest` 和 `approval_requirement`；不得把 `fetch_refs`、`registered_artifact_ids`、`backend_run_id` 或 `provider_request_id` 放进 approval envelope。
2. 收紧 `sandbox_runtime` supervised SDK RPC：把 S10 generic envelope 升级为 S12 approval envelope 生成路径，固定 `operation_digest` 只覆盖 pre-run 字段；同一 idempotency key 或 approved digest 漂移时继续返回 `operation_drift_detected`。本步骤只处理 fake/controlled operation，不调用真实 provider、runner 或 HPC upload/download。
3. 实现 versioned route policy lookup：`route_policy_id` 必须能解析到 safe route policy snapshot，并要求 policy 回链 Session 06 `evidence_ref` / `parameter_inventory_ref`、selected backend、resource class、expected outputs、approval requirement 和 prerequisite mapping。缺 policy、缺 evidence、evidence/policy 不兼容、缺 runtime packaging、缺 toolchain/provider config 都结构化失败，不能 fallback。
4. 接入 S11 placement contract：把 `hpc.workspace`、`stage_artifact`、declared outputs 和 planned fetch intent 映射进 `AdapterApprovalEnvelope`；确认 static HPC route operation 未传 explicit placement 时失败，且 `fetch_refs`、registered artifacts、output sealed digest 和 backend run id 不参与 pre-run digest。
5. 增加 `AdapterResultEnvelope` result seam：让 provider-style auto-register result、HPC `fetch_outputs(run)` result、structured warnings/errors 都统一返回 bounded result/provenance envelope。HPC declared outputs 只能在 S08 artifact boundary register 成功后写入 `fetch_refs` / `registered_artifact_ids`；operation completion 不得 eager persist visible artifacts。
6. 同步 artifact metadata / projection / events：provider output metadata、HPC output metadata、workspace projection 和 SDK result 都只暴露 safe ids、digests、bounded summary、warnings、errors 和 artifact refs；不得暴露 Host path、sandbox host path、runner/remote path、SIF path、provider credential、database mount、`storage_uri` 或 complete command。
7. 最后跑 focused regression：覆盖 approval envelope digest、route policy evidence failure、HPC placement pre-run/post-run 字段分离、`operation_drift_detected`、fixture forbidden、provider auto-register bounded result、HPC fetch-register result envelope，以及 public payload path/secret sanitizer。通过 focused tests 后再跑相关 S10/S11 回归。

## 测试/验收

- 每个受控 SDK operation 在真实 provider/HPC work 前都有 `AdapterApprovalEnvelope`，包含 placement、selected backend、route reason、route policy id、resource estimate、expected outputs 和 approval requirement。
- approval digest 只包含 pre-run 字段；`fetch_refs`、`registered_artifact_ids`、`output_artifact_ids`、`backend_run_id` 和 `provider_request_id` 缺失时不阻塞 pre-run approval envelope 创建。
- HPC placement operation 的 approval envelope 能表达 `hpc_workspace_id`、stage refs、declared outputs 和 planned fetch intent，但不泄露真实 remote path。
- HPC placement operation 的 result envelope 只能在 `fetch_outputs(run)` 经 S08 artifact boundary 成功后携带 `fetch_refs`、`registered_artifact_ids` 和 validation result；operation completion 不得 eager persist visible artifacts。
- `bio.*` provider result 可以自动登记 provider artifacts，但大型 FASTA、metadata、raw hits 和 parsed hits 只能以 artifact refs / bounded summary 返回。
- 运行时的 SDK operation、backend、params digest、resource class、source snapshot digest、input artifact digest、expected outputs 或 route/runtime references 与 approved `operation_digest` 不一致时触发新的 approval 或 `operation_drift_detected`。
- envelope schema version、route policy id、runtime packaging id、toolchain id/provider config digest 的缺失或不兼容都有结构化错误。
- route policy 必须回链 Session 06 evidence / parameter inventory 或后续 live prerequisite probe；policy 缺 evidence 或 evidence 状态不是可用状态时不能标记 route passed。
- deterministic fixture adapter 只能由 unit/eval fixture 显式注入；产品默认路径不能自动回退到 fixture。
- public projection、SDK result、event 和 artifact metadata 不暴露 Host path、sandbox host path、runner path、remote path、SIF path、provider credential、database mount、`storage_uri` 或 complete command。

## 明确不做什么

- 不在本 session 实现真实 provider 或 tool backend。
- 不在本 session 实现真实 HPC runner upload/download/fetch。
- 不把 local/HPC backend 暴露成两个领域 pipeline API；HPC 只通过 Session 11 的 placement/file-transfer namespace 表达。
- 不让 Host 根据 backend 可用性自动选择 sibling backend、Host-local backend、sandbox binary 或 fixture fallback。
