# Enzyme Design Agent 架构设计

## 1. 文档目标

本文档定义一个遵循 MCP（Model Context Protocol）规范、并提供类似 Claude Code 使用体验的 Enzyme Design Agent 总体架构。

设计目标有三点：

1. 把“自然语言酶设计任务”转成可执行、可恢复、可审计的工程流程。
2. 在协议层遵循 MCP 的能力边界，把工具、资源、提示模板标准化暴露出来。
3. 在产品层提供类似 Claude Code 的交互方式，包括持续对话、斜杠命令、任务恢复、工件管理和长任务追踪。

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

### 3.4 分层隔离高于全能单体

建议严格区分四层：

1. 产品交互层
2. 工作流编排层
3. 专家角色推理层
4. MCP 工具与资源层

### 3.5 所有关键动作必须可追溯

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
| Web Chat Host  |  | CLI            |
| - chat UI      |  | - debug        |
| - app iframe   |  | - batch        |
| - run panels   |  | - automation   |
+----------------+  +----------------+
        |                 |
        +--------+--------+
                 |
                 v
+-----------------------------------+
| Enzyme Host Agent                 |
| - session manager                 |
| - project / episode manager       |
| - workflow state machine          |
| - approval & safety gates         |
| - memory coordinator              |
| - MCP client manager              |
+-----------------------------------+
   |              |               |
   v              v               v
+--------+    +--------+     +---------+
|Research|    |Design  |     |Evaluate |
|Roles   |    |Roles   |     |Roles    |
+--------+    +--------+     +---------+
        \         |          /
         \        |         /
          +-------+--------+
                  |
                  v
+-----------------------------------+
| Shared Typed State                |
| - project state                   |
| - design contract                 |
| - evidence graph                  |
| - candidates                      |
| - runs                            |
| - experiment feedback             |
+-----------------------------------+
                  |
                  v
+-----------------------------------+
| MCP Servers                       |
| - mcp-preprocess                  |
| - mcp-bio-research                |
| - mcp-structure-workbench         |
| - mcp-hpc-tool-contracts          |
| - mcp-project-memory              |
| - mcp-reporting (optional)        |
+-----------------------------------+
                  |
                  v
