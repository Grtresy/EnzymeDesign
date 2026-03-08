# OpenZyme 架构设计

## 1. 文档目标

本文档定义一个遵循 MCP（Model Context Protocol）规范、并提供持续工作会话体验的 OpenZyme 总体架构。

设计目标有三点：

1. 把“自然语言酶设计任务”转成可执行、可恢复、可审计的工程流程。
2. 在协议层遵循 MCP 的能力边界，把工具、资源、提示模板标准化暴露出来。
3. 在产品层提供类似 Claude Code 的持续工作体验，包括任务恢复、工件管理、长任务追踪、结构化反馈和对话辅助。

本文档优先基于当前仓库已有能力设计，不假设重写现有 `mcp-hpc-runner`、`mcp-hpc-tool-contracts` 和 `mcp-preprocess`。

---

## 2. 设计背景

当前仓库已经具备三类基础能力：

- `mcp-hpc-runner`：负责 SSH / Slurm 执行、staging、artifact store、job lifecycle。
- `mcp-hpc-tool-contracts`：负责把领域参数编译成 `RunSpec`，并以 MCP 工具的形式暴露 `hhblits`、`alphafold3`、`fpocket`、`vina` 等工具。
- `mcp-preprocess`：负责本地预处理和格式转换。

与此同时，已有文档已经给出两个重要方向：

- 酶设计流程不能做成线性瀑布流，必须是可迭代状态机。
- Claude Code 式体验的关键不是“更多工具”，而是“Project / Episode / Run / Artifact / Manifest”这类长期工作上下文。

因此，本设计的核心判断是：

**Agent 本体应该是一个 Host，而不是一个大而全的 MCP Server。**

MCP Server 负责暴露窄职责能力；全局任务编排、会话记忆、审批、人机交互和多 Agent 协作应留在 Host 层。

---

## 3. 总体设计原则

### 3.1 协议与产品解耦

MCP 解决的是能力接入标准化，不解决完整产品体验。

- MCP Server 不负责长期会话管理。
- MCP Server 不持有跨工具的全局工作流状态。
- Claude Code 风格的连续工作体验由 Host 提供。

### 3.2 状态机优先于流水线

酶设计不是固定顺序的“检索 -> 生成 -> 评估”。

系统必须支持：

- 在评估阶段回退到约束修订
- 在实验反馈后重新规划设计轨道
- 在工具失败后重试、降级或切换工具
- 在长任务未完成时跨会话恢复

### 3.3 结构化数据优先于自由文本

Agent 间、Host 与 MCP Server 间，以及工具输出到记忆层之间，应尽量使用结构化对象，而不是自由文本。

优先结构化的对象包括：

- design contract
- evidence item
- constraint set
- candidate record
- run record
- experiment result
- decision log

### 3.4 Workflow-first，而不是 Chat-first

对 OpenZyme 而言，对话是重要入口，但不是系统本体。

- 用户可以通过对话表达目标、修订约束、请求解释
- 系统真实状态必须落在 project / episode / run / artifact / decision 这些结构化对象上
- 聊天记录不能成为唯一状态真源

### 3.5 分层隔离高于全能单体

建议严格区分四层：

1. 产品交互层
2. 工作流编排层
3. 专家角色推理层
4. MCP 工具与资源层

### 3.6 所有关键动作必须可追溯

系统必须能回答以下问题：

- 这轮候选是基于哪些约束生成的？
- 哪个工具跑出的结果支撑了这个决策？
- 哪次实验反馈改变了评分策略？
- 某个 run 为什么失败？
- 当前报告对应的输入、版本、参数和 artifact 是什么？

---

## 4. 总体架构

### 4.1 分层图

```text
User
  |                 |
  v                 v
+----------------+  +----------------+
| Web Host       |  | CLI            |
| - operator UI  |  | - debug        |
| - app iframe   |  | - batch        |
| - feedback UI  |  | - automation   |
+----------------+  +----------------+
        |                 |
        +--------+--------+
                 |
                 v
+-----------------------------------+
| OpenZyme Host Core               |
| - session / interrupt manager     |
| - project / episode manager       |
| - approval & safety gates         |
| - MCP registry / routing          |
| - run dispatch broker             |
+-----------------------------------+
                 |
                 v
+-----------------------------------+
| Host Agent Workflow              |
| - decide                          |
| - select action                   |
| - observe                         |
| - revise                          |
| - ask / approve / continue        |
+-----------------------------------+
         |                     |
         v                     v
+-----------------------------------+
| Typed Project Memory             |
| - agent state                     |
| - decision log                    |
| - feedback log                    |
| - approval gates                  |
| - interrupts / session            |
| - runs / artifacts                |
+-----------------------------------+
                 ^
                 |
+-----------------------------------+
| MCP Servers / Execution Plane    |
| - mcp-preprocess                  |
| - mcp-bio-research                |
| - mcp-structure-workbench         |
| - mcp-hpc-tool-contracts          |
| - mcp-project-memory              |
| - mcp-reporting (optional)        |
| - infra: mcp-hpc-runner           |
+-----------------------------------+
```

### 4.2 关键结论

