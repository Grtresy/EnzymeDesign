# OpenZyme 顶层架构总览

## 文档定位

本文档用于描述 OpenZyme 的顶层分层模型，回答“系统从高到低分别是什么层、各层职责是什么”。

- 它是总览文档，不承担实现状态追踪。
- 当前实现形态、模块落地边界和阶段性路线，请以 `docs/OpenZyme架构设计.md` 为准。
- 当两份文档存在抽象层次差异时，以本文件定义顶层边界，以实现架构文档定义当前代码映射。

为了和 Claude Code 一类 AI Agent 架构更好对齐，可以把 OpenZyme 先理解成 8 层：

- 8: User Interface
- 7: HostControlPlane
- 6: Agent
- 5: ModelContextProtocol
- 4: Capabilities
- 3: Runtime / Sandbox
- 2: System APIs
- 1: Operating System

对应关系如下：

```text
8  User Interface
7  HostControlPlane
6  Agent
5  ModelContextProtocol
4  Capabilities
3  Runtime / Sandbox
2  System APIs
1  Operating System
```

可以再画成 OpenZyme 视角：

```text
User / Web Host / CLI
          |
          v
8  User Interface
          |
          v
7  HostControlPlane
          |
          v
6  Agent
          |
          v
5  ModelContextProtocol
          |
          v
4  Capabilities
          |
          v
3  Runtime / Sandbox
          |
          v
2  System APIs
          |
          v
1  Operating System
```

其中最需要强调的一点是：  
OpenZyme 相比普通“LLM + tools”系统，最核心的差异就在第 7 层 `HostControlPlane`。  
Claude Code 风格体验不是只有 agent 和 tool protocol，而是要有持续工作控制面。

## 8. User Interface

这一层是用户直接接触的入口层。

在 OpenZyme 里主要对应：

- Web Host
- Host CLI
- 后续可能承载 MCP Apps 的宿主界面

它负责：

- 接收用户输入
- 展示 Agent 输出
- 展示 diff、logs、tool call、artifact、approval、interrupt

这一层本质上只是交互壳，不是真状态来源。

## 7. HostControlPlane

这一层是 OpenZyme 最关键的一层。  
它负责把系统组织成一个可恢复、可审计、可持续推进的工作宿主。

它负责：

- project / episode / run / artifact 这些长期上下文
- session / interrupt / resume
- approval gate
- decision trace
- workflow orchestration
- Web 和 CLI 的统一后端语义

如果说 Claude Code 风格体验的关键是：

- 持续会话
- 跨入口恢复
- human-in-the-loop
- 长任务追踪
- 工件和决策可追溯

那么这些能力都应该主要落在这一层。

这一层不是 UI，也不是 Agent，也不是 MCP Server。  
它定义产品控制语义、跨入口一致的工作状态归属，以及系统如何恢复、审批和推进。

需要特别说明的是：

- 这一层拥有状态语义和控制权。
- 具体的规范持久化可以由下层的 Typed Project Memory 或 `mcp-project-memory` 一类能力承载。
- 换句话说，“状态归谁负责”属于 HostControlPlane，“状态落在哪里”可以由专门记忆能力实现。

## 6. Agent

这一层是智能体本身。

它包括：

- LLM
- planner
- ReAct loop
- working memory
- task decomposition

它负责：

- 理解任务
- 拆解任务
- 决定下一步调用什么 capability
- 分析返回结果
- 继续推进或请求人类反馈

在 OpenZyme 里，这一层更接近 `Agent Runtime` 或 `Host Agent Workflow` 中的推理部分。

它不应该负责：

- project / episode 的真状态
- resume / interrupt 的持久化
- tool protocol 的底层连接管理

## 5. ModelContextProtocol

这一层是协议层。  
在 OpenZyme 当前语境下，主要就是 MCP。

它负责：

- 定义 Host 如何访问 capability
- 标准化 `prompts / resources / tools`
- 提供结构化调用接口
- 提供可发现、可路由的能力契约

所以这一层强调的是：

- 协议
- 调用格式
- 能力暴露标准

而不是业务逻辑本身。

