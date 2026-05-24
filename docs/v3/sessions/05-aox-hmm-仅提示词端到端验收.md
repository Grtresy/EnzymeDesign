# Session 05：AOX/HMM 仅提示词端到端验收

## 目标

定义最终端到端验收：用户只用自然语言提示词要求运行 AOX/HMM 挖掘，OpenZyme 通过 V3 agent team 完成任务拆解、源码 artifact 编写与修订、dry-run、approval、受控 sandbox/SDK 执行、结果 artifact 登记、executor 总结和 master 面向用户回复。

验收目标是产出与 `reference/enz_miner_hmm_aox.ipynb` 对齐的可追溯 AOX/HMM 挖掘结果，不是直接运行 notebook。

## 当前缺口

- Session 01-04 未完成前，系统缺少源码 artifact、code artifact execution、Host 托管 bio SDK 和 AOX/HMM 工具链。
- 当前 V3 workflow 需要验证 master delegation、executor task 终态、approval、runtime signal、workspace projection、artifact provenance 和 final answer 是否能串成完整产品路径。
- notebook 的 Cytoscape GUI 操作不适合作为自动端到端硬验收，需要改为可导入图表 artifact。

## 实施范围

- 准备一条固定用户提示词，要求基于 13 个 AOX accession 构建 HMM，搜索目标蛋白库，过滤并导出候选。
- 固定 AOX accession：
  - `AAC72747.1`
  - `KDQ24956.1`
  - `9AVH_A`
  - `XP_014653549.1`
  - `KIS68002.1`
  - `XP_003660923.1`
  - `AMW87253.1`
  - `AFP17823.1`
  - `WP_190019735.1`
  - `WP_138089821.1`
  - `WP_176407597.1`
  - `CAQ19343.1`
  - `CAQ19344.1`
- master 将需求分解为明确 task，并通过 `task.delegate` 委派给 executor。
- executor 读取 execution SDK docs，创建 pipeline 源码 artifact。
- executor 对 pipeline 源码进行必要 patch，生成新版本并记录 diff。
- executor 使用 `execution.pipeline.start(code_artifact_id=..., dry_run=true)` 生成 plan。
- Host 返回 artifact reads、bio SDK operations、toolchain/HPC operations、expected outputs、resource/quota estimate 和 approval request。
- 用户或测试 harness 通过正式 approval 入口批准单一 dry-run plan。
- 正式执行必须使用与批准 plan 相同的 `source_code_digest`、artifact reads、SDK operations、toolchain/HPC operations、expected outputs 和参数摘要。
- 运行时出现未批准 operation、资源等级变化、provider 范围变化或参数漂移时，必须暂停并发起二次 approval。
- scheduler/runtime 推进 execution；sandbox 通过 `openzyme_pipeline.bio`、`openzyme_pipeline.bio_tools`、`artifacts` 和 Host-supervised HPC 完成工作。
- Host 登记所有结果 artifact、run、events、provenance、结构化 RPC/toolchain 错误、截断日志摘要和必要的完整日志 artifact。
- executor 读取 execution status 与 artifacts，写入 task result。
- master 汇总 executor 结果，回答用户可用 artifact、候选数量、过滤规则、关键失败/警告和后续可执行动作。

## 接口变化

- 不引入新的基础接口；本 session 组合验证 Session 01-04 的接口。
- 允许为验收补充 fixture、eval driver 或 seeded live smoke，但这些不能替代真实产品 contract。
- workspace projection 必须足够展示 conversation、task board、delegation、pending approvals、execution invocation、runs、artifacts、events 和 final answer。
- 所有 artifact provenance 必须回链到 source code artifact、code digest、input/source artifacts、provider requests、toolchain/HPC operations、task/lane/invocation/run。
- workspace/events/execution status 必须能追踪结构化错误字段：`error_code`、`stage`、`retryable`、`hint`、`details`。
- RPC/result 必须只返回 bounded summary；大型 provider/toolchain 结果和完整日志必须通过 artifact refs 暴露，stdout/stderr 截断状态必须在 workspace 或 events 中可见。
- 关键输出 artifact 必须通过轻量格式校验；FASTA、HMM、MSA、CSV、nodes/edges 表只存在文件路径但格式不合格时，端到端验收失败。
- 失败场景不能把 task 自动标记 completed；失败运行必须保留可诊断的结构化错误、截断日志、完整日志 artifact ref 和已登记 outputs。
- fixture/unit tests 必须覆盖完整控制流和 artifact/provenance contract。
- opt-in `live_e2e` 必须覆盖真实 NCBI、UniProt、EBI HMMER 与 HPC 配置；缺配置时只能报告 `prerequisite missing`，不能记为通过。

