# OpenZyme V3 Capability Engines

## 1. 定位

Capability engine 是 V3 harness 可调用的专业子系统。

它们的共同约束：

- 对外暴露稳定输入输出
- 不拥有产品顶层真状态
- 可以有自己的局部执行图、局部 prompt、局部 tool loop
- 结果必须回写到 control plane canonical objects
- 启动、恢复、重试与并发由 `engine invocation` 统一标识

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

要求：

- 对 harness 至少提供 `start_execution(invocation_id, task_id, handoff)`、`resume_execution(invocation_id, resolution)`、`get_execution_status(invocation_id)`
- `execution.start(require_approval=true)` 创建 `execution_launch` approval 后，当前 master/teammate loop 必须立即返回 `waiting_approval`，不得继续把 tool result 喂给 LLM 推进下一轮
- approval 由 harness/API 统一 resolve；`POST /v3/approvals/{approval_id}/resolve` 是唯一改变 approval 状态的外部入口
- execution engine 不代表用户批准；`execution.resume` 只消费已 resolved 的 approval，pending approval 下必须保持 invocation 为 `waiting_approval`
- 执行结果必须回填 `run`、`artifact`
- 结果必须能对 report draft / workspace UI 统一投影

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
