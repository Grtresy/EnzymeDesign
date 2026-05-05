# Session 09: Execution Engine

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, docs retrieval, context compaction, approval protocols, and canonical control-plane projections. Skill loading is frozen in V3 until explicitly reapproved. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

将 HPC execution 改造成 V3 capability engine，并统一接入 harness approval protocol。审批触发点应在 SDK operation policy / Host supervisor，而不是要求 master 或 executor 预先判断某次 execution 是否敏感。

本轮还必须把 execution 从固定 preprocess + 单次 runner tool call 的模型改成
受控 pipeline sandbox。executor 可以写 Python pipeline 判断是否需要 preprocess、
批量处理输入并发起 HPC step，但不能直接调用 runner tool、SSH、Slurm 或任意 Host
文件路径。

所有 HPC step 仍必须由 Host supervisor 通过 tool contract 编译为明确的
`RunSpec.inputs`。所有需要回到 workspace 的结果都必须由 `expected_outputs`
声明并经 runner 下载后登记为新的 session artifact。

## 参考

- `docs/v3/03-capability-engines.md`
- `/home/grtresy/VSCodeRepo/EnzymeDesign/apps/mcp-hpc-runner/`

## 本轮允许改动

- execution runtime seams
- execution engine contract
- run / artifact persistence
- approval integration
- artifact-to-RunSpec staging contract
- tool-contract backed request compiler
- execution pipeline sandbox
- sandbox SDK / Host supervisor boundary
- preprocess capability boundary inside pipeline

## 本轮禁止事项

- 不新建 execution phase 作为产品主语义
- 不回到 graph-native approval-only 语义
- 不改 Web UI / CLI
- 不允许 execution 编译器把 Host 本地 artifact path 当作 HPC 远端可读路径
- 不允许任意本地路径绕过 session artifact 校验进入 runner staging
- 不允许 executor 直接 tool call `exec.run` / `job.submit` / runner status 或 fetch tools
- 不允许 pipeline sandbox 直接持有 SSH key、Slurm config、runner config、数据库连接或 Host repo 路径

## 完成产物

- execution pipeline engine API
- execution invocation persistence
- harness-managed approval path backed by SDK operation policy
- pipeline submit / status / internal supervisor resume / result parse
- canonical run / artifact updates
- `SessionArtifactRecord -> RunSpec.inputs` 映射规则
- `RunSpec.expected_outputs -> SessionArtifactRecord` 回填规则
- pipeline sandbox SDK 与 Host supervisor 边界
- preprocess-in-pipeline 的最小能力边界

## 文件与 artifact 数据流

V3 execution 的标准路径如下：

```text
session artifact catalog
  -> resolve required_artifact_ids / context_artifact_ids
  -> dry-run / validation builds ExecutionPlan
       plan_digest
       artifact reads, HPC operation list, expected outputs
       resource / quota estimate, doc hints, approval requirements
  -> if plan has gated hpc.* operations, create ApprovalRequest for the plan
  -> user approves plan through POST /v3/approvals/{approval_id}/resolve
  -> sandbox materializes authorized inputs under /openzyme/input
  -> executor-authored pipeline code runs in rootless Podman
  -> pipeline uses openzyme_pipeline SDK
       artifacts.* for authorized artifact reads/writes
       preprocess.* for local format preparation
       hpc.* for supervised HPC steps
  -> Host supervisor handles each hpc.* request
       verify request is covered by approved ExecutionPlan
       SDK operation policy / secondary approval / quota / artifact validation
       uncovered operation creates ApprovalRequest and blocks this SDK step
       tool contract compiler emits RunSpec
       command: remote /work and /out paths only
       inputs: trusted artifact storage_uri -> remote /work paths
       expected_outputs: remote /out relative paths
  -> mcp-hpc-runner stages inputs by rsync/scp
  -> ssh or sbatch executes command on HPC
  -> mcp-hpc-runner fetches declared expected_outputs
  -> Host supervisor normalizes local fetched files
  -> control plane saves SessionArtifactRecord rows
  -> workspace projection exposes pipeline + run + artifacts
```

约束：

