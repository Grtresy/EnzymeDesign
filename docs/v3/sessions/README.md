# V3 AOX/HMM Session 实施索引

本目录曾定义五个连续 session，用来把 `reference/enz_miner_hmm_aox.ipynb` 代表的 AOX/HMM 挖掘流程迁移成 OpenZyme V3 的对话驱动工作流。

当前实现已按原 01-05 session 顺序落地。原任务型 session 文档已从本目录移除，不再作为未来实施队列维护；相关稳定 contract 以 `docs/OpenZyme架构设计.md`、`docs/v3/` 稳定文档和当前代码为准。

## 总目标

最终用户只通过提示词发起 AOX/HMM 挖掘。OpenZyme 应由 master 拆解任务，delegation 给 executor；executor 创建和修改 pipeline 源码 artifact，经 dry-run / approval 后提交受控 sandbox 执行；sandbox 只能通过 `openzyme_pipeline` SDK 请求 Host 托管能力；Host 负责 artifact catalog、网络数据库、HPC runner、approval、provenance 和 public workspace 投影。

`reference/enz_miner_hmm_aox.ipynb` 是流程基准，用来界定需要覆盖的生信步骤和输出形态。它不是执行对象，不能要求 OpenZyme 直接运行 notebook，也不能把 notebook 本地路径、conda 环境或临时目录作为产品接口。

## 已完成的 01-05 session

原 01-05 session 文档已删除，对应已完成的历史实施序列如下：

1. 可版本化 Pipeline 源码 Artifact。
2. Code Artifact 驱动 Execution。
3. Host 托管的生物数据库 SDK。
4. 生信工具链与 HPC SDK。
5. AOX/HMM 仅提示词端到端验收。

这些条目不再作为可继续推进的 session 文档入口。若需追溯逐 session 验收口径，请查看 git 历史；当前验收与架构约束以本索引下方稳定口径、`docs/v3/` 稳定文档和当前代码为准。

## 已锁定决策

| 主题 | 固定口径 |
| --- | --- |
| Pipeline 源码 artifact | 使用新增 `ArtifactKind.CODE`，`format="python"`，`metadata.semantic_type="pipeline_source"`。 |
| 源码版本 | 每次 patch 生成新的不可变 artifact；旧 artifact 不覆盖、不删除；metadata 记录 `parent_artifact_id`、`lineage_root_artifact_id`、`version` 和 `content_digest`。 |
| 源码编辑工具 | agent-facing 工具固定为 `artifact.create_text`、`artifact.read_text`、`artifact.patch_text`、`artifact.diff_text`。 |
| Patch 并发控制 | `artifact.patch_text` 必须带 `base_artifact_id` 和 `base_content_digest`；digest 不匹配时失败。 |
| Execution 源码入口 | `execution.pipeline.start` 只接受 `code_artifact_id`；传入 inline `code` 一律失败，错误码 `unsupported_inline_pipeline_code`。 |
| 缺少源码 artifact | `execution.pipeline.start` 缺少 `code_artifact_id` 时失败，错误码 `missing_code_artifact_id`。 |
| 源码 provenance | dry-run、approval、run、engine invocation、output artifact 和 workspace projection 必须记录 `source_code_artifact_id`、`source_code_digest`、`source_code_version`。 |
| 网络数据库 SDK | 新增 `openzyme_pipeline.bio`；Host 托管 NCBI、UniProt、EBI HMMER REST，sandbox 不直接联网。 |
| Bio SDK 函数 | 首批函数固定为 `bio.ncbi_fetch_proteins(...)`、`bio.uniprot_fetch(...)`、`bio.hmmer_search(...)`。 |
| 生信工具 SDK | 新增 `openzyme_pipeline.bio_tools`；MAFFT、CD-HIT、HMMER CLI 统一走该模块。 |
| Bio tools 函数 | 首批函数固定为 `bio_tools.cdhit(...)`、`bio_tools.mafft(...)`、`bio_tools.hmmbuild(...)`、`bio_tools.hmmalign(...)`、`bio_tools.hmmer_search_cli(...)`。 |
| CLI 执行边界 | Pipeline code 不直接 shell/subprocess 调 MAFFT、CD-HIT、HMMER binary；Host supervisor 决定本地受控执行还是 HPC runner。 |
| Approval | AOX/HMM 使用单一 dry-run plan approval；运行时出现未批准操作或参数漂移时再发起二次 approval。 |
| 验收场景 | Session 05 使用固定 13 个 AOX accession；fixture/unit 必过，opt-in `live_e2e` 才算真实 cutover。 |

