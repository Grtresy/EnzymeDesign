# V3 AOX/HMM Session 实施索引

本目录只保留尚需推进或作为证据输入的 session。已经落地的早期任务型 session 不再作为未来实施队列维护；其稳定 contract 已沉淀到 `docs/OpenZyme架构设计.md`、`docs/v3/03-capability-engines.md`、`docs/v3/04-public-interfaces.md`、`docs/v3/05-agent-runtime.md` 与 `docs/v3/execution-pipeline-docs/`。

当前主线从 Session 06 开始：先保留 AOX/HMM 外部 provider / tool / HPC prerequisite 证据，再补 persistent executor sandbox 底座，随后在新底座上分层定义 Host-supervised bridge、HPC placement/file-transfer SDK、真实 adapter 和 live cutover。

## 总目标

最终用户只通过提示词发起 AOX/HMM 挖掘。OpenZyme 应由 master 拆解任务并委派给 executor；executor 在自己的 persistent sandbox workspace 中迭代脚本、运行本地 Python/bash 操作、检查中间文件，并通过 Host-supervised SDK 请求外部 provider、HPC bio tools 和 artifact catalog。sandbox 是 working copy/cache，artifact catalog、task board、engine invocation、run 和 report 才是 canonical state。

`reference/enz_miner_hmm_aox.ipynb` 是流程基准，用来界定需要覆盖的生信步骤和输出形态。它不是执行对象，不能要求 OpenZyme 直接运行 notebook，也不能把 notebook 本地路径、conda 环境或临时目录作为产品接口。

## Session 顺序

6. [06-adapter-foundation-exploration.md](06-adapter-foundation-exploration.md)
7. [07-persistent-executor-sandbox-foundation.md](07-persistent-executor-sandbox-foundation.md)
8. [08-sandbox-artifact-boundary.md](08-sandbox-artifact-boundary.md)
9. [09-sandbox-file-command-runtime.md](09-sandbox-file-command-runtime.md)
10. [10-sandbox-external-capability-bridge.md](10-sandbox-external-capability-bridge.md)
11. [11-domain-sdk-boundary-after-sandbox.md](11-domain-sdk-boundary-after-sandbox.md)
12. [12-unified-bio-tool-adapter-contract.md](12-unified-bio-tool-adapter-contract.md)
13. [13-real-bio-provider-adapters.md](13-real-bio-provider-adapters.md)
14. [14-real-bio-tools-local-hpc-backends.md](14-real-bio-tools-local-hpc-backends.md)
15. [15-aox-hmm-cutover-live-e2e.md](15-aox-hmm-cutover-live-e2e.md)

辅助材料：

- [06-adapter-foundation-evidence.md](06-adapter-foundation-evidence.md)：Session 06 的安全 evidence matrix。

这些 session 是实施顺序，不是可自由重排的备选方案。Session 06 只记录当前环境证据；Session 07-09 先建立 persistent sandbox 工作面、artifact 边界和 file/command runtime；Session 10 只建立 Host-supervised SDK supervisor RPC 底座、approval 阻塞/恢复和 backend route 冻结；Session 11 再定义 public SDK 的领域 operation 与 `hpc` placement/file-transfer 边界；Session 12 将 S11 的 public SDK operation 统一映射到 adapter envelope；Session 13-14 接入真实 provider/tool backend；Session 15 才证明 AOX/HMM prompt E2E cutover。

Session 07-10 的职责切分固定如下：

