# OpenZyme V3 Capability Engines

## 1. 定位

Capability engine 是 V3 harness 可调用的专业子系统。

它们的共同约束：

- 对外暴露稳定输入输出
- 不拥有产品顶层真状态
- 可以有自己的局部执行图、局部 prompt、局部 tool loop
- 结果必须回写到 control plane canonical objects
- 启动、恢复、重试与并发由 `engine invocation` 统一标识
- provider/tool 调用必须经过 limiter：agent/session/global concurrency、LLM provider、research provider、execution/HPC submission 分别表达
- 同步 SDK 只能通过受控 `to_thread` 或等价 adapter 包装在 limiter 内运行；线程池大小不是 quota 或 agent 并发策略

## 2. Deep Research Engine

### 2.1 默认定位

`deep_research` 是 V3 的首个重点 capability engine。

默认实现形态：

- 用 `LangGraph` 承担 engine 内部控制流与状态推进
- 用 `LangChain` 承担 model、tool、prompt、structured output 与 provider adapter 组装
- 作为 harness / teammate loop 可调用的专业能力存在，而不是顶层产品 orchestrator

默认参考：

- `/home/grtresy/VSCodeRepo/26/open_deep_research/src/open_deep_research/deep_researcher.py`
- `/home/grtresy/VSCodeRepo/26/open_deep_research/src/open_deep_research/state.py`
- `/home/grtresy/VSCodeRepo/26/open_deep_research/src/open_deep_research/configuration.py`
- `/home/grtresy/VSCodeRepo/26/open_deep_research/docs/deep_researcher_graph_详解.md`

### 2.2 推荐吸收的模式

- `clarify -> write_research_brief -> supervisor -> parallel researchers -> synthesis`
- 研究 brief 与 researcher context 分离
- researcher 子过程并行执行
- compression / synthesis 作为单独内部阶段
- 输出 normalized evidence dossier，而不是随意文本

对 enzyme design 的默认扩展：

- 保留上述通用 deep research 骨架
- 额外叠加 enzyme-design-aware prompt overlay
- 在 tool / provider 层接入生物 research 来源，而不是把领域逻辑硬编码进 harness
- 让 sequence / structure retrieval 可以作为 research 内部动作之一，但仍通过 canonical artifact / evidence 回填对外暴露

### 2.3 Research Teammate 与 Deep Research 的边界

`research teammate` 与 `deep_research` 不是同一层对象。

- `research teammate` 是 harness / protocol 语义中的 worker，围绕明确 `task_id` 读取 workspace、选择工具、与 peers 沟通并向用户路径回填结果
- `deep_research` 是 teammate 可调用的一种重能力 engine，适合多步拆解、并行检索、跨来源综合与 dossier synthesis
- `deep_research` 内部的 supervisor / researcher workers 只是 engine 内部 LangGraph 子过程，不等于产品级 teammate

默认策略：

- 简单事实查询、已知 accession / PDB id 的确定性抓取、轻量 annotation 查询，不要求先进入 `deep_research`
- 开放式 literature review、query decomposition、跨 provider 证据融合、gap detection、clarification，优先走 `deep_research`

### 2.4 不应直接照搬的部分

- 让 deep_researcher graph 直接变成整个 OpenZyme 的顶层产品架构
- 让 open_deep_research 的内部 state 直接暴露给 V3 UI
- 让 research session 替代 V3 的 session / task / lane control plane
- 让所有 research teammate 行为都被强制折叠进 `deep_research`

### 2.5 生物 Provider 与 Prompt 分层

V3 deep research 默认面向 enzyme design 接入一组受控 bio provider baseline：

- `PubMed`
- `Semantic Scholar`
- `UniProt`
- `RCSB PDB`
- `InterPro`

推荐分层：

- 通用 deep research prompts：clarify、briefing、supervision、research execution、synthesis
- enzyme design overlay prompts：文献可信度、酶家族/底物/结构语义、序列与结构检索启发式、引用与证据规范
- provider adapters：把 literature、sequence、structure、annotation 来源统一转换为 engine 可消费的工具结果与 canonical evidence payload

这些 provider adapter 应尽量同时服务两类调用面：