+-----------------------------------+
| Infra MCP Server                  |
| - mcp-hpc-runner                  |
+-----------------------------------+
```

### 4.2 关键结论

- Host 是系统入口，也是真正的 Agent。
- Web Chat Host 应作为主要人机交互入口，以承载 iframe 形式的 MCP Apps。
- CLI 应保留，主要用于调试、批处理和自动化，而不是承载复杂可视化交互。
- 多 Agent 角色优先实现为 Host 内部的“角色化推理单元”，而不是独立部署的远程 Agent。
- MCP Server 用来提供稳定、可测试、可复用的能力边界。
- 交互式 3D 结构查看和手工标注应实现为独立 MCP App server，而不是塞进 Host 或底层 runner。
- `mcp-hpc-runner` 更适合作为基础设施层，不应直接暴露给高层设计 Agent 拼接底层 `RunSpec`。

---

## 5. 组件设计

## 5.1 Host 层

Host 层承担类似 Claude Code 的核心职责：

- 维护当前 project 和 episode
- 接收自然语言目标并生成 design contract
- 调度不同专家角色
- 管理 MCP client 连接
- 提供 slash commands 和执行入口
- 记录状态、报告和工件索引
- 对高成本、高风险动作执行审批

Host 层不应与单一界面形态绑定。

建议同时支持两个入口：

- Web Chat Host：主入口，负责聊天界面、MCP App iframe、artifact 面板和长任务状态展示
- CLI：辅入口，负责调试、批处理、脚本化执行和无图形环境使用

Host 层建议实现以下子模块：

### 5.1.1 Session Manager

负责对话会话管理：

- 当前 project
- 当前 episode
- 当前活跃计划
- 最近使用的 runs
- 最近打开的 artifacts

### 5.1.2 Project / Episode Manager

负责长期工作区：

- `Project`：一个酶设计项目
- `Episode`：一次具体迭代闭环
- `Run`：一次工具执行
- `Artifact`：结构、日志、评分、报告、表格等产物
- `Manifest`：输入、输出、参数、版本、依赖和校验摘要

### 5.1.3 Workflow Engine

建议采用显式状态机实现，优先选择 LangGraph 或等价代码状态机框架，而不是仅靠 prompt 串联。

原因：

- 可以表达循环与分支
- 可以做节点级重试和失败恢复
- 可以插入人工确认节点
- 可以把长任务状态持久化

### 5.1.4 MCP Client Manager

负责管理多个 MCP 连接：

- 启动和连接本地 stdio servers
- 发现并缓存 `tools/resources/prompts`
- 路由不同角色访问不同 server
- 限制角色可见的工具白名单

### 5.1.5 Approval & Safety Gate

所有以下动作必须经过显式策略控制：

- GPU / 长时 HPC 任务
- 会导致大量费用的批量计算
- 向外部系统写入数据
- 导出实验交付包
- 涉及敏感序列、用途或高风险任务的设计流程

---

## 5.2 专家角色层

建议采用 6 个角色，作为 Host 内部的受限推理单元。

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

这是整个 Claude Code 风格体验的关键补充层。

职责：

- 把项目状态和工件以 resources 的方式暴露
- 把“记录决策、更新状态、导入实验结果、归档 episode”以 tools 的方式暴露
- 作为结构标注、用户备注和 design constraints 的状态真源

建议资源 URI：

- `enzyme://project/{project_id}/config`
- `enzyme://project/{project_id}/episodes`
- `enzyme://project/{project_id}/episode/{episode_id}/goal`
- `enzyme://project/{project_id}/episode/{episode_id}/state`
- `enzyme://project/{project_id}/episode/{episode_id}/plan`
- `enzyme://run/{run_id}/manifest`
- `enzyme://candidate/{candidate_id}/summary`
- `enzyme://experiment/{experiment_id}/result`

### `mcp-reporting`（可选）

职责：

- 汇总候选
- 生成 `report.md`
- 导出实验交付包

MVP 阶段也可以先不独立成 server，而由 Host 本地实现。

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
- `confirm_plan`
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
- 计划文件
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

---

## 8. 共享状态模型

建议 Host 的核心状态对象至少包含以下字段：

```json
{
  "project": {},
  "episode": {},
  "goal": {},
  "design_contract": {},
  "constraints": {},
  "evidence_graph": {},
  "strategy": {},
  "candidate_pool": [],
  "selected_candidates": [],
  "runs": [],
  "artifacts": [],
  "decision_log": [],
  "experiment_feedback": [],
  "calibration_state": {},
  "next_actions": []
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
      plan.yaml
      state.json
      runs/
      artifacts/
      report.md
      manifest.json
  cache/
  .enzyme/
```

补充建议：

- `state.json` 存储 Host 的结构化状态快照
- `plan.yaml` 存储当前 episode 的执行计划
- `manifest.json` 存储本轮综合可复现元数据
- `runs/<run_id>/` 下只保留 run 级定位信息，其它细粒度产物可引用 runner 生成的 artifact store

---

## 10. Claude Code 风格交互设计

## 10.1 交互目标

Agent 使用体验应接近：

- 用户持续用自然语言描述目标和修改约束
- 系统能记住当前工作上下文
- 用户可以随时查看计划、运行状态和产物
- 用户关闭终端或浏览器后还能从上次状态恢复

考虑到 `mcp-structure-workbench` 等 MCP Apps 需要在宿主中以内嵌 iframe 的方式渲染，系统应优先提供网页形态的对话入口。

## 10.2 推荐入口形态

建议采用双入口设计：

- Web Chat Host：主入口
- CLI：辅助入口

其中 Web Chat Host 负责：

- 聊天对话界面
- MCP Apps iframe 容器
- 结构可视化工作台的嵌入
- run 状态、日志和 artifact 的可视化面板
- 审批弹窗、表单式 elicitation 和结果回看

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