- `SessionArtifactRecord.storage_uri` 是 Host/control-plane 侧资产位置，不自动等于 HPC 可读路径。
- pipeline code 不能直接读取 `SessionArtifactRecord.storage_uri`；SDK 只暴露授权 artifact 的 sandbox 视图。
- Host supervisor 必须为每个需要上传的 artifact 生成 `RunSpec.inputs[]`，并把 command 改写为远端 `/work/...` 或 `$MCP_WORKDIR/...` 路径。
- runner 只负责按 `RunSpec.inputs` 上传和按 `expected_outputs` 下载；它不推断 workspace artifact，也不扫描远端目录。
- Host supervisor 回填 artifact 时必须保留输出相对路径层级，不能只取 basename，否则多目录输出会冲突。
- artifact 记录必须回链到 `session_id`、`task_id`、`lane_id`、`engine_invocation` 和 `run_id`。
- pipeline invocation 还必须记录 code digest、SDK operation log、sandbox status、HPC run ids 与 created artifact ids。
- dry run 是校验过程，`ExecutionPlan` 是可审批结果；`dry_run=true` 只返回 plan，不创建 approval、不启动 sandbox、不提交 HPC。
- `dry_run=false` 也必须先持久化 `ExecutionPlan`；若 plan 包含 gated `hpc.*` operation，invocation 进入 `waiting_approval`，approval 绑定 `plan_digest`、HPC operation list、artifact reads、expected outputs 与 resource / quota estimate。
- 用户 approve plan 后才允许正式 sandbox 执行；正式执行中若出现未被 approved plan 覆盖的 `hpc.*` operation、artifact id 或参数 / quota 范围，runtime SDK call 必须触发 secondary approval gate，不得提交 HPC。

## Pipeline Sandbox Baseline

execution teammate 默认不直接调用 runner tool。它提交 pipeline code 给 execution
pipeline engine，由 engine 在隔离环境中运行。

executor prompt 只应给最小 authoring 框架和检索关键词，不应内嵌完整 SDK reference。
executor 需要用法细节时，应调用 `docs.search` / `docs.read` 读取
`docs/v3/execution-pipeline-docs/` 中的文档。

默认 authoring flow：

```text
restore task + artifact catalog
  -> docs.search for needed SDK/API details
  -> docs.read selected references/examples
  -> write pipeline code
  -> execution.pipeline dry-run validates SDK use, artifact access, quota and outputs
  -> fix code from structured feedback or request approval
```

最小 prompt 关键词：

- `pipeline`
- `artifact read/register`
- `preprocess prepare_receptor prepare_ligand`
- `hpc.vina`
- `hpc.fpocket`
- `batch ligand docking`
- `sandbox rules`
- `dry-run`

默认 sandbox：

```text
/openzyme/input    authorized artifacts, read-only
/openzyme/work     temporary pipeline workspace, read-write
/openzyme/output   candidate outputs, read-write
/openzyme/logs     stdout/stderr and SDK operation logs
/openzyme/control.sock  per-invocation Unix domain socket
```

隔离要求：

- 默认使用 rootless Podman，非 root 用户、无网络、资源受限、清空非白名单环境变量。
- 不挂载 Host repo、用户 home、`.ssh`、runner config、数据库或任意通用 Host 目录。
- `/openzyme/input` 只读；`/openzyme/work` 和 `/openzyme/output` 是本 invocation 私有目录。
- 容器内没有 HPC 凭证；HPC 请求只能通过 `/openzyme/control.sock` 发给 Host supervisor。
- Python 层禁用危险 import 只能作为辅助；真实安全边界必须来自容器、mount、用户、网络和资源限制。

`openzyme_pipeline` SDK 概念接口：

```python
from openzyme_pipeline import artifacts, preprocess, hpc

receptor = artifacts.get("art_receptor")
ligand = artifacts.get("art_ligand")

if receptor.format != "pdbqt":
    receptor = preprocess.prepare_receptor(receptor)

if ligand.format != "pdbqt":
    ligand = preprocess.prepare_ligand(ligand)

run = hpc.vina(
    receptor=receptor,
    ligand=ligand,
    center=(0, 0, 0),
    size=(10, 10, 10),
    exhaustiveness=8,
)

result = run.wait()
poses = run.fetch_artifacts()
artifacts.register_many(poses)
```