- Host Core 是系统控制平面，真正的 Agent workflow 在 Host 内运行，而不是分散在 UI 或某个 MCP server 中。
- Web Host 应作为主要人机交互入口，以承载 iframe 形式的 MCP Apps、待反馈项和恢复入口，但它不是状态真源。
- CLI 应保留，主要用于调试、批处理、恢复和自动化，而不是承载复杂可视化交互。
- 多 Agent 角色优先实现为 Host 内部的“角色化推理单元”，而不是独立部署的远程 Agent 网络。
- MCP Server 用来提供稳定、可测试、可复用的能力边界；工作流编排和长期状态不应下沉到 MCP 层。
- OpenZyme 当前没有引入 OpenClaw 式 `node` 的必要；若未来需要管理特定机器、仪器或工作站，建议先抽象为 `execution target` 或 `instrument host`。
- `mcp-hpc-runner` 更适合作为基础设施层，不应直接暴露给高层设计 Agent 拼接底层 `RunSpec`。

---

## 5. 组件设计

## 5.1 Host Core 层

Host Core 承担类似 Claude Code 的宿主职责，但其第一性抽象是 workflow 和 project state，而不是聊天流：

- 维护当前 project 和 episode
- 管理 session、interrupt 和 resume 边界
- 承载 agent workflow 的启动、恢复和推进
- 管理 MCP client 连接与执行路由
- 记录 decision trace、反馈、报告和工件索引
- 对高成本、高风险动作执行审批和安全门控

Host Core 不应与单一界面形态绑定。

建议同时支持两个入口：

- Web Host：主入口，负责对话辅助、MCP App iframe、artifact 面板、待反馈项和长任务状态展示
- CLI：辅入口，负责调试、批处理、脚本化执行和无图形环境使用

Host Core 建议实现以下子模块：

### 5.1.1 Session / Interrupt Manager

负责工作会话与中断恢复：

- 当前 project
- 当前 episode
- 当前活跃 agent state version
- pending interrupts
- awaiting feedback / approval
- 最近使用的 runs
- 最近打开的 artifacts

它必须保证 Web Host 与 CLI 共享同一恢复锚点，而不是各自维护私有进度。

### 5.1.2 Project / Episode Manager

负责长期工作区：

- `Project`：一个酶设计项目
- `Episode`：一次具体迭代闭环
- `Run`：一次工具执行
- `Artifact`：结构、日志、评分、报告、表格等产物
- `Manifest`：输入、输出、参数、版本、依赖和校验摘要

### 5.1.3 Agent Workflow Engine

建议采用显式状态机实现，优先选择 LangGraph 或等价代码状态机框架，而不是仅靠 prompt 串联。

原因：

- 可以表达循环与分支
- 可以做节点级重试和失败恢复
- 可以插入人工确认节点
- 可以把长任务状态持久化

核心循环应明确为：

`decide -> act -> observe -> revise -> ask/approve -> continue or stop`

计划在这里应被视为 `working_plan`，是可修订工件，而不是唯一执行真源。

### 5.1.4 MCP Registry / Client Manager

负责管理多个 MCP 连接：

- 启动和连接本地 stdio servers
- 发现并缓存 `tools/resources/prompts`
- 路由不同 action 访问不同 server
- 为不同角色或 action 限制工具白名单
- 统一记录 tool invocation 与 observation 引用

### 5.1.5 Approval & Safety Gate

所有以下动作必须经过显式策略控制：

- GPU / 长时 HPC 任务
- 会导致大量费用的批量计算
- 向外部系统写入数据
- 导出实验交付包
- 涉及敏感序列、用途或高风险任务的设计流程

门控记录至少应包含：

- `gate_id`
- `action_id`
- `action_revision`
- `risk_level`
- `policy_reason`
- `required_feedback_type`
- `status`

**信任等级机制（Phase 2+）：**

为避免"审批疲劳"，系统支持三种信任等级：

| 等级 | 行为 | 适用场景 |
|------|------|----------|
| `auto` | Agent 自主执行，仅异常时通知 | 熟悉的常规任务 |
| `standard` | 高成本/高风险动作需审批 | 默认模式 |
| `conservative` | 每个工具调用都需确认 | 新项目/高风险任务 |

用户可在 episode 开始时选择信任等级，Agent 也可在运行中动态请求调整。

---

## 5.2 专家角色层

建议采用 6 个角色，作为 Host Agent Workflow 内部的受限推理单元。

这些角色是策略性切分，不是第一阶段必须独立部署的服务边界。

### 5.2.1 Manager Agent

职责：

- 维护全局状态机
- 决定下一步执行哪条设计轨道
- 汇总候选与证据
- 判断是否需要人类反馈
- 在失败时决定重试、降级或改道

### 5.2.2 Researcher Agent

职责：

- 调用文献与数据库检索能力
- 提取结构化证据
- 更新约束库和先验知识

输出必须结构化，例如：

- 保守位点列表
- 活性位点说明
- 关键界面残基
- 历史突变先例
- 文献证据链接

### 5.2.3 Designer Agent

职责：

- 在 design contract 和 constraint set 下生成候选
- 维护保守、中等、激进三条设计轨道
- 控制候选多样性