## 共同边界

- 继续遵守 V3 `session + task board + lane/workspace + approval + resident teammate + explicit runtime/drain` 产品语义。
- `POST /v3/sessions/{session_id}/messages` 只作为用户到 master 的入口，不隐式执行 bounded teammate runtime drain。
- execution teammate 不直接调用 runner、SSH、Slurm 或 runner config，只提交 `execution.pipeline.*`。
- sandbox 默认无网络、非 root、资源受限；所有外部网络数据库调用由 Host 托管。
- public workspace、agent tool result 和 events 不暴露源码全文、Host path、sandbox host path、runner path、`storage_uri`、SSH/Slurm 配置或凭证。
- task 业务终态必须由 agent 显式 `task.update` 或已文档化机械迁移写入，不能把 runtime idle、max steps、tool result 或 protocol message 自动当作 completed。
- provider/runtime 异常应显式失败；tool 参数错误返回 LLM 可读的结构化 tool error；不能静默 fallback 到替代 plan。

## Sandbox/Host Supervisor 共同约束

- Host-supervised SDK RPC 失败必须返回结构化错误字段：`error_code`、`stage`、`retryable`、`hint`、`details`。同一失败还必须能从 execution status、events 和 workspace 安全投影中追踪，不能只停留在 sandbox 内部日志。
- RPC payload 只返回 bounded summary、artifact refs、状态和必要 warning；大型 FASTA、metadata、raw hits、parsed hits、tool outputs 或 intermediate results 必须登记为 artifact。stdout/stderr 必须有 size cap；超限时 RPC/result 只返回截断摘要和完整日志 artifact ref。
- AOX/HMM 关键输出登记前必须做轻量格式校验。FASTA、HMM、MSA、CSV、`nodes.csv`、`edges_similarity.csv` 等 artifact 存在但格式不合法、必需列缺失或为空时，不能把该 operation 记为成功。
- sandbox 临时 workspace 必须有默认清理/保留策略。成功运行清理临时 workdir，只保留已登记 artifact、摘要和 provenance；失败运行保留诊断所需的截断日志、完整日志 artifact、registered outputs 和结构化错误事件，但不暴露 Host path、sandbox host path 或 runner path。

## 验收口径

每个 session 的实现完成后，验收必须至少覆盖：

- control-plane canonical state 是否记录 session、task、lane、approval、engine invocation、artifact、run 和 provenance 关系。
- workspace projection 是否只暴露安全投影，并能让 UI/CLI/agent 理解共享工作面。
- dry-run 是否能在提交真实网络/HPC 工作前暴露 artifact reads、SDK operations、expected outputs、资源/配额估计和 approval 需求。
- 所有失败是否有结构化错误码、可读摘要和可追踪事件，而不是静默降级。
- RPC/result 是否只返回 bounded summary；大结果、完整日志和大型中间产物是否 artifact 化，并带有可追踪 artifact ref。
- 关键 AOX/HMM 输出是否通过最小格式校验；仅路径存在但格式错误或必需列缺失不能算通过。
- sandbox 临时 workspace 是否按成功清理、失败保留诊断材料的默认策略执行，且安全投影不泄露内部路径。
- 文档、接口、测试和 implementation anchors 是否同步。
- unit/fixture tests 是否覆盖 CODE artifact 版本化、`code_artifact_id` execution、bio SDK、bio_tools SDK、single plan approval。
- opt-in `live_e2e` 是否覆盖真实 NCBI、UniProt、EBI HMMER 与 HPC 配置；缺配置时只能报告 `prerequisite missing`，不能记为通过。
- end-to-end gate 是否从用户提示词进入，且没有手工构造 execution invocation 绕过 master、executor、approval 或 scheduler。

原 Session 05 的端到端验收口径已沉淀为当前 AOX/HMM fixture/live gate 约束。Cytoscape GUI 不纳入硬验收，只要求产出可导入的节点/边表。
