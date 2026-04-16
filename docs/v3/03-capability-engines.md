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

### 2.3 不应直接照搬的部分

- 让 deep_researcher graph 直接变成整个 OpenZyme 的顶层产品架构
- 让 open_deep_research 的内部 state 直接暴露给 V3 UI
- 让 research session 替代 V3 的 session / task / lane control plane

### 2.4 V3 外部接口

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

要求：

- 同一 `task_id` 允许存在多个 research invocation
- engine 内部 graph/checkpoint 只能作为 invocation 局部运行态
- 对 harness 可恢复的状态必须回写 `engine_invocation + evidence artifacts`

## 3. Execution Engine

定位：

- 负责将某项 task 或 artifact 集合转化为可执行请求
- 继续复用 `apps/mcp-hpc-runner` 作为外部执行边界

要求：

- 对 harness 至少提供 `start_execution(invocation_id, task_id, handoff)`、`resume_execution(invocation_id, resolution)`、`get_execution_status(invocation_id)`
- approval 由 harness 统一发起和恢复
- 执行结果必须回填 `run`、`artifact`
- 结果必须能对 reporting / UI 统一投影

## 4. Reporting Engine

定位：

- 将 research、execution、artifact workspace 汇总成用户可消费报告

要求：

- 对 harness 至少提供 `start_report(invocation_id, task_id, report_brief)`、`resume_report(invocation_id, resolution)`、`get_report_status(invocation_id)`
- 支持草稿、修订、最终报告
- 输出必须结构化，便于 UI 和评估
- 不拥有顶层 workflow 生命周期

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
