# Session 11：领域 SDK 与 HPC Placement 边界

## 目标

在 Session 10 建立 generic SDK supervisor RPC / approval 底座后，定义 executor-facing public SDK 的分层边界：领域 operation 由 `bio` / `bio_tools` / `structure_tools` / `docking` 表达；HPC 执行位置、远端工作区和声明式文件流由 `hpc` 表达。`hpc` 不退役为纯兼容层，而是升级为 first-class placement / remote workspace / declarative stage-fetch namespace。

## 当前缺口

- 旧计划把问题简化为 “是否移除 agent-facing HPC SDK”，但 persistent sandbox 需要 executor 能显式表达 HPC placement、输入 staging、declared outputs 和 fetch/register 意图。
- `fpocket`、`vina`、MAFFT、CD-HIT、HMMER 等能力需要按领域 operation 暴露，避免把所有生物/化学能力都塞进 `hpc.*`。
- `selected_backend=hpc` 不能只作为事后 provenance；当 executor 需要控制文件流时，HPC placement 必须在 plan / code 中提前可见。
- S08 已经把 artifact catalog 定义为 sealed Blob/Artifact 两层架构；S11 的 stage/fetch 如果绕过 sealed artifact digest、ArtifactBoundaryService 或 source snapshot provenance，会重新引入 mutable path、runner output 和不可复现 artifact 的问题。
- 仍需避免 executor 接触 SSH、Slurm、runner config、真实 remote absolute path、Host `storage_uri`、database mount 或 credentials。

## 实施范围

- 基于 Session 10 的 generic controlled-operation substrate，锁定第一版 public SDK 模块集合：
  - `artifacts`
  - `bio`
  - `bio_tools`
  - `preprocess`
  - `structure_tools`
  - `docking`
  - `hpc`
  - `run`
- `hpc` 的稳定职责：
  - 创建或引用 Host-supervised HPC placement workspace。
  - 声明把 S08 sealed catalog artifact stage 到 workspace-relative path。
  - 为领域 operation 提供 `placement` / `workspace` 参数。
  - 声明 expected outputs，并在 operation 完成后 fetch/register declared outputs。
  - 返回 bounded summary、opaque workspace/run handle 和 structured errors；HPC declared output 的 artifact refs 只由 `fetch_outputs(run)` 经 S08 artifact boundary 返回。
  - stage/fetch 只能产生 S08 canonical artifact refs，不得把 HPC workspace、runner workdir、remote path 或 sandbox temp path 当作 artifact storage。
- 推荐 API 形态：

```python
from openzyme_pipeline import artifacts, docking, hpc

receptor = artifacts.get("art_receptor")
ligand = artifacts.get("art_ligand")
artifacts.materialize(receptor["artifact_id"], target_path="/workspace/input/receptor.pdbqt")
artifacts.materialize(ligand["artifact_id"], target_path="/workspace/input/ligand.pdbqt")

ws = hpc.workspace("vina_batch")
remote_receptor = ws.stage_artifact(
    receptor["artifact_id"],
    workspace_path="inputs/receptor.pdbqt",
)
remote_ligand = ws.stage_artifact(
    ligand["artifact_id"],
    workspace_path="inputs/ligand.pdbqt",
)

run = docking.vina(
    receptor=remote_receptor,
    ligand=remote_ligand,
    placement=ws,
    params={"center": [0, 0, 0], "size": [20, 20, 20]},
    expected_outputs=[
        {"path": "outputs/vina_out.pdbqt", "kind": "structure", "format": "pdbqt"},
        {"path": "outputs/vina.log", "kind": "log", "format": "txt"},
    ],
)

outputs = ws.fetch_outputs(run)
```