SDK 规则：

- `artifacts.get` 只能读取当前 session/task/lane 授权 artifact。
- executor 必须在 `execution.pipeline.start.inputs.artifact_ids` 或 `context_artifact_ids` 中显式声明 pipeline code 会读取的 artifact；dry-run / validation 发现 `artifacts.get("...")` 未声明时，应返回结构化 tool failure 给 LLM 修正并重试，而不是 Host 自动补全授权。
- `artifacts.register` 只能登记 `/openzyme/output` 下的文件或 SDK 返回的 fetched outputs。
- `preprocess.*` 只能读授权 artifact 或 sandbox 内文件，并且输出必须登记为 session artifact 后才能被 `hpc.*` 消费。
- `hpc.*` 不能在容器内执行 SSH/Slurm；它只向 Host supervisor 发 JSON-RPC 请求。
- 每个 `hpc.*` 请求必须带 input artifact refs、params、expected outputs 和 pipeline step id。
- Host supervisor 必须基于 SDK operation policy 判断 approval 需求；耗时久、计算量大、会提交 HPC job 或高 quota 消耗的 operation 默认应 approval-gated。
- Host supervisor 默认在执行前为 approval-gated operations 创建 plan-level canonical `ApprovalRequest`，并通过 `approval.requested` / workspace projection 交给 Web UI 展示；pipeline sandbox 只有在 approved plan 未覆盖 runtime SDK call 时，才在该 SDK call 边界触发 secondary approval gate。
- `POST /v3/approvals/{approval_id}/resolve` resolve 后，runtime signal 唤醒对应 supervisor / resident teammate 继续 pending SDK step；任何内部 resume API 都只能消费已 resolved 的 approval，不能作为批准入口。
- Host supervisor 必须支持 dry-run / plan，列出预计 artifact 读写、HPC jobs、资源、输出和按 policy 推断的 approval 需求。
- dry-run 错误必须包含可执行修正提示和相关文档关键词或 doc id。例如非 PDBQT ligand 传给 `hpc.vina` 时，应提示查询 `preprocess.prepare_ligand` 或 `hpc-vina.md`。

## RunSpec 目标契约

每个 `hpc.*` SDK 调用最终生成的 RunSpec 形状至少包含：

```text
name
stage
command[]
execution_mode
resources
inputs[]
expected_outputs[]
success_checks[]
failure_signatures[]
metadata
```

`inputs[]` 最小字段：

- `artifact_id`：来源 session artifact id，供审计与错误定位
- `local_path`：来源 artifact 的可信本地 `storage_uri`
- `remote_path`：相对 `/work` 或 `/out` 的目标路径
- `stage_to`：默认 `work`

`expected_outputs[]` 最小字段：

- `path`：相对 `/out` 的路径，必须保留目录层级
- `kind`：`file` 或 `dir`
- `required`
- `non_empty`

安全边界：

- `inputs.local_path` 只能来自当前 session 已解析 artifact、pipeline 登记 artifact 或 runner fetched artifact。
- 用户、LLM、executor pipeline code 或上层 handoff 不得直接提交任意 Host 文件路径作为 runner input。
- `expected_outputs.path` 必须是相对路径，不能包含绝对路径或逃逸片段。
- 未声明的远端输出不会自动进入 workspace artifact catalog。
- RunSpec metadata 必须包含 pipeline invocation id、pipeline code digest、step id、tool contract id、input artifact ids 与 output artifact expectations。

## Tool Contract Compiler

Host supervisor 不应长期维护不断膨胀的 `if tool_id == ...` 手写命令分支。
`hpc.*` SDK 函数的目标形态是 catalog/tool contract 驱动的 compiler：

- 读取 tool contract 的 required inputs、optional params、resources、expected outputs、failure signatures 与 parser hints。
- 将 `required_artifact_ids` 与 tool input slots 绑定，生成多个 `RunSpec.inputs`。
- 将 command 组装为远端路径语义；container/SIF 工具使用 `/work`、`/out`、`/tmp` bind 后的路径。
- 将 `expected_outputs` 原样转成 runner 可下载、可校验的声明。
- 将 parser hints 写入 metadata，供 result parser 解析 fpocket、vina 等工具产物。