### 5.2.4 Fast-Screen Agent

职责：

- 执行秒级到分钟级预筛
- 剔除明显不符合约束的候选
- 保留少量进入深度评估的候选集

### 5.2.5 Deep-Eval Agent

职责：

- 发起结构预测、口袋识别、对接、通道分析、必要时 MD 等深度评估
- 输出多目标评分向量和不确定性摘要

### 5.2.6 Experimentalist Agent

职责：

- 摄入实验结果
- 识别计算与实验偏差
- 更新评分映射和经验规则
- 触发下一轮重规划

### 5.2.7 为什么这些角色不先做成独立 MCP Server

原因如下：

- 它们共享同一个任务上下文和项目状态
- 它们的差异主要是策略和工具白名单，不是独立部署需求
- 先做成 Host 内角色更容易测试和演进

当某个角色背后的能力足够稳定、可复用、跨 Host 共享时，再提升为 MCP Server 更合适。

---

## 5.3 MCP Server 层

## 5.3.1 现有可直接复用的 Server

### `mcp-preprocess`

职责：

- 格式转换
- 配体准备
- 受体准备
- 本地预处理

适用场景：

- 将上游用户输入转换为下游工具所需格式
- 在进入 HPC 计算前做低成本预处理

### `mcp-hpc-tool-contracts`

职责：

- 暴露面向领域的工具接口
- 将工具参数编译为标准 `RunSpec`
- 决定 invocation mode
- 将执行请求转发给 runner

这层应该是 Host 主要直接调用的 HPC 工具入口。

### `mcp-hpc-runner`

职责：

- SSH / Slurm 执行
- 输入输出 staging
- job lifecycle
- preflight
- artifact fetch
- failure normalization

这层更适合作为基础设施 MCP server，被 `mcp-hpc-tool-contracts` 调用，而非让高层 Agent 直接拼装基础设施参数。

## 5.3.2 建议新增的 Server

### `mcp-bio-research`

建议职责：

- PubMed / Semantic Scholar / UniProt / RCSB / PDB 查询
- 文献元数据拉取
- 结构注释抽取
- 同源序列与功能注释查询

建议暴露：

- 检索类 tools
- 论文、结构、注释结果 resources
- 文献摘要 prompts

### `mcp-structure-workbench`

这是结构交互工作台，推荐使用 MCP Apps 形态实现。

职责：

- 在宿主中内嵌 3D 结构查看界面
- 允许用户交互式选择残基、口袋、界面区域和结构域
- 支持手动标记活性位点、冻结位点、界面约束和删除候选区域
- 将可视化选择结果转换成结构化 annotation 和 design constraints

适用场景：

- 用户旋转、缩放、查看蛋白结构
- 用户手动圈选关键位点而不是仅靠文字描述
- Agent 生成候选后，用户在结构上复核约束或补充说明

实现原则：

- 该组件是一个独立 app server，不放在 Host 内，也不放在 `mcp-hpc-tool-contracts` 或 `mcp-hpc-runner` 中
- UI 负责交互，不负责成为状态真源
- 用户标注、约束编辑和备注必须写回 `mcp-project-memory` 或 episode state
- Host 继续负责审批、编排和后续工具调用

建议暴露：

- tools：
  - `open_structure_view`
  - `save_structure_annotations`
  - `convert_annotations_to_constraints`
- resources：
  - `ui://structure-workbench/viewer.html`
  - `enzyme://project/{project_id}/episode/{episode_id}/annotations`
  - `enzyme://candidate/{candidate_id}/structure`

### `mcp-project-memory`

这是整个 Host Agent workflow 的关键补充层。

职责：

- 把项目状态和工件以 resources 的方式暴露
- 把“记录决策、更新 agent state、提交反馈、处理审批、归档 episode”以 tools 的方式暴露
- 作为结构标注、用户备注、interrupt、approval gate 和 design constraints 的状态真源

建议资源 URI：

- `enzyme://project/{project_id}/config`
- `enzyme://project/{project_id}/episodes`
- `enzyme://project/{project_id}/episode/{episode_id}/goal`
- `enzyme://project/{project_id}/episode/{episode_id}/agent-state`
- `enzyme://project/{project_id}/episode/{episode_id}/working-plan`
- `enzyme://project/{project_id}/episode/{episode_id}/decision-log`
- `enzyme://project/{project_id}/episode/{episode_id}/feedback-log`
- `enzyme://project/{project_id}/episode/{episode_id}/approval-gates`
- `enzyme://project/{project_id}/episode/{episode_id}/interrupts`
- `enzyme://project/{project_id}/episode/{episode_id}/session`
- `enzyme://run/{run_id}/manifest`
- `enzyme://candidate/{candidate_id}/summary`
- `enzyme://experiment/{experiment_id}/result`

### `mcp-reporting`（可选）

职责：

- 汇总候选
- 生成 `report.md`
- 导出实验交付包

MVP 阶段也可以先不独立成 server，而由 Host 本地实现。

### `mcp-domain-knowledge`（Phase 3+）

这是领域知识注入的关键补充，用于增强 Agent 的专业决策能力。

职责：