- `workspace_path` 和 `expected_outputs[].path` 都是 workspace-relative logical paths；SDK/result/public projection 不返回真实 HPC path。
- HPC workspace 只是 execution placement workspace，不是 artifact store；canonical truth 仍然是 S08 的 sealed artifact catalog。
- S11 v1 不提供 `fetch_outputs(register=False)` 或其它非登记 fetch 模式；fetch 的产品语义固定是把 declared outputs 经 S08 boundary 登记成 canonical artifact refs。
- runner-backed tool shorthand 从 agent-facing public SDK 和新 docs/examples/prompt 中移除；`hpc` 只保留 placement / remote workspace / declarative stage-fetch namespace。迁移后 public callable 只能是 `structure_tools.fpocket(..., placement=ws)` 或 `docking.vina(..., placement=ws)`。
- 对任何 static route 为 HPC 的领域 operation，executor code 必须显式创建 `hpc.workspace(...)`，显式 `stage_artifact(...)`，传入 `placement=ws`，声明 `expected_outputs`，并通过 `fetch_outputs(...)` 登记 declared outputs；Host 不自动创建隐式 default HPC workspace。
- approval digest 使用领域 operation、HPC placement、stage declarations、source snapshot artifact/digest、input artifact sealed digests、declared outputs、planned fetch intent 和 selected backend。真实 `fetch_refs`、output sealed digest 与 `registered_artifact_ids` 是运行后 provenance，不作为 pre-run approval digest 的已知字段。
- 本 session 可以扩展 S10 generic operation record，但不改变 S10 的 approval/pause/resume 底座语义；最终统一 adapter envelope 由 Session 12 锁定。

## Public SDK v1 Operation Matrix

| Module | v1 operation | Placement | Input style | Output registration |
| --- | --- | --- | --- | --- |
| `bio` | `ncbi_fetch_proteins` / `uniprot_fetch` / `hmmer_search` | Host provider, no `placement` | typed artifact ids / accessions / database params | Host auto-registers provider artifacts and returns bounded artifact refs |
| `bio_tools` | `cdhit` / `mafft` / `hmmbuild` / `hmmalign` | explicit `placement=ws`, static route `hpc` | semantic staged refs such as `input_fasta`, `alignment`, `hmm`, `fasta` | operation returns run handle; `ws.fetch_outputs(run)` registers declared outputs |
| `bio_tools` | `hmmer_search_cli` | public SDK name reserved for offline/HPC route; S14 disabled as `unsupported_in_s14` | semantic staged refs `hmm` and `target_fasta` when later enabled | S14 returns structured disabled failure; current AOX/HMM main route uses `bio.hmmer_search(..., database="refprot")` |
| `structure_tools` | `fpocket` | explicit `placement=ws`, static route `hpc` | semantic staged ref `structure` | operation returns run handle; explicit fetch registers declared outputs |
| `docking` | `vina` | explicit `placement=ws`, static route `hpc` | semantic staged refs `receptor` and `ligand` | operation returns run handle; explicit fetch registers declared outputs |
| `hpc` | `workspace` / `stage_artifact` / `fetch_outputs` | placement namespace only | catalog artifact ids, S08 sealed digests, and workspace-relative paths | fetch calls S08 ArtifactBoundaryService and returns `registered_artifact_ids`, artifact refs and post-run `fetch_refs` |

Sandbox-created intermediate files must first be registered through `artifacts.register(...)` or `artifacts.register_many(...)` before they can be staged to HPC. `stage_artifact(...)` only accepts visible immutable catalog artifact ids, never arbitrary sandbox local paths, Host paths, runner paths, `storage_uri` values, or mutable workspace files. The staged artifact must expose an S08 sealed file `content_digest` or directory `tree_digest`; digest absence is fail-closed and must not fall back to `artifact_id`.

## 接口变化

- 新增或锁定 `hpc` placement-facing 概念字段：
  - `hpc_workspace_id`
  - `placement="hpc"`
  - `stage_refs`
  - `artifact_digest`
  - `workspace_relative_path`
  - `declared_outputs`
  - `fetch_refs`
  - `registered_artifact_ids`
  - `source_snapshot_artifact_id`
  - `source_tree_digest`