- `deep_research` 内部 tool loop
- `research teammate` 的 direct provider actions

provider adapter 的统一边界应是轻量 `ResearchObservation`，而不是 provider-specific raw response。

概念形状：

- `status`：`completed` / `partial` / `failed`
- `summary`：供 LLM 直接阅读的一句话或短段摘要
- `findings`：结构化 evidence candidates，每项包含 `summary`、`query`、`confidence_label`、`sources`
- `unresolved_gaps`：仍需补证或澄清的问题
- `artifacts`：真实下载或生成的 workspace asset manifest
- `provider`：来源 provider 标识
- `raw_ref`：可选调试引用，不默认进入长期 prompt / read model

其中 `sources` 表示 evidence 的可追溯来源，如 paper、web page、dataset locator；`artifacts` 只表示实际 materialized 的 sequence、structure、report、result 等文件资产。普通 search hit 不应被伪装成 artifact。

两类调用面的包装不同，但 research payload 应保持一致：

- `deep_research` 内部 tool loop 使用 `ResearchObservation` 作为 `ResearchToolResult.payload`
- `research teammate` direct provider actions 使用同一 `ResearchObservation` JSON 作为 `ToolResult.content`
- provider raw response 只作为调试数据通过 `raw_ref` 或 engine document 追踪，不作为 canonical evidence schema

### 2.6 V3 外部接口

deep research 对 harness 至少提供：

- `start_research(invocation_id, task_id, brief)`
- `resume_research(invocation_id, resolution)`
- `get_research_status(invocation_id)`
- `get_research_dossier(invocation_id)`

输出至少包含：

- `summary`
- `evidence_items`
- `source_refs`
- `unresolved_gaps`

可选调试产物：

- `raw_notes`
- `research_turns`

对 enzyme design 的补充输出约束：

- 当 research 过程中下载 sequence / structure 文件时，engine 应返回足够的 artifact metadata，使 control plane 可以将其持久化为 workspace artifact
- dossier 可以引用这些 artifact，但 artifact 本身不应只作为 engine 内部临时文件存在

要求：

- 同一 `task_id` 允许存在多个 research invocation
- engine 内部 graph/checkpoint 只能作为 invocation 局部运行态
- 对 harness 可恢复的状态必须回写 `engine_invocation + evidence artifacts`
- search / lookup 类 observation 应能规范化为 canonical evidence 与 source refs
- download 类 observation 应能规范化为 workspace artifacts，并可附带 evidence/source provenance

## 3. Execution Engine

定位：

- 负责将某项 task 或 artifact 集合转化为可执行请求
- 继续复用 `apps/mcp-hpc-runner` 作为外部执行边界
- 负责运行 executor 提交的受控 execution pipeline code
- 负责把 pipeline 内的 HPC SDK 调用显式编译成 runner `RunSpec.inputs`
- 负责把 runner 下载后的 declared outputs 回填为 canonical workspace artifacts

要求：

