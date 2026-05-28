# Session 06：Adapter 基础条件探索

## 目标

在继续实现真实 adapter 之前，先用显式探索 session 查清 AOX/HMM 所需外网 provider、HPC 工具链、数据库路径和 sandbox image 轻量依赖建议是否具备。这个 session 的目标是形成 probe 清单、capability inventory 和 evidence matrix，作为后续静态 route policy 的输入；它本身不锁定最终产品 route policy，也不修改产品代码。

Session 06 补上 Session 01-05 之后暴露出的关键缺口：fixture/unit gate 已经证明 contract 形状，但没有证明真实 NCBI、UniProt、EBI HMMER、MAFFT、CD-HIT、HMMER CLI 和 HPC runner 已经可用。

本轮交付只限于本文档内的文档型 evidence matrix contract。Session 06 可以定义后续探索应收集哪些证据、如何命名状态、如何把证据交给 Session 14，但本轮不新增 probe 脚本、Host preflight API、product API、SDK、engine、eval 或测试。

Session 06 的实际 probe 结果、capability inventory、parameter inventory 和 evidence matrix 必须统一落到 `docs/v3/sessions/06-adapter-foundation-evidence.md`。本文档只保留探索计划、字段 contract、状态规则和验收口径；实际证据不继续堆在本文档正文里。

## 当前缺口

- 现有 fixture adapter 能让 AOX/HMM happy path 通过，但不能证明真实外网 provider、真实 CLI binary 和真实 HPC 环境存在。
- 缺少 provider 访问条件记录：NCBI email/tool identity、UniProt 分页和 rate limit、EBI HMMER submit/poll/result 语义。
- Host 本机不作为 AOX/HMM 生信工具部署面；既有 Host-local HMMER / Apptainer 观察只能作为非 route 背景，不能支撑 `bio_tools.*` 产品路径。
- 缺少 HPC 上 MAFFT、CD-HIT、HMMER CLI 全套工具的 module/spack/container 来源、compute node 路径、Slurm 资源模板、数据库路径和 staging 语义。
- sandbox image 只应承载 executor 的 Python/bash 工作面与轻量解析/过滤/评分依赖；缺少应建议安装哪些轻量依赖的记录，最终 allowlist 由 Session 09 实施前确认。
- 缺少统一的 prerequisite 状态矩阵，导致后续实现容易把缺配置、缺工具、缺数据库和 provider 失败误判成 fixture 成功。

## 实施范围

- 建立外网数据库 probe 清单：
  - NCBI protein accession fetch：记录 endpoint、email/tool identity、batch size、timeout、retry、rate limit、HTTP 错误和无效 accession 语义。
  - UniProt REST fetch/search：记录 accession 查询、字段选择、分页 cursor、batch size、HTTP 429、partial result 和 schema drift 语义。
  - EBI HMMER REST：记录 submit、status polling、result pagination、database 选择、空命中、timeout 和 provider error 语义。
- 建立 Host 本机边界检查：
  - 记录当前 Host 本机是否存在非预期 bio tool 观察，但这些观察只能作为迁移背景或风险说明，不能作为 `bio_tools.*` primary backend candidate。
  - 本机默认不安装 AOX/HMM 生信工具；`mafft`、`cd-hit`、`hmmbuild`、`hmmalign`、`hmmsearch` 的产品可用性必须由 HPC evidence 证明。
  - Pipeline code 运行在 sandbox 中，但不得直接 shell/subprocess 调 MAFFT、CD-HIT 或 HMMER binary；sandbox 镜像 probe 只验证 `openzyme_pipeline` SDK、Python/bash 工作面和受控 RPC 能力是否存在。
