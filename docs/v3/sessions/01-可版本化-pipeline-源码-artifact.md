# Session 01：可版本化 Pipeline 源码 Artifact

## 目标

让 executor 能在 V3 workspace 中创建、读取、修改和 diff `.py` pipeline 源码 artifact。pipeline 源码必须成为 session artifact catalog 的一等对象，而不是 prompt 临时文本、浏览器状态、Host 本地文件路径或 execution invocation 的隐式字段。

源码 artifact 用于承载后续 AOX/HMM pipeline 的可追踪实现：NCBI/UniProt/HMMER 请求编排、CD-HIT/MAFFT/HMMER CLI 调用、过滤、打分、FASTA/CSV/graph 输出登记等都应先落到可版本化源码，再由 execution 引用。

## 当前缺口

- 当前 artifact read/register 主要面向输入、生成结果和 execution output，没有明确的 pipeline source 语义。
- executor 可以在 tool 参数中提交 inline code，但这段源码不是共享 workspace 的稳定工作面。
- 缺少面向 agent 的源码文本创建、读取、patch、版本父子关系和 diff 工具语义。
- 源码覆盖、并发更新、格式不合法、非 UTF-8、超长内容等失败语义尚未明确。

## 实施范围

- 引入 `ArtifactKind.CODE`，用于标识代码类 artifact。
- Pipeline 源码 artifact 必须使用 `kind=code`、`format=python`、`metadata.semantic_type="pipeline_source"`。
- Pipeline 源码 artifact 必须记录 `metadata.content_digest`，digest 算法固定为 SHA-256。
- 支持 executor 通过 agent tool 创建 `.py` pipeline 源码 artifact。
- 支持按 `artifact_id` 读取源码文本，读取结果必须受大小、编码和权限限制。
- 支持 patch 源码并产生新 artifact version，不静默覆盖旧版本。
- 每次 patch 成功后必须生成新的不可变 `ArtifactKind.CODE` artifact，旧 artifact 保持可读。
- 版本父子关系固定记录在 metadata：`parent_artifact_id`、`lineage_root_artifact_id`、`version`。
- 支持两个源码 artifact 或两个版本之间的 diff，供 executor 解释修改内容。
- 保留源码 artifact 与 task、lane、producer agent、invocation 的关系，供 workspace projection 和 provenance 使用。

## 接口变化

- artifact catalog 增加代码源码语义：`kind=code`，`format=python`，`metadata.semantic_type="pipeline_source"`。
- agent-facing artifact 工具固定为：
  - `artifact.create_text`：创建 UTF-8 文本 artifact。
  - `artifact.read_text`：读取源码文本，返回分页或 bounded 内容。
  - `artifact.patch_text`：基于指定源码 artifact 生成新版本。
  - `artifact.diff_text`：返回两个版本的 unified diff 或结构化 diff。
- `artifact.create_text` 创建 pipeline source 时必须写入 `kind=code`、`format=python`、`metadata.semantic_type="pipeline_source"`、`metadata.content_digest`、`metadata.lineage_root_artifact_id`、`metadata.version=1`。
- `artifact.patch_text` 必须带 `base_artifact_id` 和 `base_content_digest`。
- `artifact.patch_text` 成功后返回新的 `ArtifactKind.CODE` artifact，并写入 `metadata.parent_artifact_id`、`metadata.lineage_root_artifact_id`、递增后的 `metadata.version` 和新的 `metadata.content_digest`。
- `base_content_digest` 与 catalog 当前 digest 不匹配时显式失败，不创建新 artifact。
- public workspace 可以展示源码 artifact 摘要、版本和 lineage，但默认不直接暴露完整源码；完整读取仍通过受控 agent tool。

## 测试/验收

- executor 能创建 `.py` pipeline 源码 artifact，并在 workspace 中看到安全摘要。
- `artifact.read_text` 能按 `artifact_id` 读取源码内容，不返回 Host path 或 `storage_uri`。
- patch/update 生成新版本，旧版本仍可读，且 lineage 能回链。
- 缺少 `base_artifact_id`、缺少 `base_content_digest`、digest 过期、非 code artifact patch、非 UTF-8 内容、超出大小限制、非法扩展名都返回结构化 tool error。
- diff 工具能展示两个版本之间的修改，并可被 executor 用于总结变更。
- 相关事件至少能表达 `artifact.recorded` 与源码版本更新，且投影不泄露私有路径。
- unit/fixture tests 必须覆盖 CODE artifact 创建、read、patch 版本化、digest 并发保护、diff 和 public projection 安全字段。

## 明确不做什么

- 不执行源码 artifact。
- 不在本 session 引入 `execution.pipeline.start(code_artifact_id=...)` 主路径。
- 不新增网络数据库 SDK、生信工具链或 sandbox image 依赖。
- 不允许 executor 通过 Host 本地路径、repo path、临时文件路径或浏览器状态保存源码。
- 不把源码 artifact 当作 report、普通 result artifact 或 hidden prompt 字段。