- 对 harness 至少提供 `execution.pipeline.start(invocation_id, task_id, code, inputs)`、`execution.pipeline.status(invocation_id)`；恢复等待中的 pipeline 是 harness / supervisor 内部调度语义，不是 executor 或 master 需要显式编排的用户级 tool contract
- executor 不得直接调用 runner tool、SSH、Slurm 或 runner config；它只能提交 pipeline code，并通过 sandbox 内注入的 SDK 间接请求 HPC
- 敏感性由 SDK operation policy / Host supervisor 判定，而不是由 master 或 executor 判断；例如耗时、计算量大、会提交 HPC job 或高 quota 消耗的 `hpc.*` operation 必须标记为 approval-gated
- `execution.pipeline.start` 的默认主路径是 dry-run / validation first：Host supervisor 先构建 `ExecutionPlan`，再让用户批准该 plan；批准前不得提交 HPC job，也不得启动会触发 HPC 的正式执行
- dry run 是校验过程，`ExecutionPlan` 是结果；plan 至少绑定 `plan_digest`、artifact reads、preprocess operations、HPC operation list、expected outputs、resource / quota estimate、doc hints 与 approval requirements
- approval 绑定 `plan_digest` 和 HPC operation list；用户 approve 后，Host supervisor 才启动正式 sandbox 执行
- runtime SDK call approval gate 只作为兜底：正式执行时若出现未被 approved plan 覆盖的 `hpc.*` operation、artifact id 或参数 / quota 范围，Host supervisor 必须再次创建 `ApprovalRequest` 并进入 `waiting_approval`，不得提交该 HPC operation
- approval 由 harness/API 统一 resolve；`POST /v3/approvals/{approval_id}/resolve` 是唯一改变 approval 状态的外部入口
- execution engine、pipeline SDK 与 supervisor 都不代表用户批准；pending approval 下，对应 SDK step / engine invocation 必须保持 `waiting_approval`，直到 resolved approval 通过 runtime signal 唤醒并继续
- Host-supervised pipeline completion 是 engine/workspace event，不是用户最终答复；approval resolved 后无论 pipeline `succeeded`、`failed` 还是 `cancelled`，Host 都应把原 executor 唤醒，由 executor 读取 `execution.pipeline.status`、artifacts 和 structured error 后生成用户可见收尾
- 成功时 executor 必须总结工具级结果和 output artifacts，例如 fpocket pocket count / artifact ids；失败时 executor 根据 `pipeline.error` 决定 materially changed retry，或用 `task.update(status="failed", failure_summary, failure_ref)` 写入 canonical 失败状态
- execution / HPC retry 与失败诊断策略属于 executor prompt、受控 docs 或 tool result hints；runtime wakeup instruction 只应携带 invocation/status/artifact/error evidence，不应规定重试或修复策略
- 执行结果必须回填 `run`、`artifact`
- 结果必须能对 report draft / workspace UI 统一投影
- command 不得直接引用 Host 本地 `SessionArtifactRecord.storage_uri`；HPC command 只能引用 `/work`、`/out`、`$MCP_WORKDIR`、`$MCP_OUTDIR` 等远端路径
- runner/HPC 不得直接使用 Host 本地 artifact path；所有输入必须先经 artifact catalog 授权，再通过 runner staging 映射为远端工作目录路径
- 多输入工具必须通过多个 `RunSpec.inputs` 明确 staging，例如 Vina 的 receptor 与 ligand
- 远端结果只有在 `expected_outputs` 中声明后才会被下载并登记为 artifact
- output artifact 必须保留相对路径层级，不能只保留 basename

### 3.1 Execution Pipeline Sandbox

execution engine 的目标入口是 pipeline sandbox，而不是固定 tool-specific preprocess
adapter。executor 可以写 Python pipeline 表达判断、循环、批处理和分支，但 pipeline
只能在受控运行时内执行。

默认运行边界：

- pipeline code 运行在 rootless Podman sandbox 中，默认无网络、非 root、资源受限
- sandbox 只挂载当前 invocation 的 `/openzyme/input`、`/openzyme/work`、`/openzyme/output` 和 per-invocation control socket
- `/openzyme/input` 只读，且只包含已授权 session artifacts 的副本或受控映射
- `/openzyme/work` 与 `/openzyme/output` 可写；只有 SDK 明确登记的 `/openzyme/output` 文件可进入 artifact catalog
- Host repo、用户 home、`.ssh`、数据库、runner config 和 HPC credentials 不得挂载进 sandbox
- sandbox 内代码不能直接访问网络、SSH、Slurm 或 runner；HPC 请求只能通过 `openzyme_pipeline.hpc` 走 Unix domain socket 到 Host supervisor

`openzyme_pipeline` SDK 至少提供概念能力：

- `artifacts.get(artifact_id)`：读取授权 artifact 的 sandbox 视图
- `execution.pipeline.start.inputs.artifact_ids` / `context_artifact_ids` 必须显式列出 pipeline code 将读取的 artifact；Host dry-run 发现未声明的字面量 `artifacts.get("...")` 时返回可修复 tool failure，让 executor 重新调用
- `artifacts.register(path, kind, format, metadata)`：登记 pipeline output artifact
- `preprocess.convert_format(...)`
- `preprocess.prepare_receptor(...)`
- `preprocess.prepare_ligand(...)`
- `preprocess.smiles_to_3d(...)`
- `hpc.fpocket(...)`
- `hpc.vina(...)`
- `run.wait()` 与 `run.fetch_artifacts()`