- 酶设计领域知识库管理
- RAG 驱动的知识检索
- 设计经验规则存储与查询
- 相似案例推荐

建议暴露：

- tools：
  - `query_design_heuristics`: 查询设计经验规则
  - `find_similar_cases`: 查找相似设计案例
  - `get_domain_constraints`: 获取领域特定约束建议
- resources：
  - `enzyme://knowledge/heuristics/{category}`
  - `enzyme://knowledge/cases/{case_id}`
  - `enzyme://knowledge/protocols/{protocol_name}`

知识库内容示例：

```yaml
design_heuristics:
  - id: "he-001"
    condition: "序列相似度 < 50%"
    recommendation: "优先使用 AlphaFold2/3 而非同源建模"
    confidence: 0.85

  - id: "he-002"
    condition: "对接得分 > -6 kcal/mol"
    recommendation: "考虑结构优化或重新设计结合位点"
    confidence: 0.75

reference_cases:
  - id: "case-001"
    name: "酮还原酶改造"
    substrate: "芳香酮"
    mutations: ["W190A", "F225L"]
    outcome: "活性提升 3 倍"
    lessons: ["口袋疏水性对芳香底物结合至关重要"]
```

---

## 6. MCP 能力映射

## 6.1 Tools 设计

`tools` 用来放动作型能力。

适合放进 tools 的能力：

- `prepare_ligand`
- `prepare_receptor`
- `open_structure_view`
- `save_structure_annotations`
- `convert_annotations_to_constraints`
- `hhblits`
- `alphafold3`
- `fpocket`
- `vina`
- `import_experiment_results`
- `submit_feedback`
- `approve_action`
- `continue_workflow`
- `archive_episode`

设计要求：

- 输入必须有明确 schema
- 输出优先返回 `structuredContent`
- 长任务必须返回可追踪标识，例如 `run_id`、`job_id`
- 响应中应尽量附带 artifact references

## 6.2 Resources 设计

`resources` 用来承载上下文、工件和状态。

适合放进 resources 的内容：

- 设计合同
- 当前约束集
- 当前结构标注
- 当前 working plan
- 当前 selected action snapshot
- 候选摘要
- 运行 manifest
- 实验结果
- 历史报告

资源设计原则：

- 面向读取
- 稳定 URI
- 可订阅变化
- 避免把大量自由文本塞进一次 tool 调用

## 6.3 Prompts 设计

`prompts` 用来承载用户显式可见的工作模板，而不是隐藏的工作流逻辑。

建议 prompts：

- `extract_design_contract`
- `analyze_active_site`
- `generate_conservative_designs`
- `triage_failed_run`
- `summarize_episode`
- `prepare_experiment_handoff`

这些 prompt 可以被 slash commands 或 UI 菜单显式调用。

## 6.4 Sampling 设计

建议原则：

- 主推理过程在 Host 内完成
- 仅在 server 内需要宿主 LLM 能力时，才使用 sampling

适用场景：

- 文献抽取 server 请求 Host 帮忙总结长文本
- 报告 server 请求 Host 生成用户可读总结

不建议：

- 把完整多 Agent 编排藏在某个 server 内部
- 在多个 server 中各自维护隐式 Agent

## 6.5 Roots 设计

每个 project 应有明确 root。

建议：

- 仅将当前项目目录暴露为 roots
- 严格限制 server 对其它路径的访问
- 对 `mcp-project-memory` 和 Host 本地文件系统访问做统一边界控制

## 6.6 Elicitation 设计

当 design contract 信息不足时，优先通过结构化 elicitation 获取缺失信息，而不是依赖自由文本追问。

适合 elicitation 的字段：

- 底物名称和 SMILES
- 目标反应
- 冻结位点或结构域
- 实验优先级
- 可接受的计算预算
- 是否允许激进改造

---

## 7. 工作流设计

## 7.1 主状态机

建议主流程如下：

```text
Start / Resume
  -> Decide Next Action
  -> Ask / Clarify / Approve (if needed)
  -> Execute Controlled Action
  -> Observe
  -> Revise Working Plan
  -> Continue or Stop

典型领域动作会落入以下阶段：

Intake
  -> Contract Draft
  -> Constraint Completion
  -> Evidence Gathering
  -> Strategy Planning
  -> Candidate Generation
  -> Fast Screening
  -> Deep Evaluation
  -> Human Review
  -> Experiment Handoff
  -> Feedback Ingestion
  -> Calibration
  -> Replan / Converge
```

这不是严格线性流程，系统必须支持从以下节点回跳：

- 从 `Deep Evaluation` 回到 `Constraint Completion`
- 从 `Human Review` 回到 `Strategy Planning`
- 从 `Feedback Ingestion` 回到 `Candidate Generation`
- 从任意工具失败节点跳入 `Recovery / Fallback`

## 7.2 设计轨道

建议默认三轨并行：

- `conservative`
- `moderate`
- `aggressive`

每条轨道有独立的：

- 输入约束
- 候选预算
- 评分阈值
- 实验优先级

## 7.3 长任务处理

长任务主要来自 HPC。

MVP 阶段可直接复用当前仓库已有模式：