建议继续使用已有文档中的命令体系：

- `enzyme init`
- `enzyme doctor`
- `enzyme chat`
- `enzyme new-episode`
- `enzyme plan`
- `enzyme run`
- `enzyme status`
- `enzyme logs`
- `enzyme fetch`
- `enzyme report`
- `enzyme export`

## 10.4 建议 slash commands

- `/goal`
- `/constraints`
- `/set`
- `/plan`
- `/apply`
- `/run`
- `/status`
- `/report`
- `/resume`
- `/approve`

其中：

- `/approve` 用于高成本或高风险动作确认
- `/resume` 用于跨会话恢复

在 Web Chat Host 中，这些命令可以继续保留为 slash commands，也可以以按钮、表单和侧边栏操作的方式暴露；两者应共用同一后端语义。

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

## 13.1 MVP 阶段

目标：

- 跑通从对话到报告的一条完整闭环

范围：

- Host runtime
- Web Chat Host
- Host CLI
- `mcp-preprocess`
- `mcp-hpc-tool-contracts`
- `mcp-hpc-runner`
- 简化版 `mcp-project-memory`

支持流程：

1. 输入目标
2. 生成 design contract
3. 形成计划
4. 运行若干工具
5. 汇总结果
6. 输出报告

## 13.2 第二阶段

新增：

- `mcp-structure-workbench`
- 结构可视化与位点手工标注
- annotation -> constraint 转换
- `mcp-bio-research`
- 文献结构化抽取
- evidence graph
- 多轨设计
- 候选多样性控制

## 13.3 第三阶段

新增：

- 实验反馈回流
- 在线校准
- 主动学习推荐
- 多目标帕累托筛选

## 13.4 第四阶段

新增：

- 多用户协作
- 更细粒度的审计和权限系统
- 更标准化的 task/progress 支持

---

## 14. 当前仓库的落地映射

| 能力 | 当前状态 | 角色 |
|------|----------|------|
| `mcp-preprocess` | 已有 | 本地预处理与格式转换 |
| `mcp-hpc-tool-contracts` | 已有 | 领域工具入口 |
| `mcp-hpc-runner` | 已有 | 基础设施执行层 |
| `mcp-structure-workbench` | 待实现 | 结构查看、交互标注与约束编辑的 MCP App |
| Web Chat Host | 待实现 | 主交互入口，承载聊天界面与 MCP App iframe |
| Host CLI | 待实现 | Claude Code 风格入口 |
| `mcp-bio-research` | 待实现 | 检索与知识抽取 |
| `mcp-project-memory` | 待实现 | 项目状态与工件资源层 |
| reporting server | 可选 | 报告与导出 |

关键边界结论：

- 高层 Agent 直接调用 `mcp-hpc-tool-contracts`
- 交互式结构 UI 由 `mcp-structure-workbench` 提供
- 用户在 UI 中的标注结果统一写回 `mcp-project-memory`
- `mcp-hpc-tool-contracts` 再调用 `mcp-hpc-runner`
- Web Chat Host 承载主要可视化交互，CLI 保留为辅助入口
- Host 负责项目状态和体验，不让底层 runner 侵入产品层

---

## 15. 总结

本设计把 Enzyme Design Agent 定义为：

**一个以 Host 为中心、以状态机为骨架、以内部多角色推理为策略层、以 MCP Servers 为标准能力边界的可恢复酶设计系统。**

它不是单一的大模型代理，也不是单个 MCP server，而是一个分层系统：

- Host 提供 Claude Code 风格工作体验
- 内部多角色负责研究、设计、评估和反馈
- MCP server 负责把工具、资源和模板能力标准化
- 基础设施执行能力通过 contract 层与 runner 层解耦

这样设计的好处是：

- 符合 MCP 规范职责边界
- 复用现有仓库能力
- 便于逐步落地
- 便于后续测试、审计和扩展

---

## 16. 参考

- `docs/Multi-Agent Enzyme Design Framework.md`
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