- Session 07 只做 foundation：executor sandbox base image registry / bootstrap contract、`session_id + agent_member_id` 级 `sandbox_workspace_id` identity、持久目录/volume、manifest、quota、安全 projection、`sandbox.workspace.status` 和隔离验收。
- Session 08 负责 sandbox working copy 与 artifact catalog 的边界：materialize、register、snapshot code 和 provenance。
- Session 09 负责 file CRUD 与 `sandbox.exec` command runtime，接线 S08 source snapshot preflight，并验收 base image 中的 Python/bash 交互、`openzyme_pipeline` SDK import 和 Host supervisor RPC transport smoke；普通 command recovery 采用 fail-closed，SDK controlled-operation approval 阻塞/恢复语义由 Session 10 验收。
- Session 10 负责 SDK supervisor RPC substrate：受控 SDK call 拦截、generic operation digest、approval 阻塞/恢复、backend category route freezing 和结构化失败；approve 后恢复同一个 blocked SDK RPC / sandbox continuation，agent loop 只在 `sandbox.exec` tool result 返回后继续；不定义最终 public SDK import surface、领域 operation、HPC workspace/file-transfer API、adapter envelope 或真实 runner 上传下载。
- Session 11 负责 public SDK 分层：`bio` / `bio_tools` / `structure_tools` / `docking` 表达领域 operation，`hpc` 表达 execution placement、remote workspace 和声明式 stage/fetch。
- Session 12 负责把 S11 的 public SDK operation、placement、stage/fetch declarations 统一映射到 adapter envelope、approval/provenance fields 和 drift 检测。
- Session 13 负责把真实 NCBI、UniProt 和 EBI HMMER REST provider 接到 S12 envelope 后面，并消除产品默认路径里的 deterministic provider fallback。
- Session 14 负责把真实 HPC runner stage/run/fetch 接到上述 SDK contract 后面，并以 `bio_tools.cdhit`、`bio_tools.mafft`、`bio_tools.hmmbuild`、`bio_tools.hmmalign` 作为本 session 完成门槛；`bio_tools.hmmer_search_cli` 在 S14 route policy 中先固定为 `disabled/unsupported_in_s14`，不阻塞 S14 完成。

## 已完成并沉淀的早期 contract

早期 01-05 任务型 session 已从本目录移除。实现与规范仍保留在 git 历史和稳定文档中，当前后续工作只需遵守以下沉淀后的 contract：

| 主题 | 稳定口径 |
| --- | --- |
| CODE artifact | `ArtifactKind.CODE` 表示执行相关源码的不可变审计快照，记录 `content_digest`、lineage、version 与 producer metadata。 |
| Code snapshot | executor 日常编辑在 persistent sandbox workspace 内完成；需要 approval、外部 SDK operation、执行审计或结果追踪时，由 Host snapshot 相关源码为 CODE artifact。 |
| Sandbox execution | `sandbox.exec` 是 executor-facing 唯一执行入口；execution/run/SDK operation 是 Host 内部 canonical state，不作为 agent-facing `execution.*` tool 暴露。 |
| SDK operation approval | 代码运行中触发受控 SDK call 时，Host supervisor 根据 operation digest 判断是否已有 approval；缺 approval 则同步阻塞该 SDK call、创建 Web UI approval，approve 后继续同一 call，reject 后向 sandbox 代码抛结构化异常。 |
| Provenance | approval、sandbox run、SDK operation、backend run、output artifact 和 workspace projection 必须能回链到 `source_code_artifact_id`、digest、`sandbox_workspace_id`、input artifact digests、operation set 和 backend route。 |
| Bio SDK | NCBI、UniProt、EBI HMMER 等网络 provider 请求由 Host 托管执行，sandbox 不直接持有 credential 或 Host cache path。 |
| Bio tools SDK | MAFFT、CD-HIT、HMMER CLI 等外部工具由 Host supervisor 受控执行；sandbox 可以做 Python/bash 派生处理，但不能直接接触 Host/HPC private path、runner config 或 provider secret。 |
| HPC placement | `hpc` 不退役为纯兼容层；它是 executor-facing placement / remote workspace / declarative stage-fetch namespace。领域能力可以迁到 `structure_tools` / `docking` / `bio_tools`，但 HPC 文件流必须在 plan/code 中显式表达。 |
| AOX/HMM fixture | fixture/unit 只能证明 contract、schema、控制流和 artifact/provenance；不能证明真实 provider/toolchain/HPC cutover。 |

## Persistent Sandbox 共同边界

