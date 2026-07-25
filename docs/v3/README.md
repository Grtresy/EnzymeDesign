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
8. [07-runtime-hpc-reliability.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/07-runtime-hpc-reliability.md)
9. [08-failure-recovery-and-scientific-attempts.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/08-failure-recovery-and-scientific-attempts.md)

架构审计与后续修正追踪：

- [architecture-qualification/README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/architecture-qualification/README.md)：closed invariant registry、真实 production-composition 场景、deterministic report/pure verifier 与 clean admission 操作合同。
- [harness-complexity-audit.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/harness-complexity-audit.md)
- [compatibility-sunset.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/compatibility-sunset.md)
- [runtime-hpc-reliability-operations.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/runtime-hpc-reliability-operations.md)：persistent SSH、durable operation、command drain 与 mutation scope 的启用、审计和回滚 runbook。
- [architecture-proposals/README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/architecture-proposals/README.md)：实施中发现、会影响 agent 发挥的大架构调整、umbrella 关系和生命周期索引；已实现 proposal 随对应 OpenSpec 归档，当前合同以稳定文档、代码和 OpenSpec checkpoint 为准。

AOX/HMM live cutover：

- [aox-hmm-blank-world-cutover.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/aox-hmm-blank-world-cutover.md)
- [aox-closure-stage-live-diagnostic.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/aox-closure-stage-live-diagnostic.md)：从 r59 cursor 614 只读事实构造 fresh logical fork，复用 production MICU/runtime/supervision/browser 边界，只验证 executor → reporter → master closure；永久不可进入 formal acceptance。
- 新 production attempt 使用 selected-chain `aox_blank_world_attempt_bundle@3`；
  历史 `@2` verifier 与 r48-r59 NO-GO evidence 保持冻结。r56 后的 target contract
  将 diagnostic live 与 exact-three formal acceptance 分开。post-r56 atomic closure
  rollover 与 crash-safe transition delivery 已实现并通过真实 file-backed SQLite
  concurrency/fault 回归；schema-disjoint 的 `authorize-diagnostic` /
  `run-diagnostic-live`、单槽 authority、diagnostic root/consumption/decision 与 cross-mode
  negative gate 也已实现。diagnostic 永久 `acceptance_eligible=false`，不能生成/进入
  `@3` bundle/reducer；现有 `authorize` / `run-live` 仍只代表 formal acceptance。
- `pin`、`preflight`、`run-live` 与 `run-diagnostic-live` 均先要求当前 clean commit 的 full architecture qualification report；qualification 通过本身只解除架构阻断，不创建 attempt，也不自动恢复 numbered campaign。无 attempt 的准备阶段止于 canonical `pin`；CLI `preflight` 会创建 blank-world attempt root，因此每个新 diagnostic 或 formal campaign 都必须另获 operator 授权并使用 fresh roots。r59 已永久 formal NO-GO；forward `@3` policy 将 canonically `closure_request_ready` 的 positive execution handoff 与 master closure 分开，并将 closure-request readiness 与 writer-gated Host finalization 分开，绝不从 sealed state 单独推断成功。该实现及非-live gate 不授权下一轮 diagnostic 或 formal live。
- `authorize-closure-stage-diagnostic` / `run-closure-stage-diagnostic-live` 是第三个 schema-disjoint operator flow：前者只发布一次性 plan，后者只在非 `rNN` fresh root 中恢复 cursor 614 等价状态并最多运行一次真实 MICU 收尾。源 r59 不写、科学 operation universe 不扩张、结果永久 `acceptance_eligible=false`；该 flow 不是 `run-diagnostic-live` 的别名，也没有 promotion/reducer/numbered continuation。

Execution pipeline SDK docs:

- [execution-pipeline-docs/README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/execution-pipeline-docs/README.md)

Versioned workflow knowledge packs:

- [workflow-packs/README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/workflow-packs/README.md)

执行约束：

- 后续 AI 在开始 V3 工作前，必须先读本目录至少 `README + 00-harness-doctrine.md + 与本次改动相关的稳定主题文档`。
- 涉及 V3 harness、agent runtime、protocol、scheduler 或 Host API 编排边界的修改，必须先读 `harness-complexity-audit.md`，并在修正对应问题后更新其中的复选框。
- 若实现选择与这些文档冲突，应优先更新文档并解释偏差，不能静默偏离。
- 实现 V3 execution 前必须先读 `03-capability-engines.md` 与 `execution-pipeline-docs/README.md`；默认执行工作面是 executor persistent sandbox + explicit artifact materialize/register/snapshot，不得继续依赖“Host 本地 artifact path 直接作为 HPC command path”的旧行为，也不得让 scheduler 自动替 executor 切换本地/HPC 后端。