- `job.submit`
- `job.status`
- `job.logs`
- `job.fetch_artifacts`
- `job.cancel`

Host 要做的事情：

- 把这些 job 状态映射为 episode 内的 run 状态
- 持久化 `run_id` / `job_id`
- 支持跨会话恢复
- 在 UI 中展示进度和最近日志

后续如需更贴合新版 MCP，可在不破坏现有接口的情况下增加 task 风格封装。

## 7.4 终止条件定义

系统必须明确定义 Agent workflow 的终止条件，避免在信息不足时无休止地循环。

### 终止条件分类

**成功终止：**
- 所有关键步骤完成
- 设计指标达标（如结合能、稳定性等）
- 用户确认满意

**失败终止：**
- 连续失败次数超过阈值（默认 3 次）
- 资源预算耗尽
- 用户主动中止
- 关键前置条件无法满足

**升级处理：**
- 达到最大迭代次数
- 检测到决策循环（重复相同决策）
- 遇到超出 Agent 能力范围的问题

建议实现：

```python
termination_conditions = {
    "success": [
        {"condition": "all_critical_steps_completed"},
        {"condition": "design_metrics_met", "threshold": {...}},
    ],
    "failure": [
        {"condition": "consecutive_failures >= 3"},
        {"condition": "resource_budget_exhausted"},
        {"condition": "human_abort"},
    ],
    "escalate": [
        {"condition": "max_iterations_reached", "value": 20},
        {"condition": "stuck_in_loop"},
    ]
}
```

## 7.5 审批策略与信任等级

为避免"审批疲劳"，系统应支持可配置的审批策略，而非简单的二元审批。

### 信任等级

用户可为 episode 或整个项目设置信任等级：

- **自动模式**：Agent 自主执行所有动作，仅在异常时通知
- **标准模式**：高成本/高风险动作需要审批
- **保守模式**：每个工具调用都需要确认

### 审批策略配置

```yaml
approval_policy:
  # 自动批准
  auto_approve:
    - tool: hhblits
      condition: "estimated_time < 5min"
    - tool: fpocket
      always: true

  # 需要审批
  require_approval:
    - tool: alphafold3
      reason: "高 GPU 成本"
    - tool: "*"
      condition: "estimated_cost > 30min"
    - tool: "*"
      condition: "affects_multiple_candidates"

  # 升级到人工
  escalate_to_human:
    - condition: "consecutive_failures >= 2"
    - condition: "plan_revision_count >= 3"
    - condition: "novel_tool_combination"
```

### 动态调整

Agent 可在运行时请求调整信任等级：

```
Agent: 我注意到这个 episode 的工具调用都很顺利，
是否允许我切换到更自动化的模式以提高效率？

用户: 好的，切换到标准模式
```

---

## 8. 共享状态模型

建议 Host 的核心状态对象至少包含以下字段：

```json
{
  "project": {},
  "episode": {},
  "goal": {},
  "design_contract": {},
  "working_plan": {},
  "candidate_actions": [],
  "selected_action": {},
  "observations": [],
  "human_feedback": [],
  "approval_gates": [],
  "interrupts": [],
  "session": {},
  "constraints": {},
  "evidence_graph": {},
  "candidate_pool": [],
  "runs": [],
  "artifacts": [],
  "decision_log": [],
  "experiment_feedback": [],
  "calibration_state": {},
  "termination_status": {}
}
```

### 8.0 Agent State 增强字段（Phase 2+）

为支持更智能的 Agent 行为，建议在核心状态基础上扩展以下字段：

```json
{
  // 领域知识注入
  "domain_context": {
    "knowledge_refs": [],
    "design_heuristics": [],
    "reference_cases": []
  },

  // 多方案并行探索
  "candidate_plans": [
    {
      "id": "plan-A",
      "strategy": "保守突变",
      "risk_level": "low",
      "estimated_time": "1h"
    }
  ],
  "parallel_runs": [],

  // Checkpoint 与回退
  "checkpoints": [
    {
      "step": "after_structure_prediction",
      "state_ref": "cp-001",
      "reversible": true,
      "created_at": "..."
    }
  ],
  "current_checkpoint": "cp-002",
  "rollback_budget": 3,

  // 进度预期管理
  "progress_estimate": {
    "estimated_total_time": "2-4 hours",
    "completed_steps": 5,
    "total_steps": 12,
    "current_phase": "结构优化",
    "critical_path": ["结构预测", "对接", "动力学验证"]
  },

  // 审批策略
  "approval_policy": {
    "trust_level": "standard",
    "auto_approve": [...],
    "require_approval": [...]
  },

  // 外部协作钩子
  "external_hooks": [
    {
      "event": "structure_ready",
      "notify": "slack://lab-team"
    }
  ]
}
```

### 8.1 关键子对象

#### Design Contract

建议字段：

- `enzyme_target`
- `substrate`
- `reaction`
- `must_keep`
- `must_avoid`
- `success_metrics`
- `budget`
- `risk_policy`

#### Constraint Set

建议字段：

- `frozen_residues`
- `protected_domains`
- `required_cofactors`
- `interface_constraints`
- `structural_constraints`
- `expression_constraints`

#### Candidate Record

建议字段：