- `structure_tools.fpocket(...)`、`docking.vina(...)` 和 static route 为 HPC 的 `bio_tools.*` operation 必须接受 `placement=ws`；当 placement 是 HPC 时，Host 在 S14 通过 runner 实现真实 stage/run/fetch。
- HPC placement operation 返回 opaque run handle，不直接返回 output artifact refs；`run.wait` 保持状态等待；`hpc.Workspace.fetch_outputs(run)` 是声明式 fetch/register 请求，只能取回 approved operation 的 declared outputs。
- `hpc.Workspace.fetch_outputs(...)` 必须把 declared outputs 交给 S08 `ArtifactBoundaryService` 执行 validation、copy/seal、sealed digest recheck 和 immutable Artifact row commit；任一步失败都不得创建 visible artifact。
- `hpc.Workspace.fetch_outputs(...)` 不接受 `register` 参数；任何“只取回但不登记”的 preview/debug 模式都不属于 S11 public SDK v1。
- public docs 不出现 Host path、runner path、SIF path、Slurm/SSH config、database mount 或 credential。
- 缺 prerequisite 时返回结构化 failure，不通过旧 `hpc` shorthand、fixture 或 sibling backend 兜底。

## Resource Identity / Lifecycle

本 session 锁定 `HpcWorkspace`、`StageRef` 和 `FetchRef` 的 logical contract，并明确它们如何接入 S08 artifact boundary；真实 runner upload/run/download 由 Session 14 实现，但 artifact canonicality 仍由 S08 定义。

- `HpcWorkspace`
  - identity：S11 v1 只有 Host 默认 placement profile；`hpc_workspace_id = sandbox_workspace_id + normalized_label`。`hpc.workspace("vina_batch")` 在同一 executor sandbox workspace 内同 label 复用同一个 logical HPC placement workspace。多 cluster / queue / placement profile 不在 S11 设计，后续若引入必须新增 profile 维度。
  - label：label 必须 normalize 为 safe slug；空 label、路径分隔符、绝对路径、`..`、shell metachar 或超长 label 返回 `hpc_workspace_label_invalid`。
  - owner：Host HPC placement service 创建、复用、retire 和投影；executor 只拿 opaque handle。
  - lifecycle：创建/引用发生在 SDK call 时；workspace 可跨多个 approved operation 复用；cleanup/retention 由 Host backend policy 管理，S11 不暴露 close/delete API。
  - persistence：logical workspace id、label、sandbox workspace binding、stage/fetch refs 和 safe summary 持久化；真实 remote path 和 runner workspace id 不是 public/canonical state。
- `StageRef`
  - identity：`stage_ref_id = hpc_workspace_id + artifact_id + artifact_digest + workspace_relative_path`，其中 `artifact_digest` 必须来自 S08 sealed file `content_digest` 或 directory `tree_digest`。
  - owner：Host placement service 创建；executor 只能声明 artifact 和 workspace-relative target path；artifact authorization、sealed digest lookup 和 visible immutable artifact check 由 Host artifact boundary/catalog service 执行。
  - lifecycle：同 digest/path 幂等复用；目标 path 已有不同 digest stage 返回 `hpc_stage_conflict`，不得覆盖。
  - persistence：stage declaration、artifact digest、workspace-relative path、source snapshot binding 和 approval/provenance 绑定持久化；真实上传由 S14 执行。
  - path policy：`workspace_relative_path` 只允许 normalized POSIX relative path；绝对路径、`..`、空 path segment、shell metachar、符号链接逃逸、文件/目录冲突和路径覆盖都返回 `hpc_stage_path_invalid` 或 `hpc_stage_conflict`。
  - fail-closed：artifact 不在当前 session 授权范围、不是 visible immutable Artifact record、缺 sealed digest/tree digest、digest 与 catalog 不一致，或调用方传入 sandbox/Host/runner path 时均结构化失败。
- `FetchRef`
  - identity：`fetch_ref_id = hpc_workspace_id + backend_run_id + declared_output_path + output_digest`，其中 `output_digest` 是 S08 copy/seal 后的 sealed output digest 或 tree digest。
  - owner：Host placement/backend service 创建 fetch declaration；S08 ArtifactBoundaryService 创建 canonical Artifact record；只允许 fetch approved operation 的 declared outputs。
  - lifecycle：重复 fetch 同 run/output 幂等返回已有 artifact refs；未声明输出、路径逃逸、digest mismatch、validation failure、source unstable、seal failure 或 commit failure 均结构化失败。`fetch_ref_id` 在 backend run 完成、declared output 校验和 artifact boundary commit 后生成。
  - persistence：fetch declaration、registered artifact ids、validation result、sealed output digest/tree manifest、source snapshot binding 和 safe log refs 持久化。