- 建立 HPC 工具 probe 清单：
  - HPC runner 配置是否存在，SSH/Slurm 连接是否可用，作业提交和结果回收是否可用。
  - 工具来源固定记录为 module、spack、container image 或管理员配置路径中的一种。
  - compute node 上记录 MAFFT、CD-HIT、HMMER CLI 版本、路径、环境初始化命令和 resource profile，覆盖 `mafft`、`cd-hit`、`hmmbuild`、`hmmalign`、`hmmsearch`。
  - 小样本 smoke 必须覆盖 staging input、declared expected outputs、fetch output、日志截断和失败日志 artifact 化。
- 建立数据库路径 probe 清单：
  - HMMER target database、UniProt/RefProt FASTA、索引文件和版本标签必须由 HPC policy 管理。
  - probe 结果只暴露数据库 logical name、version、digest、record count 和 availability，不暴露 Host path、runner path 或 private mount。
- 记录 sandbox image 轻量依赖建议：
  - 只记录建议候选与用途边界，不在 S06 决定或安装依赖。
  - 建议候选仅限 sandbox 内 Python/bash 派生处理、解析、过滤、评分、CSV/FASTA/HMM/JSON 轻量读写。
  - 不建议把 MAFFT、CD-HIT、HMMER、Apptainer、SSH/Slurm client、runner config、provider credential 或 database mount 放入 sandbox image。
- 建立参数能力 probe 清单：
  - 对 MAFFT、CD-HIT、HMMER CLI 记录对应版本的 `--help`、man page 或官方文档引用，作为后续 adapter 参数 schema 的 evidence reference。
  - 区分 AOX/HMM 必需参数、常用安全参数、资源/性能参数、输入输出路径参数、数据库选择参数和 shell/重定向/脚本类危险参数。
  - 记录哪些参数应由 Host policy 管理，例如 threads、memory、walltime、database logical name、output location 和 log cap；这些参数不能由 pipeline code 或 LLM 任意透传。
  - 记录哪些参数应禁止进入 adapter contract，例如 Host path、HPC remote path、database mount、arbitrary command、shell metacharacter、output redirect 和任意 passthrough string。
  - Session 06 只收集参数能力 inventory，不定义最终 `params` schema、allowlist 或 SDK contract；最终参数 contract 必须在 Session 14 中锁定。
- 产出 capability inventory / evidence matrix：
  - `bio.ncbi_fetch_proteins`、`bio.uniprot_fetch`、`bio.hmmer_search`。
  - `bio_tools.cdhit`、`bio_tools.mafft`、`bio_tools.hmmbuild`、`bio_tools.hmmalign`、`bio_tools.hmmer_search_cli`。
  - 对每个 `bio_tools.*` operation 必须记录一个 primary static backend recommendation，并记录 evidence reference、状态、prerequisite、resource class、expected outputs、approval requirement 和 prerequisite missing 时的结构化错误。
  - 对每个 `bio_tools.*` operation 必须记录 parameter inventory reference，说明 AOX/HMM 必需参数、安全可暴露参数、Host policy 管参数和禁止透传参数。
  - 不采用双 backend 作为产品目标；非推荐 backend 只在有助于解释风险或缺口时记录为补充证据，不能被 Session 14 解释成动态 fallback 或 runtime route choice。
  - 探索结果必须记录推荐候选和风险说明，但不能替代 Session 14 的最终静态 backend route table。
  - 探索结果必须写入 `docs/v3/sessions/06-adapter-foundation-evidence.md`，并在 `evidence_ref` / `parameter_inventory_ref` 中使用该文件内的稳定小节锚点。
  - Session 14 必须读取该 evidence 文件中的 inventory / matrix 后，才能为 `bio_tools.*` 锁定 `hpc` 或 `unsupported/prerequisite_missing` 的静态 route policy。

## 静态 Backend 推荐判断

如果后续实现不采用双 backend，Session 06 记录的保守静态判断如下。这个判断用于指导 evidence matrix 和 Session 14 route table 设计；Session 06 仍不实现或启用任何 route policy。