- 每个 executor 拥有独立、持久化、可恢复的 sandbox workspace；`sandbox_workspace_id` 按 `session_id + agent_member_id` 复用，`agent_id` 只作为展示/兼容字段，`task_id` / `lane_id` 只是当前 focus metadata；容器可重启，sandbox workspace volume 保留。
- 默认多个 executor 使用同一个 Host-configured sandbox base image digest，分别启动各自的 rootless container process 并挂载各自的 `/workspace` volume。持久化对象是 sandbox workspace volume、manifest、projection summary 和 canonical records，不是容器进程或 container id。
- executor sandbox base image 由 Session 07 的 Host-level registry / bootstrap contract 管理，至少记录 `image_ref`、`image_digest`、最低能力声明和版本兼容；缺失或不兼容必须返回 `sandbox_image_missing` / `sandbox_image_incompatible`，不能自动 pull/build、自动换镜像或 fallback 到旧 pipeline runner。
- MAFFT、CD-HIT、HMMER、HPC runner、HPC runtime packaging 和领域 toolchain packaging 不属于 executor base image，由 Session 14 或后续 backend/toolchain registry 管理。
- 持久化目录只以 `/workspace` 为长期模型，默认包含 `/workspace/src`、`/workspace/input`、`/workspace/work`、`/workspace/output`、`/workspace/logs` 和 `/workspace/manifest`；`/openzyme/control.sock` 是运行时 IPC，不持久化，旧 `/openzyme/input|work|output|logs` 只能作为兼容视图或实现细节。
- sandbox 内 executor 可以做文件 CRUD、bash、python、脚本迭代和中间结果检查。
- sandbox 外能力只能通过 Host-supervised SDK 或 agent-facing `sandbox.*` 工具进入；不得挂载 Host repo、用户 home、`.ssh`、runner config、provider credential、数据库 private mount 或 HPC secret。
- sandbox workspace 是 working copy/cache，不是 canonical truth。共享、汇报、复用或审批相关结果必须登记回 artifact catalog 或 snapshot 为 CODE artifact。
- scheduler 只推进已排队/已批准的 deterministic action，不规划 workflow、不选择 backend、不自动 fallback、不自动把 task 标记 completed。
- backend route 一旦进入 approved SDK operation 必须冻结；provider/HPC backend 失败只产生结构化失败。是否换 route 由 executor 读取异常后修改 sandbox workspace 或参数，再重新运行 `sandbox.exec`。
- Session 10 的 bridge 只能依赖 generic controlled-operation record、canonical digest、Host-owned continuation state 和 bounded RPC envelope；最终 public SDK 名称、typed params、placement/stage/fetch 字段和 adapter envelope 由 Session 11/12 锁定，不能在 bridge 底座里提前隐式定型。
- executor 可以通过 `hpc` placement API 声明远端 workspace、artifact staging、workspace-relative target path、declared outputs 和 fetch/register 意图；真实上传、下载、runner 调用、权限校验、审批和 provenance 由 Host supervisor 执行。
- RPC/result 只返回 bounded summary、artifact refs、状态和必要 warning；大型 FASTA、metadata、raw hits、parsed hits、tool outputs、中间文件和完整日志必须 artifact 化或保留在受控 sandbox workspace snapshot 中。
- public workspace、agent tool result 和 events 不暴露 Host path、sandbox host path、runner path、`storage_uri`、SSH/Slurm 配置或凭证。

## Resource Identity / Lifecycle Checklist

Session 08 之后凡新增对象、字段、registry、workspace、run、artifact、backend、provider、runner 或 projection 字段，必须同时写清：

- identity：稳定 id 如何生成，是否由用户可控 label 参与，label 如何 normalize。
- owner：哪个 Host service / registry 创建、更新、恢复和删除。
- lifecycle：何时创建、attach、复用、完成、失败、恢复、retire 或 cleanup。
- persistence：哪些是 canonical/persistent state，哪些只是 disposable runtime envelope。
- compatibility/versioning：schema、policy、image、toolchain、provider 或 adapter 版本不兼容时如何失败。
- error semantics：固定结构化错误码和 agent/user 可见状态。
- fallback policy：哪些 retry、fallback、auto install、auto route、fixture/synthetic substitution 明确禁止。
- session split：当前 session 锁定 contract 的范围，以及后续 session 只实现或扩展哪一层。

跨 session 默认值：