- `candidate_id`
- `parent`
- `track`
- `sequence`
- `mutations`
- `generation_rationale`
- `scores`
- `uncertainty`
- `status`

#### Run Record

建议字段：

- `run_id`
- `tool`
- `params`
- `status`
- `job_id`
- `artifacts`
- `error_code`
- `started_at`
- `finished_at`

#### Decision Log

建议字段：

- `decision_id`
- `type`
- `reason`
- `evidence_refs`
- `author`
- `timestamp`

**增强字段（Phase 2+）：**

为提升可解释性，Decision Log 应支持双层解释：

```json
{
  "decision_id": "dec-001",
  "type": "tool_selection",
  "action": "switch_to_alphafold3",
  "reason_technical": "hhblits similarity 45% < threshold 60%",
  "reason_human": "序列相似度较低，同源建模可能不可靠，改用 AI 结构预测",
  "confidence": 0.85,
  "evidence_refs": ["obs-001", "obs-002"],
  "alternatives_considered": ["homology_modeling", "roseTTAFold"],
  "author": "manager_agent",
  "timestamp": "..."
}
```

#### Approval Policy

建议字段：

- `trust_level`: 信任等级（`auto` | `standard` | `conservative`）
- `auto_approve`: 自动批准规则列表
- `require_approval`: 需要审批的规则列表
- `escalate_to_human`: 升级到人工的条件

#### Checkpoint

建议字段：

- `checkpoint_id`
- `step`: 对应的工作流步骤
- `state_ref`: 状态快照引用
- `reversible`: 是否可回退
- `created_at`
- `description`: 检查点描述

#### Progress Estimate

建议字段：

- `estimated_total_time`: 预计总时间
- `completed_steps`: 已完成步骤数
- `total_steps`: 总步骤数
- `current_phase`: 当前阶段名称
- `critical_path`: 关键路径步骤列表
- `blocking_issues`: 当前阻塞问题

---

## 9. 项目目录与工件组织

建议沿用现有 CLI 文档中已经定义的形态：

```text
project/
  enzyme.yaml
  data/
    inputs/
    refs/
  episodes/
    0001/
      goal.md
      agent-state.json
      working-plan.yaml
      feedback-log.jsonl
      decision-log.jsonl
      approval-gates.json
      interrupts.json
      session.json
      runs/
      artifacts/
      report.md
      manifest.json
  cache/
  .enzyme/
```

补充建议：

- `agent-state.json` 存储 Host Agent workflow 的结构化状态快照
- `working-plan.yaml` 存储当前 episode 的工作计划快照；它是动态工件，不再是唯一执行真源
- `feedback-log.jsonl`、`decision-log.jsonl` 记录反馈与决策谱系
- `approval-gates.json`、`interrupts.json`、`session.json` 支撑跨入口恢复与审批中断
- `manifest.json` 存储本轮综合可复现元数据
- `runs/<run_id>/` 下只保留 run 级定位信息，其它细粒度产物可引用 runner 生成的 artifact store

---

## 10. 持续工作交互设计

## 10.1 交互目标

Agent 使用体验应接近：

- 用户持续用自然语言描述目标和修改约束
- 系统能记住当前工作上下文
- 用户可以随时查看 working plan、当前 action、运行状态和产物
- 用户关闭终端或浏览器后还能从上次状态恢复
- 用户能理解 Agent 为什么做出某个决策（可解释性）

考虑到 `mcp-structure-workbench` 等 MCP Apps 需要在宿主中以内嵌 iframe 的方式渲染，系统应优先提供网页形态的对话入口。

但需要明确：

- OpenZyme 是 `workflow-first, chat-assisted`
- 对话是入口和解释层，不是系统主状态
- 真正的系统状态必须落在 episode、agent state、runs、artifacts 和 decision trace 上

**进度预期管理（Phase 2+）：**

用户需要全局进度视图，而非单步预期：

- 整体任务预计完成时间
- 当前所处阶段（如"初始设计" vs "结构优化" vs "验证"）
- 关键路径与阻塞点
- 已完成/剩余步骤概览

Web UI 应展示：

```text
┌─────────────────────────────────────────┐
│ Episode: 酶设计 A+B→C                   │
│ 阶段: 结构优化 (3/5)                    │
│ 预计剩余: 45-60 分钟                    │
│ ████████████░░░░░░░░ 60%               │
├─────────────────────────────────────────┤
│ 关键路径:                               │
│ ✅ 序列搜索                             │
│ ✅ 结构预测                             │
│ ⏳ 口袋检测 (进行中)                    │
│ ⏸ 分子对接                             │
│ ⏸ 验证                                 │
└─────────────────────────────────────────┘
```

## 10.2 推荐入口形态

建议采用双入口设计：

- Web Host：主入口
- CLI：辅助入口

其中 Web Host 负责：

- 对话辅助界面
- MCP Apps iframe 容器
- 结构可视化工作台的嵌入
- run 状态、日志和 artifact 的可视化面板
- 审批弹窗、表单式 elicitation、interrupt 恢复和结果回看

CLI 负责：

- `doctor`
- 项目初始化
- 脚本化执行
- 调试单个 step
- 无图形环境下的最小工作流