| Operation | 推荐静态 backend | Resource class | 判断 |
| --- | --- | --- | --- |
| `bio.ncbi_fetch_proteins` | `provider` | `network_io` | Host-supervised provider request；只需要 endpoint、email/tool identity、限流、重试和错误语义，不应提交 HPC。 |
| `bio.uniprot_fetch` | `provider` | `network_io` | Host-supervised provider request；分页、字段选择、HTTP 429 和 schema drift 由 Host 管理，不应提交 HPC。 |
| `bio.hmmer_search` | `provider` | `network_io` | EBI HMMER REST 的 submit/poll/result fetch；计算发生在 provider 侧，不等同于本地或 HPC CLI backend。 |
| `bio_tools.hmmbuild` | `hpc` | `hpc_batch_small` | 即使小样本可轻量运行，为保持 AOX/HMM 工具链部署面一致，HMMER CLI 统一安装和验证在 HPC；Host 本机和 sandbox 不作为 route。 |
| `bio_tools.hmmalign` | `hpc` | `hpc_batch_small` | 即使小样本可轻量运行，为保持 AOX/HMM 工具链部署面一致，HMMER CLI 统一安装和验证在 HPC；Host 本机和 sandbox 不作为 route。 |
| `bio_tools.mafft` | `hpc` | `hpc_batch_small` | 即使小样本理论上可轻量运行，为保持最终 AOX/HMM 测试环境一致，不在 Host 本机或 sandbox 安装 MAFFT，静态锁定 HPC。 |
| `bio_tools.cdhit` | `hpc` | `hpc_batch_small` | 即使小 FASTA 理论上可轻量运行，为保持最终 AOX/HMM 测试环境一致，不在 Host 本机或 sandbox 安装 CD-HIT，静态锁定 HPC。 |
| `bio_tools.hmmer_search_cli` | `hpc` | `hpc_batch_small` | 真实 HMM search 依赖 target database、索引和批量扫描；数据库更适合由 HPC/shared storage policy 管理，静态锁定 HPC。 |

静态判断的执行含义：

- `provider` backend 只表示 Host 托管的外网 provider 访问，不表示 sandbox 直接联网，也不表示 HPC job。
- 本计划不为 AOX/HMM `bio_tools.*` 设置 Host-local backend；既有 Host-local 观察不进入产品 route。
- `hpc` backend 只允许 Host supervisor 通过 HPC runner、staging input、declared expected outputs 和 fetch output 执行；pipeline code 不接触 SSH、Slurm、runner config、database mount 或远端路径。
- Podman pipeline sandbox 的 probe 目标是确认 sandbox 能运行 pipeline source、导入 `openzyme_pipeline`、通过受控 RPC 请求 `bio.*` / `bio_tools.*` / `hpc.*`，并记录是否需要额外轻量 Python 依赖；它不能用来证明 HPC backend 的 MAFFT、CD-HIT、HMMER binary 已安装。
- `hpc` 推荐项如果缺少 runner、module/container、数据库、staging/fetch 或 compute-node smoke 证据，状态必须是 `prerequisite_missing` 或 `failed`，不能自动改走 Host 本机、sandbox 内 binary 或 fixture。

## 接口变化

- 本 session 不引入产品 API、SDK、engine、adapter 或 eval 变更。
- 本 session 不新增 probe CLI、自动化 probe 脚本或 Host preflight API；后续若实现 probe automation，必须另起实现改动并补测试。
- 本 session 记录 `bio_tools.*` primary static backend recommendation，但不实现或启用产品 route policy；它只提供后续 Session 14 决策所需的证据。
- 探索报告的状态值固定为 `ok`、`prerequisite_missing`、`failed`。
- `prerequisite_missing` 必须携带 `missing_kind`、`operation`、`backend`、`hint` 和安全的 `details`。
- provider 侧缺口使用结构化错误码：`provider_not_configured`、`provider_identity_missing`、`provider_unavailable`、`rate_limited`、`pagination_failed`、`provider_schema_drift`。
- toolchain 侧缺口使用结构化错误码：`tool_missing`、`tool_version_unsupported`、`container_runtime_missing`、`container_image_missing`、`container_entrypoint_missing`、`database_missing`、`sample_smoke_failed`、`hpc_runner_not_configured`、`hpc_tool_missing`。
- 所有 probe 证据只能进入 docs/report 或后续 implementation ticket，不写入 production artifact catalog，不改变用户 session 状态。
- Session 06 当前约定的 docs 落点是 `docs/v3/sessions/06-adapter-foundation-evidence.md`；该文件可以包含安全摘要、命令模板、版本、digest、状态矩阵和 remediation hint，但不得包含 credential、Host path、HPC remote path、private mount 或完整 runner config。