在 OpenZyme 里，把 MCP 放在这一层有两个好处：

- 明确 MCP 不是系统本体，而是能力接入协议
- 避免把 MCP Server 和 HostControlPlane 混成一层

## 4. Capabilities

这一层是系统对外或对 Host 可见的能力边界。

在 MCP 语义下，主要包括：

- Prompts
- Resources
- Tools

OpenZyme 里的例子包括：

- `mcp-preprocess`
- `mcp-hpc-tool-contracts`
- `mcp-bio-research`
- `mcp-structure-workbench`
- `mcp-project-memory`

这一层关心的是：

- 这个能力能做什么
- 什么时候应该使用
- 输入输出契约是什么
- 返回的结果形态是什么

它不直接等于底层 executor，也不等于 runtime。

## 3. Runtime / Sandbox

这一层负责运行 capability 背后的实际执行环境，并提供隔离、权限和资源边界。

在 OpenZyme 里可以包括：

- 本地 Python runtime
- MCP server runtime
- SSH / Slurm runner
- Web App sandbox
- 其它隔离执行环境

这一层负责：

- 运行具体工具
- 管理权限边界
- 隔离资源和执行环境
- 支撑长任务和异步任务执行

也就是说，第 4 层是“能力长什么样”，第 3 层是“能力在哪里、如何被运行”。

## 2. System APIs

这一层是操作系统或平台提供的 API。

包括但不限于：

- filesystem API
- subprocess API
- network API
- database driver
- SSH client API
- container / VM runtime API

这一层通常不是 OpenZyme 自己定义的，但上层 capability 和 runtime 最终都依赖它。

## 1. Operating System

这一层是最底层的操作系统。

例如：

- Linux
- macOS
- Windows

它负责：

- 文件系统
- 进程调度
- 内存管理
- 网络
- 权限模型

这是整个系统的最终承载底座。

## 对 OpenZyme 的参考意义

这套 8 层结构对 OpenZyme 最重要的参考意义有三点：

- 它提醒我们要把 `HostControlPlane` 单独拉出来，这是 OpenZyme 最核心的产品层。
- 它提醒我们把 `ModelContextProtocol` 放在协议层，而不是把 MCP 当作系统本体。
- 它提醒我们把 `Capabilities` 和 `Runtime / Sandbox` 分开，不要把能力边界和执行环境混成一层。

如果用一句话总结：

- 第 8 层负责交互入口
- 第 7 层负责持续工作控制面
- 第 6 层负责智能体决策
- 第 5 层负责能力协议
- 第 4 层负责能力边界
- 第 3 层负责执行环境
- 第 2 层负责系统接口
- 第 1 层负责最终承载

## 当前代码映射

结合当前仓库，可以先这样理解：

- 第 8 层 `User Interface`：`apps/enzyme-web-host`、`apps/enzyme-host-cli`
- 第 7 层 `HostControlPlane`：`packages/enzyme-host-runtime` 中的 workspace、services、reporting、execution 编排语义
- 第 6 层 `Agent`：`packages/enzyme-host-runtime` 中的 planning/orchestrator、LLM adapter、policy
- 第 5 层 `ModelContextProtocol`：各 `mcp-*` 服务暴露的 MCP resources / tools / prompts 契约
- 第 4 层 `Capabilities`：`mcp-preprocess`、`mcp-hpc-tool-contracts`、`mcp-project-memory` 以及后续的 `mcp-bio-research`、`mcp-structure-workbench`
- 第 3 层 `Runtime / Sandbox`：本地 Python 执行环境、MCP server runtime、`mcp-hpc-runner`、Web App sandbox
- 第 2 层 `System APIs`：filesystem、subprocess、SSH、数据库驱动、网络接口
- 第 1 层 `Operating System`：Linux / macOS / Windows

当前实现还有一个需要持续收敛的点：

- 顶层分层已经基本成立。
- 但部分 Host 到 capability 的调用仍然是进程内直连，而不是统一走协议客户端。
- 因此这份 8 层图已经可以作为目标边界，但不应被误读为“所有实现细节都已经严格按层隔离完成”。