固定错误码：

- `hpc_workspace_label_invalid`
- `hpc_workspace_forbidden`
- `hpc_stage_conflict`
- `hpc_stage_path_invalid`
- `hpc_stage_digest_missing`
- `hpc_fetch_not_declared`
- `hpc_fetch_digest_mismatch`
- `hpc_fetch_register_parameter_unsupported`
- S08 artifact boundary errors such as `artifact_digest_mismatch`, `artifact_validation_failed`, `artifact_source_unstable`, `artifact_seal_failed`, `artifact_commit_failed`

## 文档同步要求

- `docs/v3/execution-pipeline-docs/` 必须与本 session 保持同步：
  - SDK overview 的 import surface 和 examples。
  - sandbox rules 中关于 `hpc` 只承载 placement/file-flow 的表述。
  - batch patterns 中迁到 `hpc.workspace + docking.vina` 的示例。
- 稳定架构文档必须保持同一口径：`hpc` 是 placement namespace，领域能力不再通过 runner-backed `hpc` shorthand 暴露；若后续实现再次修改该边界，必须同步更新 `docs/OpenZyme架构设计.md` 和 `docs/v3/` 稳定文档。
- 本 session 只定义 API 和文档口径；真实 runner 上传下载接入由 Session 14 实现。

## 当前实现债 / 完成门槛

S11 不能只以 SDK 名称存在为完成。当前实现若仍存在下列行为，必须视为 S11 未完成：

- `stage_artifact` 用 `metadata.digest`、`artifact_id` 或其它非 S08 sealed digest 兜底生成 `artifact_digest`。S11 完成要求只接受 S08 sealed `content_digest` 或 `tree_digest`；缺失时返回 `hpc_stage_digest_missing`。
- HPC placement operation 在 operation 完成时提前把 output drafts persist 为 visible artifact，并在 public run handle 中暗示 outputs 已登记。S11 完成要求 operation 只返回 opaque run handle；declared output artifact refs 只能由 `fetch_outputs(run)` 产生。
- `fetch_outputs(run)` 只按 `run_id` 查询既有 artifact record，或信任 runner 已给出的 artifact refs。S11 完成要求 fetch 对 approved operation 的 declared outputs 调用 S08 `ArtifactBoundaryService`，完成 validation、copy/seal、sealed digest recheck 和 immutable commit 后才返回 `registered_artifact_ids`。
- fetch 结果缺少 declared output 与 `fetch_ref_id` 的稳定绑定，或重复 fetch 不能幂等返回同一 canonical artifact refs。
- public SDK、docs、examples、prompts 或新测试中仍把 `hpc.fpocket` / `hpc.vina` 作为 callable public SDK，或展示 `fetch_outputs(register=False)` / `register=True` 参数。

## 本轮实现记录

S11 本轮实现只落在 public SDK / Host supervisor logical boundary，不提前接入 S14 的真实 runner upload/download。

- `hpc.stage_artifact` 现在只接受当前 session artifact catalog 中带 S08 sealed `content_digest` / `tree_digest` 的 artifact；缺 digest 返回 `hpc_stage_digest_missing`，StageRef digest 与 catalog 不一致返回 `artifact_digest_mismatch`，同 workspace/path 不同 digest 返回 `hpc_stage_conflict`。
- `bio_tools.*`、`structure_tools.fpocket`、`docking.vina` 的 HPC placement operation 只返回 opaque `hpc_run_handle`，并把 declared output draft 记录为 pending fetch state；operation 完成时不再提前创建 visible artifact，也不在 run handle 中返回 output artifact refs。
- `structure_tools.fpocket` / `docking.vina` 的 S11 compatibility path 不再在 operation completion 阶段主动调用 runner artifact fetch；真实 runner download/staging 留给 S14，S11 fetch 只验证 declared-output 到 artifact-boundary 的事务语义。
- `hpc.fetch_outputs(run)` 只允许 fetch 已记录的 declared outputs，拒绝 `register` 参数；成功路径通过 `ArtifactBoundaryService.register(...)` 完成 validation、copy/seal、sealed digest recheck 和 immutable artifact commit，并返回 `registered_artifact_ids`、artifact refs 与稳定 `fetch_refs`。
- 为兼容旧 `execution.pipeline.start` 测试桥，fetch 时会确保一个 logical sandbox artifact-boundary workspace 和 source snapshot 存在；这只是 S11 的 artifact-boundary 事务支撑，不表示真实 HPC remote workspace 已经实现。
- `ArtifactBoundaryService.register(...)` 支持由 supervisor 透传 `invocation_id` / `run_id`，并允许 `format=fpocket` 目录通过非空目录校验，便于 fetch 后 artifact 与 run/provenance 建立绑定。