## 实现锚点

- 本地 fixture gate 位于 `apps/openzyme-host-api/src/openzyme_host_api/evals.py` 的 `v3_aox_hmm_prompt_e2e` scenario，并由 `apps/openzyme-host-api/tests/test_evals.py` 验证。
- 该 gate 只从 `POST /v3/sessions/{session_id}/messages` 的单条自然语言 prompt 进入；fixture model 只负责确定性地模拟 master/executor 决策，不预先构造 execution invocation。
- executor 先创建 pipeline source artifact，再 patch 生成 v2 source，调用 `artifact.diff_text` 留下 diff，随后执行 `execution.pipeline.start(..., dry_run=true)` 与 `execution.pipeline.start(..., inputs={"approval_policy": "single_plan"})`。
- approval 仍通过正式 `POST /v3/approvals/{approval_id}/resolve` 路径完成；approval resolved 后由 runtime/scheduler 唤醒 executor 读取 `execution.pipeline.status` 并显式 `task.update(status="completed")`。
- fixture sandbox 通过 Host supervisor control handler 调用 `bio.*` 与 `bio_tools.*`，并返回 filtered/candidate/scoring/nodes/edges 等派生 artifacts；派生输出携带 `format` 与 `required_columns`，由 sandbox registration 校验覆盖。

## 测试/验收

端到端验收必须从用户提示词开始，不能手工预先创建 execution invocation 来绕过 master/executor 流程。最小验收路径：

1. 用户发送 AOX/HMM 挖掘提示词到 `POST /v3/sessions/{session_id}/messages`。
2. master 创建 task 并 delegation 给 executor。
3. executor 创建或 patch pipeline 源码 artifact。
4. executor 发起 `code_artifact_id` dry-run。
5. approval 通过后，runtime/scheduler 推进正式执行。
6. Host 登记结果 artifact 和 events。
7. executor 显式更新 task 终态。
8. master 产生面向用户的最终回答。

验收产物必须包括：

- Reference FASTA artifact。
- Reference metadata CSV/JSON artifact。
- CD-HIT 90 reference FASTA artifact。
- MAFFT alignment artifact。
- HMM artifact。
- HMMER raw hits artifact。
- HMMER parsed hits CSV artifact。
- Filtered FASTA artifact。
- Filtered CSV artifact。
- Scoring CSV artifact。
- Candidate FASTA artifact。
- Candidate CSV artifact。
- CD-HIT 85 candidate FASTA artifact。
- `nodes.csv` artifact。
- `edges_similarity.csv` artifact。
- execution summary，包含候选数量、过滤阈值、工具版本、provider 摘要、失败/警告和关键 artifact ids。

验收还必须检查：

- workspace artifact projection 不暴露 Host path、sandbox host path、runner path、SSH/Slurm config、credentials 或 `storage_uri`。
- output artifact provenance 包含 `source_code_artifact_id`、`source_code_digest`、provider/toolchain/HPC 来源和 input artifact ids。
- provider/toolchain/HPC 失败时，task 不被自动标记 completed；executor 必须显式处理失败并更新 task。
- provider/toolchain/HPC 失败时，workspace/events/execution status 必须暴露结构化错误字段，且失败 logs/registered outputs 可用于诊断。
- 大结果必须 artifact 化，RPC/result 中只能看到摘要和 artifact refs；stdout/stderr 超限时必须能看到截断摘要和完整日志 artifact ref。
- Reference FASTA、HMM、alignment、parsed hits、filtered CSV、candidate CSV、`nodes.csv`、`edges_similarity.csv` 等关键输出必须通过最小格式或必需列校验。
- live/provider/HPC 配置缺失时，报告为 prerequisite missing，不计为通过。
- Cytoscape GUI 不作为硬验收；只要求输出可导入的节点/边表。
- fixture/unit gate 必须通过才允许运行 `live_e2e`。
- `live_e2e` gate 必须从用户提示词进入，不能手工构造 execution invocation 绕过 master、executor、approval 或 scheduler。

## 明确不做什么

- 不直接运行 `reference/enz_miner_hmm_aox.ipynb`。
- 不把 notebook 输出目录 `aox_work/` 当成 artifact catalog。
- 不要求人工在 Cytoscape GUI 中打开网络作为通过条件。
- 不通过手工调用内部 engine 或构造数据库状态绕过用户提示词、master、executor、approval 或 scheduler。
- 不把 seeded smoke、单独 live gate 或 collection 成功说成完整产品完成。
