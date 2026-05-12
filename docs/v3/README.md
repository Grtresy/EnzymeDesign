# OpenZyme V3 文档入口

`docs/v3/` 是 OpenZyme V3 的独立规划与执行文档集。

V3 的核心立场：

- 这是一次 **harness-first** 的版本升级，不是对 V2 supervisor graph 的局部修补。
- V2 视为冻结并准备废弃的路线；V3 不以延续 V2 产品模型为目标。
- 顶层产品真状态从 `episode + phase graph` 转向 `session + task board + lane/workspace + approval + teammate work surface`。
- `learn-claude-code` 是 V3 的方法论基线。
- LangGraph / LangChain 可以继续存在，但只能作为 `deep_research`、`execution` 等**内部能力引擎**的实现工具，不能重新成为产品级 workflow truth owner。
- Monorepo 包布局默认收敛为：`packages/openzyme-domain`、`packages/openzyme-core`、`packages/openzyme-engines`，避免沿着 V2 的 `runtime/storage/tools/graph` 继续过细拆分。

先读文档顺序：

1. [00-harness-doctrine.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/00-harness-doctrine.md)
2. [01-target-architecture.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/01-target-architecture.md)
3. [02-control-plane.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/02-control-plane.md)
4. [03-capability-engines.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/03-capability-engines.md)
5. [04-public-interfaces.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/04-public-interfaces.md)
6. [05-migration-roadmap.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/05-migration-roadmap.md)

架构审计与后续修正追踪：

- [harness-complexity-audit.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/harness-complexity-audit.md)

按对话执行的任务包：

1. [sessions/01-doc-pack.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/sessions/01-doc-pack.md)
2. [sessions/02-control-plane-schema.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/sessions/02-control-plane-schema.md)
3. [sessions/03-harness-kernel.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/sessions/03-harness-kernel.md)
4. [sessions/04-task-board.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/sessions/04-task-board.md)
5. [sessions/07-lane-isolation.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/sessions/07-lane-isolation.md)
6. [sessions/05-memory-and-skills.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/sessions/05-memory-and-skills.md)
7. [sessions/06-background-and-protocols.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/sessions/06-background-and-protocols.md)
8. [sessions/08-deep-research-engine.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/sessions/08-deep-research-engine.md)
9. [sessions/09-execution-engine.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/sessions/09-execution-engine.md)
10. [sessions/10-report-drafts-and-projections.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/sessions/10-report-drafts-and-projections.md)
11. [sessions/11-v3-api-cli-ui.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/sessions/11-v3-api-cli-ui.md)
12. [sessions/12-cutover-and-evals.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/sessions/12-cutover-and-evals.md)

Execution pipeline SDK docs:

- [execution-pipeline-docs/README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/execution-pipeline-docs/README.md)

执行约束：

- 后续 AI 在开始 V3 工作前，必须先读本目录至少 `README + doctrine + 对应 session 文档`。
- 涉及 V3 harness、agent runtime、protocol、scheduler 或 Host API 编排边界的修改，必须先读 `harness-complexity-audit.md`，并在修正对应问题后更新其中的复选框。
- 若实现选择与这些文档冲突，应优先更新文档并解释偏差，不能静默偏离。
- 若涉及对现有 `docs/OpenZyme架构设计.md` 的回写，必须单独征求用户确认。
- 实现 V3 execution 前必须先读 `sessions/09-execution-engine.md`；不得继续依赖“Host 本地 artifact path 直接作为 HPC command path”的旧行为。
