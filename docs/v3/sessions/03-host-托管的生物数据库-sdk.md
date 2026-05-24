# Session 03：Host 托管的生物数据库 SDK

## 目标

新增 Host-supervised 的生物数据库/网络 SDK，使 AOX/HMM pipeline 能获取参考序列、目标蛋白组、HMMER hits 和相关 metadata，同时保持 sandbox 默认无任意网络。sandbox 只通过 `openzyme_pipeline.bio` 发起受控请求；Host 负责 provider 配置、网络访问、分页、配额、审计、artifact 登记和 provenance。

## 当前缺口

- 现有 execution SDK 主要覆盖 `artifacts`、`preprocess` 和 `hpc`，没有统一的 bio/network 数据库模块。
- notebook 直接访问 NCBI、UniProt 和 EBI HMMER REST，这与 V3 sandbox 无网络边界冲突。
- 现有 `uniprot.*` research tools 可作为参考，但不是 pipeline sandbox 内的 Host-supervised SDK 契约。
- 缺少批量拉取、分页、rate limit、provider error、partial result、provenance 和 artifact 输出的统一语义。

## 实施范围

- 在 sandbox SDK 中新增 `openzyme_pipeline.bio`。
- Host supervisor 实现以下受控操作：
  - NCBI protein 批量拉取 accession 对应的 FASTA 和 metadata。
  - UniProt 批量获取序列、长度、taxonomy、reviewed 状态和可配置 metadata 字段。
  - EBI HMMER REST `hmmsearch` 提交、状态轮询、分页拉取和结果解析。
- 所有网络请求由 Host 执行，sandbox 只接收结构化结果或已登记 artifact ref。
- 大结果必须写入 artifact catalog：FASTA、metadata CSV/JSON、raw HMMER hits JSON、parsed hits CSV。
- 每个结果记录 provider、query、accession、database、request window、分页 cursor、response digest、retrieved_at、tool version/API version。
- 支持 dry-run 中展示预计 provider、请求量、分页/配额估计、是否需要 approval。

## 接口变化

- SDK module 固定为 `openzyme_pipeline.bio`。
- `bio.ncbi_fetch_proteins(accessions=[...], fields=[...])` 返回 FASTA artifact 与 metadata artifact。
- `bio.uniprot_fetch(accessions=[...], fields=[...], batch_size=...)` 返回 sequence/metadata artifacts 和 structured summary。
- `bio.hmmer_search(hmm_artifact_id=..., database=..., params=...)` 返回 raw hits artifact、parsed hits artifact 和 search summary。
- Host policy 负责 provider credentials、email/tool identity、rate limit、retry budget、timeout、quota 和 audit log。
- provider error、timeout、quota exceeded、invalid accession、partial results、empty results、pagination failure、schema drift 都必须返回结构化 RPC error 或带 warning 的结构化 partial result。
- 结构化 RPC error 固定包含 `error_code`、`stage`、`retryable`、`hint`、`details`；warning 至少包含 `warning_code`、`stage`、`hint` 和受影响 accession/page/result range。
- NCBI、UniProt、EBI HMMER 的 timeout、quota、partial result 和 schema drift 不能折叠成普通空结果；必须进入 execution status、events 和 workspace 安全投影，供 executor 汇总给 master。
- 大型 FASTA、metadata、raw hits 和 parsed hits 不通过 RPC payload 返回全文；RPC 只返回 bounded summary、artifact refs、计数、digest、provider/page 摘要和 warning。
- public workspace 展示 database artifact 和 provenance 摘要，不展示 provider credential、private endpoint token、Host cache path 或 raw request secrets。

## 测试/验收

- dry-run 能列出 NCBI、UniProt、EBI HMMER 操作、预计请求数、输出 artifact 和配额/approval 需求。
- sandbox 内不能直接访问网络；直接 `requests`、`httpx`、`urllib` 或 `Bio.Entrez` 网络调用应被 sandbox policy 或 dry-run 拒绝。
- NCBI 批量 accession fetch 产出 FASTA 和 metadata artifact，metadata 至少包含 accession、description、length、taxonomy。
- UniProt 批量查询能处理分页和批量大小限制，结果 artifact 可被后续 pipeline 读取。
- EBI HMMER search 能提交 HMM artifact、轮询完成、分页拉取 raw/parsed hits，并保留 query/HMM provenance。
- provider 超时、HTTP 错误、quota 超限、无命中、部分 accession 失败都有明确状态、结构化字段和可追踪事件。
- schema drift、pagination failure 和 partial result fixture 必须验证 warning/error 不会被当作成功空结果。
- unit/fixture tests 必须覆盖 `bio.ncbi_fetch_proteins(...)`、`bio.uniprot_fetch(...)`、`bio.hmmer_search(...)`、直接网络拒绝、大结果 artifact 登记和 RPC payload 不返回全文。

## 明确不做什么

- 不给 sandbox 开任意网络。
- 不让 pipeline code 自行保存 provider credentials、SSH key、API token 或 Host cache path。
- 不要求直接复刻 notebook 中的 requests/BioPython 网络代码。
- 不把普通 search hit 当作 artifact；只有真实下载或生成的 sequence、metadata、hits 文件进入 artifact catalog。
- 不在本 session 定义 MAFFT、CD-HIT、HMMER CLI 或 HPC toolchain 的完整执行边界。