本轮 focused 验收：

- `uv run pytest packages/openzyme-engines/tests/test_execution.py -k "stage_artifact_requires or stage_ref_digest_mismatch or no_eager_persist or fetch_outputs_registers_declared"`
- `uv run pytest packages/openzyme-engines/tests/test_execution.py -k "hpc or bio_tool or fetch_outputs or fpocket or vina"`
- `uv run pytest packages/openzyme-engines/tests/test_execution.py`
- `uv run pytest packages/openzyme-core/tests/test_artifact_boundary.py`
- `uv run ruff check packages/openzyme-engines/src/openzyme_engines/execution.py packages/openzyme-engines/tests/test_execution.py packages/openzyme-core/src/openzyme_core/artifact_boundary.py`
- `rg "hpc\.(fpocket|vina)|fetch_outputs\([^\n)]*register\s*=|register\s*[:=]\s*(True|False)" docs/v3 docs/OpenZyme架构设计.md packages/openzyme-pipeline packages/openzyme-engines/tests/test_execution.py`
- `./scripts/check-mainline.sh`

## 推荐实施顺序

这一段是 S11 动工顺序，不是当前完成状态。每一步都应先补 focused failing test，再改实现；只在前一步验收通过后进入下一步，避免把 S12 adapter envelope 或 S14 真实 runner transfer 提前塞进 S11。

1. 先锁定 S11 guardrail 测试：覆盖 `stage_artifact` 缺 sealed digest 返回 `hpc_stage_digest_missing`、跨 session / 非 visible artifact / Host path / sandbox path / runner path / `storage_uri` 失败、HPC domain operation 不再 eager persist visible artifacts、`fetch_outputs(run)` 不能只列既有 run artifacts、`fetch_outputs(register=...)` 失败、未传 explicit placement 的 HPC route operation 失败，以及 public SDK/docs/examples 不再使用 `hpc.fpocket` / `hpc.vina` shorthand。
2. 锁定 public SDK import surface：`openzyme_pipeline.__all__`、SDK docs 和 examples 保持 `artifacts` / `bio` / `bio_tools` / `preprocess` / `structure_tools` / `docking` / `hpc` / `run` 一致；`hpc` 只提供 `workspace`、`Workspace.stage_artifact` 和 `Workspace.fetch_outputs`；`structure_tools.fpocket(...)`、`docking.vina(...)` 和 static HPC route 的 `bio_tools.*` 必须显式接收 `placement=ws` 与 `expected_outputs`。
3. 实现 logical `HpcWorkspace` 边界：`hpc_workspace_id = sandbox_workspace_id + normalized_label`，label/path validation、同 label 幂等复用、安全 projection 和结构化错误先完成；本步骤只创建 logical placement workspace，不创建真实 remote directory，不接触 SSH、SCP、Slurm、runner config 或 remote absolute path。
4. 收紧 `stage_artifact`：只接受当前 session 授权的 visible immutable Artifact record；`artifact_digest` 只能来自 S08 sealed file `content_digest` 或 directory `tree_digest`；缺失、digest mismatch、路径冲突或非法 target path 都 fail-closed；同 digest/path 幂等返回同一 `StageRef`。S11 不做真实上传，真实 staging 由 S14 在相同 declaration 后实现。
5. 收紧 HPC placement operation run handle：`bio_tools.*`、`structure_tools.fpocket` 和 `docking.vina` 在 S11 只记录 approved operation、placement、stage refs、declared outputs、selected backend、resource estimate 和 opaque `run_id`；operation 返回值不得包含 output artifact refs，不得在 operation 完成时提前 persist visible output artifacts，也不得暗示 declared outputs 已经登记。
6. 实现 `fetch_outputs(run)` 的 artifact-boundary 事务语义：只能 fetch approved operation 的 declared outputs；S11 可使用受控 test/dummy output source 验证 S08 `ArtifactBoundaryService` validation、copy/seal、sealed digest recheck 和 immutable commit 流程，但不能接真实 runner upload/download；成功后返回 `registered_artifact_ids`、artifact refs 和稳定 `fetch_refs`，重复 fetch 幂等返回同一 canonical artifact refs。
7. 接入 approval preview / provenance 摘要：operation digest 和 approval summary 必须包含领域 operation、`hpc_workspace_id`、stage refs、source snapshot artifact/digest、input artifact sealed digests、declared outputs、planned fetch intent、selected backend 和 resource estimate；真实 `fetch_refs`、output sealed digest、registered artifact ids 和 backend run id 只作为 post-run provenance。
8. 最后同步稳定文档和回归检查：更新 `docs/v3/execution-pipeline-docs/`、`docs/OpenZyme架构设计.md` 和相关 `docs/v3/` 口径；运行 `rg` 检查旧 shorthand / `register` 参数 / path 泄露，运行 S11 focused tests、相关 execution/pipeline tests、`git diff --check`。若第 1 步列出的任一 blocker 仍存在，S11 只能标记为 in progress，不能标记完成。