## 参考资料

- `docs/HPC服务器调用指南.md` 可作为 HPC capability inventory 和 command-contract 模板参考，尤其是工具目录、deployment mode、entrypoint、runtime context、node expectation、command contract 字段、Apptainer bind policy、failure diagnostics、staging/fetch timeout 和 smoke-check 格式。
- `docs/v3/sessions/06-adapter-foundation-evidence.md` 是本 session 后续实际 probe 结果的固定落点；`docs/HPC服务器调用指南.md` 只能作为其格式和 HPC command-contract 参考。
- 该指南不能直接作为 Session 06 的 `ok` 证据。指南中的 smoke 记录是历史手工证据，Session 06 必须按当前环境重新 probe，并把结果归入 `ok`、`prerequisite_missing` 或 `failed`。
- 该指南中的 Host path、HPC remote path、container path、SSH/Slurm 细节和 database mount 只能作为内部 probe 输入，不得暴露到 public workspace、tool result、artifact public projection 或 pipeline source。
- 该指南中的 fallback / substitute / invocation precedence 只能作为 remediation 背景，不能被写成 V3 runtime dynamic route、backend fallback 或 fixture 替代规则。

## 测试/验收

- probe 清单覆盖 NCBI、UniProt、EBI HMMER、HPC MAFFT/CD-HIT/HMMER CLI、runtime packaging、数据库路径、小样本 smoke，以及 sandbox image 轻量依赖建议。
- probe 清单覆盖 MAFFT、CD-HIT、HMMER CLI 的参数能力 inventory，并明确参数证据来源、危险参数类别和 Host policy 管控边界。
- 每个 probe 结果都能归入 `ok`、`prerequisite_missing`、`failed`，且缺失项有明确 remediation hint。
- 实际 probe 结果必须写入 `docs/v3/sessions/06-adapter-foundation-evidence.md`，本文档正文只保留 contract 和状态规则。
- evidence matrix 能支撑后续 Session 14 按 primary static backend recommendation 判断每个 `bio_tools.*` operation 应静态走 `hpc`，还是因 prerequisite 缺失而标记为 `unsupported/prerequisite_missing`。
- evidence matrix 不得把 Host 本机、sandbox 内 binary 与 HPC 同时作为同一 `bio_tools.*` operation 的产品候选 backend；非推荐 backend 的观察结果只能作为风险说明或 remediation 背景。
- HPC smoke 必须使用受控小样本输入，并验证 declared expected outputs，不以命令返回零作为唯一通过条件。
- provider probe 必须记录分页、轮询、timeout、quota、partial result、empty result 和 schema drift 的观察结果。
- probe 失败不能被 deterministic adapter、fixture result 或 synthetic artifact 替代。
- 文档必须明确 probe 不是 live cutover；probe 通过只说明 prerequisite 可用，不说明 AOX/HMM prompt E2E 已通过。

## 明确不做什么

- 本轮不实现真实 provider adapter。
- 本轮不实现 `BioToolSupervisor` 或 `HpcBioToolBackend`。
- 本轮不实现动态路由、静态 route table 或 SDK operation route policy。
- 本轮不修改 SDK、engine、Host API、eval、pytest 或 live gate。
- 不把 deterministic fixture 成功写成真实 provider/toolchain 成功。
- 不把 Host path、HPC runner path、SSH/Slurm 配置、database mount 或 credentials 暴露到 public workspace。

