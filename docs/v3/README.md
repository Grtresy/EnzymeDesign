# OpenZyme V3 文档入口

`docs/v3/` 是 OpenZyme V3 的独立规划与执行文档集。

V3 的核心立场：

- 这是一次 **harness-first** 的主线架构，不是对旧 supervisor graph 的局部修补。
- 顶层产品真状态从 `episode + phase graph` 转向 `session + task board + lane/workspace + approval + teammate work surface`。
- 旧 `episode + phase graph` 产品面已从主线删除；新工作不得恢复这些公共语义。
- `learn-claude-code` 是 V3 的方法论基线。
- LangGraph / LangChain 可以继续存在，但只能作为 `deep_research`、`execution` 等**内部能力引擎**的实现工具，不能重新成为产品级 workflow truth owner。
- Monorepo 包布局默认收敛为：`packages/openzyme-domain`、`packages/openzyme-core`、`packages/openzyme-engines`，避免重新拆出产品级 graph/storage 栈。

先读文档顺序：

1. [00-harness-doctrine.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/00-harness-doctrine.md)
2. [01-target-architecture.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/01-target-architecture.md)
3. [02-control-plane.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/02-control-plane.md)
4. [03-capability-engines.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/03-capability-engines.md)
5. [04-public-interfaces.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/04-public-interfaces.md)
6. [05-agent-runtime.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/05-agent-runtime.md)
7. [06-top-level-llm-loop.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/06-top-level-llm-loop.md)

架构审计与后续修正追踪：

- [harness-complexity-audit.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/harness-complexity-audit.md)
- [compatibility-sunset.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/compatibility-sunset.md)
- [architecture-proposals/README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/architecture-proposals/README.md)：实施中发现、会影响 agent 发挥且需要大架构调整的问题逐项单独记录，当前 Goal 不实施这些提案。

AOX/HMM live cutover：

- [aox-hmm-blank-world-cutover.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/aox-hmm-blank-world-cutover.md)

Execution pipeline SDK docs:

- [execution-pipeline-docs/README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/execution-pipeline-docs/README.md)

Versioned workflow knowledge packs:

- [workflow-packs/README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/workflow-packs/README.md)

执行约束：

- 后续 AI 在开始 V3 工作前，必须先读本目录至少 `README + 00-harness-doctrine.md + 与本次改动相关的稳定主题文档`。
- 涉及 V3 harness、agent runtime、protocol、scheduler 或 Host API 编排边界的修改，必须先读 `harness-complexity-audit.md`，并在修正对应问题后更新其中的复选框。
- 若实现选择与这些文档冲突，应优先更新文档并解释偏差，不能静默偏离。
- 实现 V3 execution 前必须先读 `03-capability-engines.md` 与 `execution-pipeline-docs/README.md`；默认执行工作面是 executor persistent sandbox + explicit artifact materialize/register/snapshot，不得继续依赖“Host 本地 artifact path 直接作为 HPC command path”的旧行为，也不得让 scheduler 自动替 executor 切换本地/HPC 后端。