首批必须覆盖：

- `fpocket`：单个 PDB 结构输入，输出 pocket 目录。
- `vina`：receptor PDBQT、ligand PDBQT、box 参数，输出 docking pose 与 log。

后续工具必须先补 tool contract，再接入 compiler；不能只新增一段 command 拼接逻辑。

## Preprocess In Pipeline

预处理是 V3 execution pipeline 的基线能力，不是固定写死在 compiler 里的 tool-specific
adapter。executor 在 pipeline code 中判断工具输入格式是否满足 contract，并通过
`preprocess.*` SDK 显式生成新的可信 session artifact，再交给 `hpc.*` step。

最小 preprocess 能力：

- `convert_format`：CIF/PDB/SDF/MOL2/PDBQT 等格式转换。
- `prepare_receptor`：PDB 等 receptor 输入转 Vina 兼容 PDBQT。
- `prepare_ligand`：SDF/MOL2 或 SMILES 转 Vina 兼容 PDBQT。
- `smiles_to_3d`：SMILES 生成三维 ligand 中间结构。

规则：

- preprocess 输出必须登记为 session artifact，带来源 artifact、tool、format 与 provenance。
- `hpc.vina` 不得假设 PDB/SDF/SMILES 可直接被 Vina 读取；SDK 或 Host supervisor 必须拒绝非 PDBQT receptor/ligand，除非 pipeline 已先生成 PDBQT artifact。
- preprocess 可先在 sandbox 本地执行；未来如需 HPC obabel/meeko 路径，应作为新的 `hpc.*` tool contract 接入，而不是让 preprocess backend 感知 SSH/Slurm。
- pipeline 可以批量 preprocess 多个 ligand，但必须受 approval、quota、timeout 和 output size 限制。

## 验收标准

- 审批从 control plane 发起和恢复
- run / artifact 可关联到 session / task / lane
- 同一 task 的多次 execution invocation 可区分、可恢复
- execution 结果可回到 report draft / workspace projection
- executor 只能通过 `execution.pipeline.*` 提交或恢复 pipeline，不能直接调用 runner tools
- pipeline sandbox 不能读取 Host repo、home、`.ssh`、数据库、runner config 或任意未授权 path
- `hpc.fpocket` request 使用 staged PDB 输入，而不是 Host 本地路径参数
- `hpc.vina` request 支持 receptor + ligand 多输入 staging，并声明 `vina_out.pdbqt` 与 `vina.log`
- PDB/SDF/SMILES 到 PDBQT 的 pipeline preprocess 能形成新的 session artifact 并被 HPC step 消费
- pipeline 批处理多个 ligand 时，每个 HPC run、RunSpec、输出 artifact 与 pipeline step 都可追踪
- 输出 artifact 注册保留相对路径层级，避免同名文件冲突
- 非当前 session artifact、任意本地路径、未声明远端输出都不能静默进入 execution artifact catalog

## 建议验证

- `uv run pytest -m "not integration" apps/mcp-hpc-runner packages/openzyme-engines packages/openzyme-core apps/openzyme-host-api`
- 新增针对 pipeline sandbox 的单元测试：授权 input 映射、未授权路径拒绝、output 注册边界、code digest 记录
- 新增针对 Host supervisor 的单元测试：`hpc.fpocket` / `hpc.vina` SDK 请求编译成 RunSpec、artifact staging、多输入 Vina、expected output 回填、路径逃逸拒绝
- 新增 preprocess-in-pipeline 流程测试：PDB/SDF 或 SMILES 先生成 PDBQT artifact，再由 `hpc.vina` 编译 RunSpec
- 新增 adapter 测试：runner 返回嵌套输出路径时，SessionArtifact `relative_path` 保留目录层级
- 新增 quota / approval 测试：批处理 pipeline 不能在未批准或超 quota 时提交多个 HPC jobs

## 交接给下一轮

- Session 10 汇总 research / execution / artifacts 成 report draft 与统一工作区叙事
- Session 11 的 workspace/API/UI 只消费 control-plane artifact projection，不直接读取 runner artifact 目录