设计原则：

- Agent 核心状态、编排和 MCP client 管理必须在后端 Host 层，而不是浏览器内
- Web 只是主要交互壳，不应成为系统唯一入口
- CLI 不负责承载复杂可视化交互

## 10.3 建议命令面

建议命令面围绕 workflow 驱动，而不是围绕静态 plan 导入：

- `enzyme init`
- `enzyme doctor`
- `enzyme new-episode`
- `enzyme workflow start`
- `enzyme workflow continue`
- `enzyme workflow feedback`
- `enzyme workflow gates`
- `enzyme status`
- `enzyme logs`
- `enzyme fetch`
- `enzyme report`
- `enzyme export`

## 10.4 建议 slash commands

- `/goal`
- `/constraints`
- `/set`
- `/continue`
- `/feedback`
- `/approve`
- `/status`
- `/report`
- `/resume`

其中：

- `/approve` 用于高成本或高风险动作确认
- `/resume` 用于跨会话恢复

在 Web Host 中，这些命令可以继续保留为 slash commands，也可以以按钮、表单和侧边栏操作的方式暴露；两者应共用同一后端语义。

---

## 11. 失败恢复与降级策略

系统必须把工具失败当成一等公民设计，而不是异常分支。

### 11.1 失败分类

- 输入无效
- 远端 preflight 失败
- 工具执行失败
- 产物缺失
- 结果质量不足
- 外部服务不可用

### 11.2 处理策略

对于每类失败，Manager Agent 应能选择：

- 重试
- 降级
- 切换备用工具
- 缩小候选集
- 请求用户确认
- 终止当前轨道

### 11.3 当前仓库的可复用能力

`mcp-hpc-runner` 已经具备：

- preflight
- failure signature mapping
- output validation
- artifact fetch
- job lifecycle

因此 Host 不应重复实现这些基础设施逻辑，而应消费其标准化结果并做更高层策略判断。

### 11.4 Checkpoint 与回退机制（Phase 2+）

为支持更灵活的失败恢复，系统应在关键节点创建状态快照（Checkpoint）。

**Checkpoint 创建时机：**
- 完成高成本计算后（如结构预测）
- 进入不可逆操作前（如批量突变生成）
- 用户主动请求时
- 每完成一个主要阶段

**回退策略：**

```python
def handle_critical_failure(failure, agent_state):
    if failure.severity >= "critical" and agent_state.rollback_budget > 0:
        # 回退到上一个稳定检查点
        checkpoint = find_last_stable_checkpoint(agent_state)
        restore_state(checkpoint)
        agent_state.rollback_budget -= 1

        # 尝试替代策略
        propose_alternative_strategy(failure)
    else:
        # 升级到人工处理
        escalate_to_human(failure)
```

**Checkpoint 生命周期：**

```text
创建 → 验证 → (可选: 回退) → 归档
```

系统应定期清理过期的 checkpoint，但保留关键决策点的快照用于审计。

---

## 12. 安全、合规与权限边界

### 12.1 权限边界

建议采用最小权限原则：

- 高层角色只看到需要的 tools
- research 角色不应直接访问底层 runner
- deep-eval 角色只访问经过 contract 层包装的工具

### 12.2 项目边界

- roots 仅指向当前项目目录
- 导出和写入外部位置需要额外审批

### 12.3 任务边界

以下任务应触发额外审查：

- 敏感用途设计
- 超预算长任务
- 高风险激进设计轨道
- 未验证来源的数据自动注入知识库

---

## 13. 推荐实现路线

## 13.1 MVP 阶段（Phase 1）

目标：

- 跑通从对话到报告的一条完整闭环
- 建立持续决策型 Agent 的基础设施

范围：

- Host runtime
- Web Host
- Host CLI
- `mcp-preprocess`
- `mcp-hpc-tool-contracts`
- `mcp-hpc-runner`
- 简化版 `mcp-project-memory`

核心能力：

1. **Agent Workflow Foundation**
   - LangGraph 驱动的持续决策闭环
   - 可恢复的 Agent State（working_plan, selected_action, observations, feedback）
   - 跨界面共享规范状态

2. **基础交互**
   - 输入目标
   - 生成 design contract
   - 形成计划
   - 运行工具
   - 汇总结果
   - 输出报告

3. **可审计性**
   - Decision Log 基础版
   - Run Manifest
   - Episode 状态持久化

## 13.2 第二阶段（Phase 2 - 体验增强）

新增能力：

- `mcp-structure-workbench`
- 结构可视化与位点手工标注
- annotation -> constraint 转换
- `mcp-bio-research`
- 文献结构化抽取
- evidence graph
- 多轨设计
- 候选多样性控制

**Agent 体验增强：**

1. **终止条件明确化**
   - 显式定义 success/failure/escalate 条件
   - 循环检测与自动升级

2. **信任等级与审批策略**
   - 可配置的 auto_approve / require_approval 规则
   - 动态信任等级调整

3. **进度预期管理**
   - 全局进度视图
   - 关键路径展示
   - 剩余时间预估

4. **双层解释**
   - 技术层面 + 用户层面的决策解释
   - 自然语言决策摘要