## 测试/验收

- public examples 能让 executor 明确看出 operation 发生在 HPC placement，并能显式声明 stage/fetch。
- SDK import surface 与 docs 一致，`hpc` 是 first-class namespace。
- `hpc.workspace(label)` 在同一 `sandbox_workspace_id` 内按 normalized label 复用；非法 label 返回 `hpc_workspace_label_invalid`。
- `stage_artifact` 同 artifact digest/path 幂等复用，路径冲突返回 `hpc_stage_conflict`。
- `stage_artifact` 对缺失 sealed digest、digest mismatch、跨 session artifact、非 visible artifact、sandbox local path、Host path、runner path 或 `storage_uri` 输入都结构化失败。
- `fetch_outputs` 只能取回 approved operation 的 declared outputs，重复 fetch 返回既有 artifact refs。
- `fetch_outputs` 对未声明 output、路径逃逸、digest mismatch 或 ArtifactBoundaryService register 失败不得创建 visible artifact，并透传/归一化 S08 artifact boundary 错误。
- fetch 成功后修改 remote output、sandbox fetched temp 或 runner workdir，不影响已登记 artifact 的 sealed digest 和读取内容。
- Host supervisor 的 operation preview / approval summary 能展示 `hpc_workspace_id`、stage refs、declared outputs、resource estimate、selected backend 和 approval requirements。
- API 不泄露 Host path、BlobStore path、sandbox host path、runner path、remote absolute path、SIF path、SSH/Slurm config、database mount、credential 或 `storage_uri`。
- `rg` 检查 public SDK/docs/examples/prompts/new tests 后，不得再出现 runner-backed `hpc` tool shorthand 作为 callable public SDK；旧实现残留必须被移除。
- `rg` 检查 S11 和 sessions README，不得把 fetch/register 描述成直接写 artifact record 或直接信任 runner output。
- static route 为 HPC 的领域 operation 未传 explicit placement 时返回 `hpc_workspace_forbidden` 或 typed validation error，不能自动创建 default remote workspace。

## 明确不做什么

- 不在 Session 11 实现真实 HPC runner staging/fetch。
- 不把 `fpocket`、`vina`、MAFFT/CD-HIT/HMMER 统一塞进一个 backend API。
- 不让 executor 写 SSH、SCP、Slurm、rsync 或真实 remote path。
- 不允许 scheduler 根据 backend 可用性自动重写 placement 或 fallback。