Host supervisor 负责：

- 校验 pipeline 是否只能读取当前 session/task/lane 授权 artifact
- 执行 dry-run / plan，列出预计 artifact 读写、HPC jobs、资源与输出
- 执行 SDK operation policy、approval gate、quota、timeout、输出大小限制和失败分类
- 对 approval-gated SDK operation 创建 canonical `ApprovalRequest`，并把 pending operation 与 session/task/lane/invocation/step id 关联，供 Web UI 通过 workspace projection 展示 approval card
- 把每个 `hpc.*` 调用转换为 tool contract compiler 输入
- 调用 `apps/mcp-hpc-runner`，并把 fetched outputs 登记为 session artifacts
- 记录 pipeline code digest、SDK operation log、RunSpec、run id、artifact lineage 与 provenance

### 3.2 Pipeline SDK Docs

SDK 用法是 execution capability contract 的一部分，不是模型常识。executor prompt
只应给最小框架、关键词和要求，不应把完整 SDK reference 长篇内嵌进系统提示。

V3 默认提供可检索的 pipeline SDK 文档库：

- 文档根目录：`docs/v3/execution-pipeline-docs/`
- executor 默认可使用只读 `docs.search` / `docs.read`
- 文档库必须与当前 SDK 版本同步，并优先覆盖 artifact、preprocess、HPC tool、batch pattern、sandbox rule 与示例

execution teammate 的默认 authoring 流程：

```text
restore task + artifact catalog
  -> read minimal prompt keywords
  -> docs.search for needed SDK/API details
  -> docs.read selected references/examples
  -> write pipeline code
  -> run pipeline dry-run / validation
  -> fix from structured feedback or request approval
```

dry-run 反馈必须给出可检索关键词或相关 doc id。例如 Vina ligand 不是 PDBQT 时，
反馈应提示查询 `preprocess.prepare_ligand` 或 `hpc-vina.md`，而不是只返回低层
Python exception。

### 3.3 Execution Tool Contract 与 HPC SDK

tool contract 至少描述：

- required input slots 与目标远端路径
- optional params 与资源请求
- expected outputs 与 success checks
- failure signatures 与 parser hints
- preprocess requirements，例如 Vina 需要 receptor/ligand PDBQT

`hpc.*` SDK 函数的实现默认应由 tool contract 驱动，而不是不断增加
tool-specific command 拼接分支。每次 HPC SDK 调用都必须生成可审计 `RunSpec`。

preprocess 是 pipeline 的受控本地能力：

- `convert_format` 负责通用分子格式转换
- `prepare_receptor` 负责 receptor PDBQT 准备
- `prepare_ligand` 负责 ligand PDBQT 准备
- `smiles_to_3d` 负责 SMILES 到三维 ligand 中间结构

executor 在 pipeline code 中判断是否需要 preprocess；preprocess 输出必须先成为可信
session artifact，再被后续 `hpc.*` 调用作为 `RunSpec.inputs` 消费。

## 4. Reporting 默认不属于 Capability Engine

定位：

- 报告总结默认由 report teammate 直接在共享 workspace 上完成
- `report draft` 是 control-plane 中可恢复、可修订、可发布的正式工作对象

默认要求：

- report teammate 读取 research、execution、artifact workspace 与 protocol thread
- report teammate 直接更新 `report_draft`
- final `report` 作为 `report_draft` 的发布结果进入 workspace projection

补充边界：

- 若未来需要离线批处理、重算、严格 schema 生成，可额外定义可选 reporting engine
- 该可选 engine 不属于当前 V3 默认 capability baseline，也不应反向主导主路径

## 5. Engine Registration

所有 capability engine 必须挂入统一 registry。

registry 至少记录：

- `engine_name`
- `tool_names`
- `input_schema`
- `output_schema`
- `requires_approval`
- `supports_background`
- `idempotency_key_shape`
- `produces_artifact_types`
- `capability_key`

## 6. AI 提醒

后续 AI 在实现 capability engine 时必须记住：

- 能力引擎是 harness 的被调对象，不是 product orchestrator
- 如果实现过程中又在 engine 外层包一个更大的 phase graph，说明方向错了