## Evidence Matrix 附录

Session 06 的文档型 evidence matrix 必须落在 `docs/v3/sessions/06-adapter-foundation-evidence.md`。它不写入 production artifact catalog，不改变用户 session 状态，也不等同于 live cutover proof。

该 evidence 文件建议固定包含这些小节：

- `Probe Summary`：probe date、operator、environment summary、safe digest 和当前限制。
- `Provider Evidence`：NCBI、UniProt、EBI HMMER REST 的配置、访问、分页、quota、timeout 和 schema 观察结果。
- `Host Local Non-route Observations`：Host-local 非 route 背景观察；不得作为 `bio_tools.*` backend evidence。
- `HPC Evidence`：MAFFT、CD-HIT、HMMER search/database、runner、staging/fetch、resource profile 和 compute-node smoke。
- `Sandbox Image Recommendations`：建议放入 sandbox image 的轻量依赖候选、用途边界和禁止项；最终 allowlist 由 Session 09 实施前确认。
- `Parameter Inventory`：MAFFT、CD-HIT、HMMER CLI 的 supported、unsupported、Host-policy-managed 和 forbidden params。
- `Evidence Matrix`：按下表字段记录每个 operation/backend 的状态。
- `Remediation Hints`：可执行修复建议，但不包含 credential、private path 或 runner secret。

Matrix 字段固定为：

| 字段 | 含义 |
| --- | --- |
| `operation` | 领域 SDK operation，例如 `bio.uniprot_fetch` 或 `bio_tools.hmmer_search_cli`。 |
| `backend` | 候选 backend，固定为 `provider`、`hpc` 或 `none`；AOX/HMM `bio_tools.*` 当前不使用 Host-local backend。 |
| `status` | 证据状态，固定为 `ok`、`prerequisite_missing`、`failed`。 |
| `evidence_ref` | 文档证据引用，例如 probe 记录、手工检查摘要或后续 ticket id；不能是口头判断。 |
| `prerequisite` | 所需配置、工具、数据库、credential、runner 能力或 provider identity。 |
| `resource_class` | 资源等级，例如 `network_io`、`hpc_batch_small`。 |
| `runtime_packaging` | backend 的运行封装，例如 `provider_http`、`hpc_apptainer_sif`、`hpc_module` 或管理员 wrapper；只能作为 Host/internal evidence，不暴露为 pipeline API。 |
| `expected_outputs` | 该 operation 成功后必须声明并校验的输出集合。 |
| `approval_requirement` | 是否需要 SDK operation approval，以及 approval 中必须展示的资源、输出和 provider/tool 摘要。 |
| `parameter_inventory_ref` | 参数能力证据引用，指向对应 tool/version 的 help/man page/官方文档摘要和参数分类记录。 |
| `error_code` | `prerequisite_missing` 或 `failed` 时的结构化错误码。 |
| `remediation_hint` | 可执行修复提示，不包含 Host path、runner path、credential 或 private mount。 |

状态规则：

- `ok` 必须有可追踪 `evidence_ref`，且 evidence 覆盖 tool/provider availability、最小 smoke、expected outputs 和格式校验；只有 `ok` 才能支撑 Session 14 把对应 backend 写成 `hpc` route。
- `prerequisite_missing` 表示环境、credential、工具、数据库、runner、staging/fetch 或 provider identity 缺失；它是非通过状态，但可以作为 Session 14 写入 `unsupported/prerequisite_missing` 的证据。
- `failed` 表示 probe 条件已具备但执行失败，例如 provider schema drift、sample smoke failed、output validation failed 或 HPC fetch failure；它不能被 fixture、synthetic artifact 或另一个 backend 的成功替代。
- 同一 `bio_tools.*` operation 在产品推荐上只能有一个 primary static backend；若 matrix 附带非推荐 backend 的探查证据，该证据不能成为 Session 14 的动态 fallback 或双 backend route。
- 最终 route policy 只能由 Session 14 根据 matrix 生成。
