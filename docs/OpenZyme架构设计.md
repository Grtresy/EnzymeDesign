# OpenZyme 主线架构设计

## 1. 文档定位

本文档描述当前根仓库主线的架构边界。

它回答的是两件事：

1. 现在主线仓库还保留哪些系统能力
2. V2 将以什么边界继续建设

它**不再**描述已经迁入 `legacy/v1/` 的 V1 Host 实现。  
V1 归档文档见：[legacy/v1/docs/OpenZyme V1实现架构设计.md](/home/grtresy/VSCodeRepo/EnzymeDesign/legacy/v1/docs/OpenZyme%20V1%E5%AE%9E%E7%8E%B0%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1.md)

V2 目标蓝图见：[docs/OpenZyme V2 LangChain重写蓝图.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/OpenZyme%20V2%20LangChain%E9%87%8D%E5%86%99%E8%93%9D%E5%9B%BE.md)

---

## 2. 当前主线边界

根仓库主线已经完成一次 V1 -> legacy 的硬切换。

当前主线保留：

- `apps/mcp-hpc-runner`
- `containers/`
- `database/`
- `docs/`
- `openspec/`
- V2 预留骨架目录：
  - `apps/openzyme-host-api`
  - `apps/openzyme-web-ui`
  - `packages/openzyme-graph`
  - `packages/openzyme-domain`
  - `packages/openzyme-storage`
  - `packages/openzyme-tools`
  - `packages/openzyme-execution`

已经迁入 `legacy/v1/` 的旧主线包括：

- Host runtime
- Web Host
- Host CLI
- `mcp-project-memory`
- `mcp-preprocess`
- `mcp-hpc-tool-contracts`
- `pi-ai-sidecar`
- V1 playgrounds
- V1 相关 OpenSpec 规格与变更工件

因此，根仓库当前**不是**“V1 Host 系统的持续实现目录”，而是：

- 一个保留 HPC 执行基础设施的主线仓库
- 一个承接 OpenZyme V2 重写的主线工作区

---

## 3. 主线架构原则

### 3.1 保留可复用基础设施，停止沿用旧产品壳

`mcp-hpc-runner` 继续作为主线保留，因为它承担稳定的远程执行、Slurm 调度、artifact staging 和作业生命周期管理边界。

旧的 Host/Web/CLI/runtime 没有继续留在主线增量演进，而是被冻结到 `legacy/v1/`。  
V2 不再以它们为当前实现基线。

### 3.2 V2 采用 LangGraph-first，而不是 V1 Host-first 增量修补

主线下一步默认采用：

- LangGraph 作为工作流主内核
- LangChain 作为模型、工具、structured output 与 agent primitives 层
- 自建 Web UI 作为主交互面
- 数据库 + LangGraph checkpointer 作为状态真源

这意味着 V2 的核心目标不再是继续加强 V1 的工作区文件型 canonical state，而是转向：

- durable workflow
- graph-native interrupt / resume
- typed domain model
- Web-first execution-aware UI

### 3.3 旧 MCP 能力按“是否仍适合作为主线基础设施”区分处理

主线保留和未来继续复用的，是边界稳定、与 V2 新内核低耦合的能力：

- `mcp-hpc-runner`
- HPC 容器与镜像资产
- 生物数据资料与数据库资产

不再作为主线继续扩展的，是明显耦合 V1 Host 状态模型的能力：

- `mcp-project-memory`
- `mcp-preprocess`
- `mcp-hpc-tool-contracts`
- `enzyme-host-runtime`
- V1 Web/CLI surfaces

这些能力是否在 V2 中“概念上保留”，不等于它们继续以相同目录、相同 contract 和相同产品角色存在于主线。

---

## 4. V2 目标分层

当前主线以 V2 目标分层为准：

```text
User
  |
  v
React Web UI / Thin CLI
  |
  v
FastAPI Host API
  |
  v
LangGraph Supervisor Graph
  |
  +--> intake
  +--> research
  +--> design
  +--> execution
  +--> report_review
  |
  v
Typed tools / application services
  |
  +--> preprocess service
  +--> research service
  +--> execution compiler / dispatcher
  +--> reporting service
  |
  v
Persistence + Infra
  |
  +--> relational store
  +--> LangGraph checkpointer
  +--> artifact store
  +--> mcp-hpc-runner / SSH / Slurm
```

关键边界：

- Web UI / CLI 不持有工作流真状态
- Host API 是唯一共享入口
- LangGraph Supervisor Graph 承担 episode 生命周期控制
- typed services 负责能力执行，不直接拥有 workflow
- `mcp-hpc-runner` 继续作为外部执行边界，而不是被替换

---

## 5. 当前主线落地状态

### 5.1 已落地

- `mcp-hpc-runner` 仍在主线，可独立测试与运行
- `containers/` 与 `database/` 仍作为共享基础资产保留
- V2 设计蓝图已落盘
- V2 目录骨架已创建，但尚未进入实质实现阶段

### 5.2 已归档到 legacy

- V1 Host product shell
- V1 workflow runtime
- V1 canonical project memory
- V1 preprocess / tool-contracts integration chain
- V1 LLM sidecar integration

这些内容仍可在 `legacy/v1/` 中查看、运行和测试，但不再代表根仓库当前实现。

### 5.3 尚未开始或待重开

- `openzyme-host-api`
- `openzyme-web-ui`
- `openzyme-graph`
- `openzyme-domain`
- `openzyme-storage`
- `openzyme-tools`
- `openzyme-execution`
- 任何基于 V2 架构重新定义的 bio-research / knowledge / structure-workbench 主线实现

---

## 6. 文档与规格边界

根目录 `docs/` 默认只承载：

- 当前主线架构文档
- V2 目标蓝图
- 共享基础资料
- 可继续服务于 V2 的研究资料

`legacy/v1/docs/` 承载：

- V1 Host/runtime/Web/CLI 相关架构与调试文档
- V1 时代的产品/交互/能力接入语义

根目录 `openspec/` 默认只承载主线未来要继续推进的规格与变更。  
依赖 V1 Host/runtime/memory 语义的旧变更，应视为 legacy 工件。

---

## 7. 与 V2 蓝图的关系

本文档不是完整蓝图，而是主线边界说明。

如果需要回答：

- V2 为什么选择 LangGraph
- Web UI 如何与 graph frontend 对齐
- 状态真源为何转向 DB + checkpointer
- 哪些旧能力要回收到 Host 内部 typed tools

请直接参考：[docs/OpenZyme V2 LangChain重写蓝图.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/OpenZyme%20V2%20LangChain%E9%87%8D%E5%86%99%E8%93%9D%E5%9B%BE.md)

---

## 8. 总结

当前根仓库的架构结论是：

- 主线已经不再继续承载 V1 Host 实现
- 主线保留 HPC 执行基础设施与共享资产
- OpenZyme 将以 V2-first 的方式重建上层 Host、状态层和前端
- V1 相关系统以 `legacy/v1/` 形式冻结保留

因此，任何后续主线实现、OpenSpec change 或架构讨论，都应默认以 V2 重写边界为前提，而不是再把根仓库视为 V1 Host 的延续实现目录。
