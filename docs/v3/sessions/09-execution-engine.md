# Session 09: Execution Engine

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, skill loading, context compaction, approval protocols, and canonical control-plane projections. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

将 HPC execution 改造成 V3 capability engine，并统一接入 harness approval protocol。

本轮还必须把 execution 的文件语义补齐：V3 execution 不能继续依赖“把本地
`storage_uri` 直接塞进远端 command 参数”的隐式路径。所有需要送到 HPC 的
session artifact 都必须被编译成明确的 `RunSpec.inputs`，所有需要回到
workspace 的结果都必须由 `expected_outputs` 声明并经 runner 下载后登记为新的
session artifact。

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
- preprocess capability boundary for execution inputs

## 本轮禁止事项

- 不新建 execution phase 作为产品主语义
- 不回到 graph-native approval-only 语义
- 不改 Web UI / CLI
- 不允许 execution 编译器把 Host 本地 artifact path 当作 HPC 远端可读路径
- 不允许任意本地路径绕过 session artifact 校验进入 runner staging

## 完成产物

- execution engine API
- execution invocation persistence
- harness-managed approval path
- request compile / submit / parse result
- canonical run / artifact updates
- `SessionArtifactRecord -> RunSpec.inputs` 映射规则
- `RunSpec.expected_outputs -> SessionArtifactRecord` 回填规则
- preprocess-before-execution 的最小能力边界

## 文件与 artifact 数据流

V3 execution 的标准路径如下：

```text
session artifact catalog
  -> resolve required_artifact_ids / context_artifact_ids
  -> optional preprocess produces new trusted session artifacts
  -> tool contract compiler emits RunSpec
       command: remote /work and /out paths only
       inputs: local session artifact storage_uri -> remote /work paths
       expected_outputs: remote /out relative paths
  -> mcp-hpc-runner stages inputs by rsync/scp
  -> ssh or sbatch executes command on HPC
  -> mcp-hpc-runner fetches declared expected_outputs
  -> execution adapter normalizes local fetched files
  -> control plane saves SessionArtifactRecord rows
  -> workspace projection exposes run + artifacts
```

约束：

- `SessionArtifactRecord.storage_uri` 是 Host/control-plane 侧资产位置，不自动等于 HPC 可读路径。
- compiler 必须为每个需要上传的 artifact 生成 `RunSpec.inputs[]`，并把 command 改写为远端 `/work/...` 或 `$MCP_WORKDIR/...` 路径。
- runner 只负责按 `RunSpec.inputs` 上传和按 `expected_outputs` 下载；它不推断 workspace artifact，也不扫描远端目录。
- execution adapter 回填 artifact 时必须保留输出相对路径层级，不能只取 basename，否则多目录输出会冲突。
- artifact 记录必须回链到 `session_id`、`task_id`、`lane_id`、`engine_invocation` 和 `run_id`。

## RunSpec 目标契约

V3 execution request 的目标 RunSpec 形状至少包含：

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

- `inputs.local_path` 只能来自当前 session 已解析 artifact 或同一 execution 前置 preprocess 产物。
- 用户、LLM 或上层 handoff 不得直接提交任意 Host 文件路径作为 runner input。
- `expected_outputs.path` 必须是相对路径，不能包含绝对路径或逃逸片段。
- 未声明的远端输出不会自动进入 workspace artifact catalog。

## Tool Contract Compiler

execution engine 不应长期维护不断膨胀的 `if tool_id == ...` 手写命令分支。
目标形态是 catalog/tool contract 驱动的 compiler：

- 读取 tool contract 的 required inputs、optional params、resources、expected outputs、failure signatures 与 parser hints。
- 将 `required_artifact_ids` 与 tool input slots 绑定，生成多个 `RunSpec.inputs`。
- 将 command 组装为远端路径语义；container/SIF 工具使用 `/work`、`/out`、`/tmp` bind 后的路径。
- 将 `expected_outputs` 原样转成 runner 可下载、可校验的声明。
- 将 parser hints 写入 metadata，供 result parser 解析 fpocket、vina 等工具产物。

首批必须覆盖：

- `fpocket`：单个 PDB 结构输入，输出 pocket 目录。
- `vina`：receptor PDBQT、ligand PDBQT、box 参数，输出 docking pose 与 log。

后续工具必须先补 tool contract，再接入 compiler；不能只新增一段 command 拼接逻辑。

## Preprocess Baseline

预处理是 V3 execution 的基线能力，不是可选备注。compiler 在发现工具输入格式不满足
contract 时，必须能够请求或编排 preprocess step，并把 preprocess 输出作为新的可信
session artifact 再交给 HPC execution。

最小 preprocess 能力：

- `convert_format`：CIF/PDB/SDF/MOL2/PDBQT 等格式转换。
- `prepare_receptor`：PDB 等 receptor 输入转 Vina 兼容 PDBQT。
- `prepare_ligand`：SDF/MOL2 或 SMILES 转 Vina 兼容 PDBQT。
- `smiles_to_3d`：SMILES 生成三维 ligand 中间结构。

规则：

- preprocess 输出必须登记为 session artifact，带来源 artifact、tool、format 与 provenance。
- Vina compiler 不得假设 PDB/SDF/SMILES 可直接被 Vina 读取；必须显式生成或要求 PDBQT。
- preprocess 可先本地执行；未来如需 HPC obabel/meeko 路径，应作为新的 tool contract 接入，而不是让 preprocess backend 感知 SSH/Slurm。

## 验收标准

- 审批从 control plane 发起和恢复
- run / artifact 可关联到 session / task / lane
- 同一 task 的多次 execution invocation 可区分、可恢复
- execution 结果可回到 report draft / workspace projection
- fpocket request 使用 staged PDB 输入，而不是 Host 本地路径参数
- vina request 支持 receptor + ligand 多输入 staging，并声明 `vina_out.pdbqt` 与 `vina.log`
- PDB/SDF/SMILES 到 PDBQT 的前置转换能形成新的 session artifact 并被 execution 消费
- 输出 artifact 注册保留相对路径层级，避免同名文件冲突
- 非当前 session artifact、任意本地路径、未声明远端输出都不能静默进入 execution artifact catalog

## 建议验证

- `uv run pytest -m "not integration" apps/mcp-hpc-runner packages/openzyme-engines packages/openzyme-core apps/openzyme-host-api`
- 新增针对 execution compiler 的单元测试：artifact staging、多输入 Vina、expected output 回填、路径逃逸拒绝
- 新增 preprocess-to-execution 流程测试：PDB/SDF 或 SMILES 先生成 PDBQT artifact，再编译 Vina RunSpec
- 新增 adapter 测试：runner 返回嵌套输出路径时，SessionArtifact `relative_path` 保留目录层级

## 交接给下一轮

- Session 10 汇总 research / execution / artifacts 成 report draft 与统一工作区叙事
- Session 11 的 workspace/API/UI 只消费 control-plane artifact projection，不直接读取 runner artifact 目录
