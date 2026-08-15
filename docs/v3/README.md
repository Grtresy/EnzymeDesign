# OpenZyme V3 文档入口

`docs/v3/` 是 OpenZyme V3 的独立规划与执行文档集。

V3 的核心立场：

- 这是一次 **harness-first** 的主线架构，不是对旧 supervisor graph 的局部修补。
- 顶层产品真状态从 `episode + phase graph` 转向 `session + task board + lane/workspace + approval + teammate work surface`。
- 旧 `episode + phase graph` 产品面已从主线删除；新工作不得恢复这些公共语义。
- `learn-claude-code` 是 V3 的方法论基线。
- LangGraph / LangChain 可以继续存在，但只能作为 `deep_research`、`execution` 等**内部能力引擎**的实现工具，不能重新成为产品级 workflow truth owner。
- Monorepo 包布局默认收敛为：`packages/openzyme-domain`、`packages/openzyme-core`、`packages/openzyme-engines`，避免重新拆出产品级 graph/storage 栈。
- effect-known ordinary failure 是 agent-readable observation，不是第二套 recovery workflow；
  Harness 不用 response veto 或 exact matcher规定 agent 的下一步策略。

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
- [test-gate.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/test-gate.md)：当前 optimized `scripts/check-mainline.sh` authority、focused/affected/replay 非权威边界、exact qualification ownership、resource-audited fixed parallelism、receipt、benchmark、forced-serial 与 rollback 合同。
- [harness-complexity-audit.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/harness-complexity-audit.md)
- [compatibility-sunset.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/compatibility-sunset.md)
- [runtime-hpc-reliability-operations.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/runtime-hpc-reliability-operations.md)：persistent SSH、durable operation、command drain 与 mutation scope 的启用、审计和回滚 runbook。
- [repository-service-operations.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/repository-service-operations.md)：project repository binding、独立 HTTPS Git/LFS transport、session pin、credential boundary、activation/retirement 与 backup/restore runbook。
- [architecture-proposals/README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/architecture-proposals/README.md)：实施中发现、会影响 agent 发挥的大架构调整、umbrella 关系和生命周期索引；已实现 proposal 随对应 OpenSpec 归档，当前合同以稳定文档、代码和 OpenSpec checkpoint 为准。

AOX/HMM cutover 与历史封存：

- [aox-artifact-cutover-supersession.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/aox-artifact-cutover-supersession.md)：当前权威 C0 治理入口；旧 AOX/HMM artifact cutover、c001 与 8.3--8.8 已固定为 legacy NO-GO、不可恢复、不可采纳且不得同步 main specs。
- [aox-hmm-blank-world-cutover.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/aox-hmm-blank-world-cutover.md)：只读历史合同与 incident 索引，不再是可执行 live change。
- [aox-r-series-codex-goal.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/aox-r-series-codex-goal.md)：只读历史 operator runbook；不得再由旧 change 启动 fresh R-series、repair 或 live，未来 cutover 必须使用另一个新 OpenSpec 和新 runbook。
- [aox-closure-stage-live-diagnostic.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/aox-closure-stage-live-diagnostic.md)：只读历史封存页。r65 已删除其 authority/reconstruction/live/CLI 可执行链；历史 SQLite/evidence 仍可离线核验，但永久不能进入 formal acceptance。
- 新 production attempt 使用 claim-bound selected-chain `aox_blank_world_attempt_bundle@4`；
  历史 `@2` verifier 与 r48-r59 NO-GO evidence 保持冻结。r56 后的 target contract
  将 diagnostic live 与 exact-three formal acceptance 分开。post-r56 atomic closure
  rollover 与 crash-safe transition delivery 已实现并通过真实 file-backed SQLite
  concurrency/fault 回归；schema-disjoint 的 `authorize-diagnostic` /
  `consume-diagnostic-authority` / `run-diagnostic-live`、单槽 authority、diagnostic
  root/consumption/decision 曾用于历史 diagnostic，post-r69 已删除其全部 current authority与
  runnable command，只保留 read-only cross-mode negative gate。
  diagnostic 永久 `acceptance_eligible=false`，不能生成/进入
  `@3` bundle/reducer；current product surface 不含 `run-live` / `run-diagnostic-live`。
