# OpenZyme V3 迁移路线图

## 1. 迁移口径

这是一次 **现实替代迁移**，目标是以 V3 取代已冻结的 V2，而不是长期双轨并行。

默认策略：

- 先建立 V3 文档与 control plane
- 再定义 workspace bootstrap 与包迁移桥接边界
- 再建立 harness kernel
- 再先固定 task board 与 lane isolation
- 再补 memory / compaction / protocols / background
- 再把能力引擎逐步挂接进去
- 再显式收敛到 `domain + core + engines + apps`
- 最后再切换 API / CLI / UI
- 最终输出 V2 retirement plan，而不是 V2/V3 coexistence baseline

## 2. 阶段划分

### 阶段 A：文档与边界固化

对应对话：

- Session 01

目标：

- 把 V3 doctrine、目标态、session-by-session 任务包固定下来

### 阶段 B：Control Plane 落地

对应对话：

- Session 02
- Session 03
- Session 04
- Session 07
- Session 05
- Session 06

目标：

- 拿到一个可持久化的 harness control plane
- 拿到最小 agent harness kernel
- 先固定 task / lane 的执行骨架，再补 approval / memory / inbox / delegation / background 等核心机制

### 阶段 C：Workspace Bootstrap And Package Bridge

对应对话：

- Session 02
- Session 03

目标：

- 明确 `pyproject.toml`、导入路径、依赖方向与新旧包桥接策略
- 允许旧目录过渡实现，但禁止新增顶层产品语义继续沉淀到旧包
- 定义收口条件，避免 mixed-package limbo

### 阶段 D：Capability Engines 挂接

对应对话：

- Session 08
- Session 09
- Session 10

目标：

- 挂接 `deep_research`、`execution` capability engines
- 建立 report teammate + report draft + final report 发布路径
- 将 execution artifact staging、tool contract compiler、多输入多输出和 preprocess 前置能力纳入 Session 09 baseline

### 阶段 E：产品表面切换

对应对话：

- Session 11
- Session 12

目标：

- 提供 `/v3` API、CLI、UI
- 完成 cutover 预演、评估、回滚策略与 V2 retirement plan

## 3. Session 依赖

- Session 01 是全部前置
- Session 02 之前不得改 schema
- Session 03 依赖 Session 02 的 canonical objects
- Session 04 依赖 Session 03 的 harness kernel
- Session 03 之前需要先固定 workspace bootstrap / package bridge 默认值
- Session 07 依赖 Session 04 的 task board，用于固定 task-lane binding 与执行隔离语义
- Session 05 依赖 Session 07 已给出 lane binding 规则；若提前实施，则只允许交付 lane-agnostic 的 memory / compaction base
- Session 06 依赖 Session 07 已给出 lane / agent / execution context 的绑定规则；若提前实施，则只允许交付不含 lane-aware restore 的 protocol base
- Session 08/09/10 依赖前述 control plane 能够承载 engine 结果
- Session 11 依赖 workspace projection 已稳定
- Session 12 依赖主要功能链路已经联通

## 4. 迁移成功标准

- 产品顶层真状态已不依赖 graph checkpoint
- UI / CLI 只消费 control-plane projection
- `deep_research` 成为 capability engine，而不是顶层 orchestrator
- `execution` approval 统一走 harness protocol
- execution 不再把 Host 本地 artifact `storage_uri` 当作 HPC 远端路径；输入必须经 `RunSpec.inputs` staging
- preprocess 输出和 HPC declared outputs 都能回填为 session artifact
- 任务、lane、approval、memory 可跨压缩恢复
- engine invocation、delegation、background completion 可独立恢复
- V3 能独立跑通从 research 到 execution 到 report drafting 再到 final delivery 的闭环
- V2 已被明确冻结，且不存在继续向 V2 主模型回灌新能力的计划
- `openzyme-runtime` / `openzyme-storage` / `openzyme-tools` / `openzyme-graph` 不再承载新的产品顶层真状态

## 5. 风险提示

- 最大风险不是代码复杂度，而是“做着做着又回到 graph-first”
- 第二风险是沿着 V2 目录继续越拆越细，导致 `runtime/storage/tools/graph` 边界越来越重
- 第三风险是 mixed-package limbo，导致 V3 语义长期停留在过渡目录而没有收口
- 第四风险是 engine state leakage，把 invocation 恢复语义偷偷留在 engine 内部状态
- 每轮对话必须检查是否把新需求错误地建模成 phase / edge / subgraph
- 若出现这种倾向，应优先回到 doctrine 文档修正方向