## 13.3 第三阶段（Phase 3 - 智能增强）

新增能力：

- 实验反馈回流
- 在线校准
- 主动学习推荐
- 多目标帕累托筛选

**Agent 智能增强：**

1. **领域知识注入**
   - RAG 驱动的知识检索
   - 设计经验规则库
   - 相似案例参考

2. **多方案并行探索**
   - 同时探索多个候选方案
   - 方案对比与评分
   - 自动选择最优路径

3. **Checkpoint 与回退**
   - 关键节点状态快照
   - 失败后自动回退
   - 回退预算管理

4. **外部协作 Hooks**
   - 事件通知机制
   - 与实验团队协作
   - 外部系统集成

## 13.4 第四阶段（Phase 4 - 规模化）

新增能力：

- 多用户协作
- 更细粒度的审计和权限系统
- 更标准化的 task/progress 支持

**企业级能力：**

1. **多用户与权限**
   - 项目级权限控制
   - 协作与共享
   - 审计日志

2. **高级分析**
   - Agent 行为分析
   - 效率优化建议
   - 历史数据挖掘

3. **扩展性**
   - 自定义工具集成
   - 工作流模板
   - API 接口开放

---

## 14. 当前仓库的落地映射

| 能力 | 当前状态 | 角色 | 阶段 |
|------|----------|------|------|
| `mcp-preprocess` | 已有 | 本地预处理与格式转换 | Phase 1 |
| `mcp-hpc-tool-contracts` | 已有 | 领域工具入口 | Phase 1 |
| `mcp-hpc-runner` | 已有 | 基础设施执行层 | Phase 1 |
| Web Host | 待实现 | 主交互入口，承载对话辅助、反馈界面与 MCP App iframe | Phase 1 |
| Host CLI | 待实现 | Claude Code 风格入口 | Phase 1 |
| `mcp-project-memory` | 待实现 | 项目状态与工件资源层 | Phase 1 |
| `mcp-structure-workbench` | 待实现 | 结构查看、交互标注与约束编辑的 MCP App | Phase 2 |
| `mcp-bio-research` | 待实现 | 检索与知识抽取 | Phase 2 |
| 领域知识 RAG | 待实现 | 酶设计知识注入 | Phase 3 |
| Checkpoint 系统 | 待实现 | 状态快照与回退 | Phase 3 |
| 外部协作 Hooks | 待实现 | 事件通知与集成 | Phase 3 |
| reporting server | 可选 | 报告与导出 | Phase 1-2 |

关键边界结论：

- 高层 Agent 直接调用 `mcp-hpc-tool-contracts`
- 交互式结构 UI 由 `mcp-structure-workbench` 提供
- 用户在 UI 中的标注结果统一写回 `mcp-project-memory`
- `mcp-hpc-tool-contracts` 再调用 `mcp-hpc-runner`
- Web Host 承载主要可视化交互，CLI 保留为辅助入口
- Host 负责项目状态和体验，不让底层 runner 侵入产品层

---

## 15. 总结

本设计把 OpenZyme 定义为：

**一个以 Host 为中心、以状态机为骨架、以内部多角色推理为策略层、以 MCP Servers 为标准能力边界的可恢复酶设计系统。**

它不是单一的大模型代理，也不是单个 MCP server，而是一个分层系统：

- Host 提供 Claude Code 风格工作体验
- 内部多角色负责研究、设计、评估和反馈
- MCP server 负责把工具、资源和模板能力标准化
- 基础设施执行能力通过 contract 层与 runner 层解耦

**核心设计决策：**

1. **持续决策闭环**：Agent 不是一次性计划生成器，而是持续做决策的 host agent
2. **动态可修订计划**：计划是 agent state 中的动态工件，而非执行前冻结的唯一真源
3. **受控工具调用**：LLM 决定何时调用什么工具，但实际执行通过 runtime 受控边界
4. **人类反馈作为一等中断点**：支持审批、澄清、拒绝等多种反馈类型
5. **可审计决策谱系**：保留完整决策 trace，而非仅计划版本

**演进路线：**

- **Phase 1 (MVP)**：建立持续决策型 Agent 基础设施
- **Phase 2 (体验增强)**：终止条件、信任等级、进度预期、双层解释
- **Phase 3 (智能增强)**：领域知识注入、多方案并行、Checkpoint 回退、外部协作
- **Phase 4 (规模化)**：多用户协作、企业级权限、高级分析

这样设计的好处是：

- 符合 MCP 规范职责边界
- 复用现有仓库能力
- 便于逐步落地
- 便于后续测试、审计和扩展
- 增强建议与核心设计无冲突，可渐进式实现

---

## 16. 参考

- `docs/OpenZyme Multi-Agent Design Framework.md`
- `docs/CLI交互面设计.md`
- `apps/mcp-hpc-runner/README.md`
- `apps/mcp-hpc-tool-contracts/README.md`
- `openspec/specs/mcp-hpc-runner/spec.md`
- `openspec/specs/mcp-hpc-tool-contracts/spec.md`
- MCP official specification:
  - architecture
  - tools
  - resources
  - prompts
  - sampling
  - roots
  - elicitation