- `pin` 与 `preflight` 均先要求当前 clean commit 的 full architecture qualification report；qualification 通过本身只解除架构阻断，不创建 attempt，也不自动恢复 numbered campaign。current pin transaction 原子封存 credential-free launch profile，authority/preflight/Host 复用其非敏感 settings，ambient 只补 credential。`preflight` 必须在 atomic slot claim/root 前重跑 actual Podman/image/SDK/`aox_sandbox_scientific_backend_probe@2` launch resolver 与 unchanged guard，通过后才发布 source-bound conductor execution contract；若 consumed authority 的 profile/config/actual runtime 在 claim 前失败，则只有 current source-bound preflight-failure receipt 的纯离线 verifier/decision 可以形成零-attempt canonical NO-GO，历史 r75 不回填。`serve-attempt` 在 process creation 前必须重验 closed root，以 pinned ledger baseline 原子 no-replace 发布 attempt-start claim并立即重读 ledger；child、startup/supervision、formal failure与public finalizer绑定同一claim/epoch，current finalizer不接受standalone MICU-before。claim后、child-ready前的safe sandbox bootstrap failure只有在live PID/PGID/start-time、process-group retirement、fresh root/zero state与unchanged MICU全部闭合时，才可经current pre-ready receipt进入current formal failure；无PID spawn failure只保留effect-unproven、retry-terminal、successor-blocked的最小typed blocker。历史r76/r82保持blocked且不回填。current conductor execution contract为`aox_public_conductor_execution_contract@4`，formal failure为`@3`，public profile/attempt bundle为`@4`；历史 conductor `aox_public_conductor_execution_contract@1` / `aox_public_conductor_execution_contract@2` / `aox_public_conductor_execution_contract@3` 只读且不得驱动新执行。formal CLI在Host调用前强制exact session create与唯一raw canonical message + pinned workflow entry，之后禁止第二条message与generic authorize；专用grant只从sealed bounded drain/terminal/唯一execution-task workspace read派生。drain可使用public schema内`1..100` signals/steps的任意bounded cadence，hidden enqueue固定关闭，历史`1/8`不再是evidence policy。Host退休前仍须封存retirement readiness。executor随后通过canonical lane tools和current-assignee `attempt.create`建立真实control；任何 non-live gate 都不授权下一 rNN 或 live。
- r78 已由 source-bound preflight-failure verifier/reducer形成 canonical `NO-GO`，不得重试或复用。r79 随后只启动 slot 1：唯一 attempt 已 admission 且保持 open，selection 缺失、provider/HPC operation 为零，bounded command 因 late-scope heartbeat authority 缺口以 `runtime_command_claim_expired` 停止；它没有 canonical GO/NO-GO decision，Host 按 readiness 合同保持 active。前向 runtime-command correction让scope打开后的每次heartbeat使用exact command-bound短writer；repository把精确mutation-guard rejection翻译为包内typed exception，worker不解析原始SQLite文本，只在当前lease内有界处理该authority-transition类型与SQLite contention。production qualification用真实authorized-renew Event屏障代替固定亚秒sleep；expired-claim no-replay、真实fence fail-closed及scientific lifecycle不变。r79不回填、不重试，slot 2/3与下一rNN均未获授权。
- post-r79 campaign `aox_campaign_b22dbb53d1e3a77b31ee69a6` 的唯一 attempt 已完成 NCBI/MAFFT/hmmbuild，但冻结 public final reads 时 HMMER 仍 `dispatching`，terminal handoff、report 与 verifier 均缺失，故 retirement readiness 拒绝且结论保持 blocked/noncanonical。稍后 private terminal state不能回填sequence 89-91的public snapshots；现行合同要求terminal status之后追加fresh sealed workspace/full events，non-live composition regression固定这一时序边界，不授权retry、successor或下一rNN。
- 该 incident 的前向生产修复继续复用通用 `ControlledOperationExecution`：migration `037` 封存 Host-private immutable provider dispatch/observation receipts，EBI HMMER submit-once 后按 bounded slice 只 poll exact job，`RETRY` 非终态，restart 复用接受时刻确定的绝对 deadline，terminal success 才 materialize，timeout 形成 `provider_timeout` terminal handoff。provider 接受但 job receipt 未落盘的 crash gap 保持 `dispatch_in_doubt` 且禁止重发；这不回填上述冻结 campaign，也不恢复 AOX observer/driver。
- r80 已发布并获批 exact plan，但唯一 `consume-authority` 调用把 `attempt-authority.json` 错组装为去后缀的 `attempt-authority.consumed.json`；canonical owner 因目标不匹配在 receipt 前 fail closed。authority 未消费且 product execution/effect 为零，故它是 preparation blocker，不是 formal/preflight failure、NO-GO 或 evidence gap，也不得回填或重试。前向 public consume/preflight 正常路径现从 canonical plan 的完整 basename 推导 `<plan-name>.consumed.json`；旧参数仅为 exact compatibility assertion，错误值继续在 receipt/root/effect 前拒绝，storage/schema/one-use 语义不变。
- r81 的 slot 1 建立唯一 open attempt，但 selection 缺失且 provider/HPC operation、report 均为零；selected manifest 被误送 `docs.read`、oversized artifact child path 被猜错，最后一个 ordinary known-effect error 又被 stale runtime projection重复标成 `failure_reconciliation_required`。Host 已按 authority deadline 安全退休，r81保持 blocked/noncanonical，无 canonical GO/NO-GO。前向 correction 只删除 ordinary failure 的第二份 attention、明确 `WorkflowRegistry`/`DocumentRegistry` owner，并给 `artifact.get` missing path 增加 bounded locality fields；不回填、重试或授权下一 rNN/live。
- closure-stage authority/reconstruction/live/CLI 已从 current product surface 退役。architecture qualification 只保留 historical run-class/attempt-id 的 formal non-adoption negative gate；不存在恢复旧 flow 的兼容命令。

Execution pipeline SDK docs:

- [execution-pipeline-docs/README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/execution-pipeline-docs/README.md)

Versioned workflow knowledge packs:

- [workflow-packs/README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/workflow-packs/README.md)

执行约束：

- 后续 AI 在开始 V3 工作前，必须先读本目录至少 `README + 00-harness-doctrine.md + 与本次改动相关的稳定主题文档`。
- 涉及 V3 harness、agent runtime、protocol、scheduler 或 Host API 编排边界的修改，必须先读 `harness-complexity-audit.md`，并在修正对应问题后更新其中的复选框。
- 若实现选择与这些文档冲突，应优先更新文档并解释偏差，不能静默偏离。
- 实现 V3 execution 前必须先读 `03-capability-engines.md` 与 `execution-pipeline-docs/README.md`；默认执行工作面是 executor persistent sandbox + explicit artifact materialize/register/snapshot，不得继续依赖“Host 本地 artifact path 直接作为 HPC command path”的旧行为，也不得让 scheduler 自动替 executor 切换本地/HPC 后端。