- `artifacts.materialize()` 对同一 `sandbox_workspace_id + artifact_id + artifact_digest + target_path + mode` 幂等复用；目标路径已有不同 digest 内容时结构化失败。
- 同一 `sandbox_workspace_id` 同时只允许一个 active `sandbox.exec`；file read/list 可并发，写操作与 exec 的并发策略由 Session 09 固定为 fail-closed。普通 `sandbox.exec` 在 Host 重启、stale lock 或 process state 丢失时也 fail-closed 为结构化失败，释放 active lock 并唤醒 executor 重新运行；S10 只接管 SDK controlled-operation approval continuation 的 pause/resume 语义。
- Session 10 approval 在同一 session 内按完整 `operation_digest` 复用；digest 漂移必须重新审批或结构化失败。S10 的 approval resolve 不通过 `AgentRuntimeSignal(APPROVAL_RESOLVED)` 直接恢复 agent turn，而是先恢复 Host supervisor 持有的 blocked SDK RPC / sandbox continuation；`sandbox.exec` 返回 tool result 后 agent loop 才继续。
- `hpc.workspace(label)` 按 `sandbox_workspace_id + normalized_label` 复用。它是 executor sandbox workspace 下的 labeled remote placement workspace，不暴露真实远端路径。
- S11 `hpc.stage_artifact(...)` 必须基于 S08 visible immutable artifact record 和 sealed artifact digest/tree digest；缺 digest、跨 session artifact、mutable sandbox path、Host path、runner path 或 `storage_uri` 都 fail-closed，不允许用 `artifact_id` 兜底。
- S11 `hpc.fetch_outputs(...)` 必须经 S08 `ArtifactBoundaryService` validation、copy/seal、sealed digest recheck 和 immutable Artifact row commit 后返回 canonical artifact refs；S14 只实现真实 runner transfer/run/fetch，不重新定义 artifact canonicality。
- S11 完成不能只看 SDK 名称是否存在；`stage_artifact` 的 digest fallback、operation 完成时 eager persist visible artifacts、以及 `fetch_outputs` 只列出现有 artifact record 都是 completion blockers。
- Provider cache 只允许作为 Host-private optimization；cache key/digest 可进 provenance，但 cache hit 不能作为 live cutover passed 证据。
- Session 15 live cutover 必须在显式 S15 eval result 中生成 sealed inline evidence payload 与 `evidence_bundle_digest`，回链 prompt、配置 snapshot、image/toolchain/route/provider digest、approval、operation trace、artifact ids 和 final answer；不新增顶层 control-plane 真状态。

## 后续口径冻结点

- 旧 “移除 agent-facing `openzyme_pipeline.hpc`” 结论废弃。Session 11 必须保留 `hpc` 作为 first-class placement / remote workspace / declarative stage-fetch namespace；fpocket / Vina 等领域操作必须放在 `structure_tools` / `docking` 下，旧 runner-backed shorthand 不进入 agent-facing public SDK / docs / examples / prompt。
- 旧 `execution.pipeline.start(code_artifact_id=...)` 主路径进入迁移兼容状态。Session 07 起 executor-facing 文档应使用 sandbox-first 口径；现有代码仍暴露该工具时，只能视为 implementation debt 或 Host 内部兼容桥。
- Session 06 evidence 仍可作为真实 provider/tool/HPC readiness 的输入，但不能单独作为 cutover proof。
- `prerequisite_missing` 是非通过状态。未配置 live 环境时可以把 opt-in live gate 标记为 skipped / prerequisite_missing，但不能把它计入 passed。
- 核心稳定文档必须保持同一口径：`hpc` 是 placement / remote workspace / declarative stage-fetch namespace，不再是未决项；公开 docs/examples 使用 `hpc.workspace + domain operation` 形态，不再展示 runner-backed shorthand。

## 验收口径

每个 session 完成后必须至少覆盖：

- control-plane canonical state 是否记录 session、task、lane、approval、engine invocation、artifact、run、`sandbox_workspace_id` 和 provenance 关系。
- workspace projection 是否只暴露安全投影，并能让 UI/CLI/agent 理解 sandbox working copy 与 artifact catalog 的区别。
- sandbox run 中的受控 SDK call 是否能在真实 provider/HPC 工作前暴露 artifact reads、operation digest、expected outputs、资源/配额估计、backend route 和 approval 需求，并在 Web UI approval 前同步阻塞。
- 所有失败是否有结构化错误码、可读摘要和可追踪事件，而不是静默降级。
- 关键 AOX/HMM 输出是否通过最小格式校验；仅路径存在但格式错误或必需列缺失不能算通过。
- fixture/unit gate 只能证明 contract 和控制流；live AOX/HMM E2E 必须从用户 prompt 进入，经过 master、executor、`sandbox.exec`、SDK operation approval、scheduler、persistent sandbox、Host supervisor、artifact catalog 和 final answer。
