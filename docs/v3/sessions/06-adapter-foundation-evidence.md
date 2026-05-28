# Session 06 Adapter 基础条件证据

## Probe Summary

Probe 日期：2026-05-25；NCBI identity probe 与 EBI HMMER known-good probe 于 2026-05-27 复核；HPC AOX/HMM bio-tools SIF 与小样本 smoke 于 2026-05-28 复核。

范围：本文是 Session 06 的文档型证据，覆盖 provider、HPC prerequisite、数据库 inventory、参数 inventory、Host 本机非 route 观察、sandbox image 轻量依赖建议，以及 Session 14 锁定 `bio_tools.*` 静态 route policy 之前必须读取的 evidence matrix。

本文不是 live cutover 报告。某一行通过只说明当前环境中观察到了对应 prerequisite，不证明 AOX/HMM prompt E2E 产品路径已经通过。

Operator / 环境摘要：

- 当前 checkout：`EnzymeDesign` workspace。
- 本 session 对仓库代码的改动：新增/更新本文档，并增加 `apps/mcp-hpc-runner/fixtures/hpc_tool_samples/aox_hmm/` 小样本 smoke fixture。
- Probe 输入：受控 FASTA/MSA/HMMER 小样本输入；未写入 production artifact catalog。
- 安全边界：本文不记录 credential、Host 绝对路径、HPC remote path、private mount、runner secret 或完整 runner config。
- Provider identity 检查：NCBI probe 使用 operator 提供的 email/tool identity；未配置 NCBI API key。当前 shell 环境中仍没有配置 `UNIPROT_API_KEY`、`EBI_HMMER_EMAIL` 或 `OPENZYME_EBI_HMMER_EMAIL`。

安全 digest 与固定样本指纹：

| 项目 | 安全指纹 |
| --- | --- |
| Host-local HMMER SIF 非 route 观察 | sha256 `d46324cc2a1bc93d68997960c6aeb035f46e2037dbdb9cb609dc8492bbdd9634` |
| 受控 MSA 输入 | sha256 `b452258966c3c778ec61c006d187514698890857a65c57de755739d556bf0701` |
| 受控 sequence 输入 | sha256 `69c2050770a42ed31faa187564d251863fcc0d0d6605cb2053a8b247c1e530fa` |
| 受控 target FASTA 输入 | sha256 `b755310bd1e41b2b9c6a699a9639ae2782b0222dc480708b49b2db9378e91fbc` |
| NCBI valid accession FASTA 输出 | sha256 `dc55eccbbd46666327b633b5ecbdd6a2040ee83794d82ec58429a4d00cc0295b` |
| NCBI invalid accession error 输出 | sha256 `70bc3909febe0d1e0e6400842237150f0e43d2af64d210dcccb9d33af2b45764` |
| EBI HMMER known-good PF00069 HMM 输入 | sha256 `37695d3cd57cd55d352e1d4229cf53eb5dc982fe8bffba23f106039e41a4065d` |
| EBI HMMER known-good submit response | sha256 `0d4e4723dcc681a1fd14d3fb5f23016df3faf68e3c4b1efe56604708851383b2` |
| EBI HMMER known-good job detail response | sha256 `59bb9a715b8a09169e177b4cff829fe6a6110b60cdb7101b61e29929d8302f2d` |
| EBI HMMER known-good result page response | sha256 `21e53d73d7bb4a1921228afe9c18f2b2b0771f6fc919ff074d201b99043cadc3` |
| HMMER `hmmbuild` 输出 | sha256 `440ef6d8863e74a6cb3bf3db8c019c17f2097e17401035852aee722448cbecc2` |
| HMMER `hmmalign` 输出 | sha256 `b196fc4ad890e104259328e50088738d7b3b7c6a474799377c260e95a74b47aa` |
| HMMER `hmmsearch --tblout` 输出 | sha256 `73c5853772152f87b3bce76461b811dde93a21705c9d017b56f98cb54e4f4e86` |
| HPC AOX/HMM smoke `input_sequences.fasta` | sha256 `46fafd1699f08df9c086f8cab5f3148ea0d3d542a7669dbef23d3ed5bd716617` |
| HPC AOX/HMM smoke `msa.sto` | sha256 `55773fda74dc7b4a7e50c546f082a59bb2fb79cf6ee19110ea8b379718bf8bb6` |
| HPC AOX/HMM smoke `search_targets.fasta` | sha256 `f44488ffb8dda52ab7e468b5ace1f31d49b5c633c8246d552712ae58e543f815` |
| HPC AOX/HMM smoke script | sha256 `7a8431b7327145fa348cfc5cefba634d08b341880ca7c4220017ed4189c5df2e` |
| HPC Slurm smoke `mafft.aln.fasta` | sha256 `46fafd1699f08df9c086f8cab5f3148ea0d3d542a7669dbef23d3ed5bd716617` |
| HPC Slurm smoke `cdhit_representatives.fasta` | sha256 `3193a9621e1ee1a6c7ff2f4f08667bf3cf7c972b4758fe9946d82a6c489a5027` |
| HPC Slurm smoke `cdhit_representatives.fasta.clstr` | sha256 `51b2d912dfe2107e8ff7acecb4044016b4c823e2c14e2f6a0541aa511556ec62` |
| HPC Slurm smoke `toy.hmm` | sha256 `be49b8c2f8400f66df5e4edc97733ed08d258be300192799baed0491dc1f4eb9` |
| HPC Slurm smoke `hmmalign.sto` | sha256 `28efb6390e051bb1a146586844a6ac468541011136a7407272a4c9f78cfd7320` |
| HPC Slurm smoke `hmmsearch.tblout` | sha256 `571c72cf2d92382b5c141fbf360a16ccdaebd1b815942a64a7c07291ced2991d` |
| HPC Slurm smoke `hmmsearch.domtblout` | sha256 `ba8bb8a48686d659823704998dc3f5cf9db2c86e8c4eb3e241301cb16a79bcdc` |

当前限制：

- 未做 rate-limit 压测。单次安全请求只记录了 provider 返回的 quota/release header。
- 本地 probe 使用了有界请求 timeout，但没有主动诱发 provider 侧 timeout 状态。
- 未主动诱发 retry/backoff；下方矩阵只记录 retry policy 是否仍是 prerequisite。
- 已证明 MAFFT、CD-HIT、HMMER CLI（`hmmbuild`、`hmmalign`、`hmmsearch`）可通过 Diannan HPC SIF 在受控小样本上运行，并通过 runner staging/fetch 与 declared-output validation。尚未把这些 runtime evidence 固化为 S14 产品 adapter contract。
- 尚未证明 HPC-managed production HMMER target database inventory；按当前 S15 主路，HMM search 使用 EBI HMMER REST `refprot`，该缺口不阻塞 Session 06 作为 S13/S14/S15 主路实施输入的完成判断，只阻塞后续启用 offline/HPC `bio_tools.hmmer_search_cli` 产品 route。
- EBI HMMER REST 的早期 toy HMM / `pdb` 样本提交后 job 立即失败；2026-05-27 使用 Pfam PF00069 HMM 与 `refprot` 重新 probe 后，submit、polling 和 result pagination 均成功。早期失败归类为样本/数据库选择不适合作为 provider 可用性证明。

## Session 06 Conclusion

按最新证据和当前 route 决策，Session 06 可以判定为 `complete_for_main_route_prerequisites`：本 session 需要交付的安全 evidence matrix、provider/HPC prerequisite 观察、database/parameter inventory、Host/sandbox/HPC 边界和 remediation hints 已齐备，可作为 S13、S14 和 S15 主路实施输入。

这个结论不是 `s15_passed`，也不是所有可能 backend 的 unconditional `all_ok`。

S06 自身完成状态：

- Evidence sink 已统一到本文档；探索计划不再承载实际证据。
- Provider prerequisite 已有当前安全证据：NCBI、UniProt 与 EBI HMMER REST 均有可达性、基础 schema/error 语义或 pagination 观察。
- HPC AOX/HMM CLI tool runtime prerequisite 已有当前安全证据：MAFFT、CD-HIT、`hmmbuild`、`hmmalign` 和 `hmmsearch` 均已通过 Diannan HPC SIF/version 检查，并在 Runner SSH 与 Slurm 小样本 smoke 中完成 staging、fetch 和 declared-output validation。
- Host-local 与 sandbox 边界已锁定：Host 本机不部署 AOX/HMM CLI 生信工具；executor sandbox 不承载 MAFFT/CD-HIT/HMMER、Apptainer、SSH/Slurm client、provider credential 或 database mount。
- 剩余缺口均已归属到后续 session 或 optional route，不是 S06 继续补证据才能完成的事项。

主路放行理由：

- Provider prerequisite 已覆盖并可用：NCBI、UniProt 与 EBI HMMER REST 均为 `ok`；EBI HMMER REST 已用 known-good PF00069 HMM 对 `refprot` 证明 submit、polling 和 result pagination。
- HPC tool runtime prerequisite 已覆盖并可用：MAFFT、CD-HIT、`hmmbuild`、`hmmalign` 和 `hmmsearch` 均已通过 Diannan HPC SIF/version 检查，并在 Runner SSH 与 Slurm 小样本 smoke 中完成 staging、fetch 和 declared-output validation。
- 当前 S15 HMM search 主路是 `bio.hmmer_search(..., database="refprot")` 的 EBI HMMER REST provider，不要求 HPC 本地生产 HMMER target database。
- Host 本机与 executor sandbox 都不是 AOX/HMM CLI 生信工具部署面；Host-local HMMER 只保留为非 route 观察，sandbox image 只记录轻量依赖建议，不参与本结论。

仍不能宣称的内容：

- 不能宣称 offline/HPC `bio_tools.hmmer_search_cli` 产品 route 已 ready；它仍缺 HPC-managed production target database 的 logical name、version、digest、record count 和 availability。
- 不能宣称 S14 adapter contract 已完成；MAFFT、CD-HIT、HMMER CLI 还需要在 S14 固化 Host-managed command template、typed params、resource profile、staging/fetch expectations 和 failure signatures。
- 不能宣称 AOX/HMM 固定 HMM 已对 `refprot` 完成 EBI HMMER REST 成功搜索；当前 S06 provider success proof 使用的是 known-good PF00069 HMM。S13/S15 仍需用 AOX/HMM 固定合同输入重新验证。
- 不能把 S06 当成 S15 live E2E cutover proof；S15 仍需用 AOX/HMM 固定 prompt 和真实产品路径重新验收。

## Provider Evidence

<a id="provider-evidence-ncbi"></a>

### Provider Evidence：NCBI

Probe：使用 operator 提供的 email/tool identity，对 accession `NP_001230.1` 执行 NCBI EFetch protein FASTA 请求，并对 invalid accession 执行错误语义 probe。

观察结果：

- HTTP status：`200`。
- Content type：`text/plain`。
- Response body 以 `NP_001230.1` FASTA header 开头。
- Header 包含 `x-ratelimit-limit: 3` 和 `x-ratelimit-remaining`。
- invalid accession probe 返回 HTTP `200`，body 是 provider error text，表示无法理解该 invalid id。
- 当前 probe 已带 email/tool identity；未使用 NCBI API key。
- 本次安全 probe 没有触发 retry/backoff 行为。

状态判断：`ok`。

原因：基础 endpoint 访问成功，valid accession 返回 FASTA，invalid accession 错误语义可观察，且本次 probe 已带 email/tool identity。NCBI API key 仍未配置；这不阻塞当前小样本 prerequisite，但 S13 实现仍必须把 identity、quota、retry 和 error mapping 纳入 Host provider policy。

S13 将其固化为真实 provider adapter 前仍需补充：

- batch size policy 与 retry/backoff policy。
- invalid accession 与 provider error 的显式 mapping。
- 安全 quota/rate-limit handling。

<a id="provider-evidence-uniprot"></a>

### Provider Evidence：UniProt

Probe：对两个 accession 执行 UniProtKB REST search，使用 `size=1`、selected fields 和 cursor pagination。

观察结果：

- Page 1 HTTP status：`200`。
- Page 1 headers 包含 `x-uniprot-release: 2026_01`、`x-total-results: 2` 和 `Link: ... rel="next"`。
- Page 1 返回一个 result，accession 为 `P69905`。
- 按返回的 cursor 请求下一页，HTTP status 为 `200`，返回一个 result，accession 为 `P68871`。
- 使用合法 accession 形状但没有观察到 match 的 empty search probe 返回 HTTP `200`，`results` 为 0，并带有 `suggestions` 字段。
- invalid accession-format probe 返回 HTTP `400`，并带有结构化 JSON message 说明 accession 格式非法。
- 安全 probe 中没有观察到 429；未主动诱发 429。

状态判断：`ok`。

后续实现仍必须保留：

- Host-managed page cursor handling。
- fields allowlist 与 schema validation。
- HTTP `400`、`404`、`429`、partial result 和 schema drift mapping。
- 大结果必须 artifact 化，不能作为 inline RPC payload 返回。

<a id="provider-evidence-ebi-hmmer-rest"></a>

### Provider Evidence：EBI HMMER REST

Probe：检查 EBI HMMER API v1 OpenAPI、database list，提交早期受控 toy `hmmsearch` 样本，并用 Pfam PF00069 known-good HMM 对 `refprot` 重新 probe。

观察结果：

- OpenAPI endpoint 返回 HTTP `200`，OpenAPI 版本为 `3.1.0`，包含 submit、search status、result、domains、download 和 database inventory 相关 paths。
- Database inventory endpoint 返回 HTTP `200`，包含 enabled logical databases：
  - `pfam` type `hmm`，version `37.2`。
  - `refprot` type `seq`，version `2025_01`。
  - `swissprot` type `seq`，version `2025_01`。
  - `uniprot` type `seq`，version `2025_01`。
  - `pdb` type `seq`，version `03.25`。
  - `rp15`、`rp35`、`rp55`、`rp75` type `seq`，version `2024_04`。
- `POST /Tools/hmmer/api/v1/search/hmmsearch` 接受受控 HMM 样本，返回 HTTP `200` 和 UUID job id。
- 轮询 job 返回 HTTP `200`，其中 `algo=hmmsearch`、`input_type=hmm`、`database=pdb`，task status 为 `FAILURE`。
- 拉取 result 返回 HTTP `200`，payload 为 `status=FAILURE`、`result=null`、`page_count=null`。
- 使用 aligned FASTA/MSA 样本重复提交，同样返回 UUID job id，但 task 立即进入 `FAILURE`。
- 2026-05-27 使用 Pfam PF00069 HMM（`Pkinase`，`LENG 262`）提交 `database="refprot"`，返回 job id `fdaf751e-bf95-4e6a-a70a-6eadf2078ae2`。
- known-good job 轮询返回 `SUCCESS`，`database=refprot`，`input_type=hmm`，`number_of_hits=1384826`，`number_of_included=1354281`，`date_done=2026-05-27T07:16:27.791Z`。
- 拉取 result page 1、`page_size=3` 返回 `SUCCESS`，`page_count=461609`，包含 3 条 hit；第一条 hit 的 `score=1834.7283935546875`、`evalue=0`。
- 早期失败样本是 20 aa toy HMM / toy MSA，并且使用 `database=pdb`；该失败不能作为 EBI HMMER provider unavailable 证据，只能作为 invalid/unsuitable sample failure mapping 的输入。

状态判断：`ok`。

原因：endpoint、schema 和 database inventory 可达，known-good HMM 对 `refprot` 的 submit、polling 和 result pagination 已成功。S13 仍必须实现 failed-job mapping、empty-result mapping、pagination recovery、bounded result artifactization 和 schema validation；S15 仍必须用 AOX/HMM 固定 prompt 和当前真实 HMM 重新证明 cutover。

### Provider 边缘语义观察

| Provider operation | Pagination | Polling | Timeout | Quota/rate limit | Partial result | Empty result | Schema drift |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `bio.ncbi_fetch_proteins` | 单批 accession fetch probe 不涉及分页；S13 仍需实现 batch policy。 | 不适用。 | 本地 probe 使用有界请求 timeout；未诱发 provider timeout。 | Response 暴露 `x-ratelimit-limit: 3` 和 `x-ratelimit-remaining`；未诱发 429。 | 未观察到；未来 adapter 必须 map partial batch failures。 | invalid id 返回 HTTP `200` 和 provider error text，不能当成 empty FASTA success。 | 对一个 accession 观察到 FASTA header/body shape；metadata schema 未证明。 |
| `bio.uniprot_fetch` | 已观察到两个单结果页面的 cursor pagination。 | 不适用。 | 本地 probe 使用有界请求 timeout；未诱发 provider timeout。 | 未观察到 429；观察到 release/deployment headers。 | 未观察到；两条结果查询跨两页完成。 | 合法 accession 形状的 no-hit query 返回 HTTP `200` 且 `results` 为 0。 | success 与 invalid-format error 的预期 JSON keys 已观察到；未诱发 drift。 |
| `bio.hmmer_search` | known-good `refprot` job 已观察到 result pagination；page 1 / `page_size=3` 返回 3 条 hit，`page_count=461609`。 | 已观察到 submit/status/result polling endpoints；known-good job 从 submitted 到 `SUCCESS`。 | 本地 probe 使用有界请求 timeout；未诱发 provider timeout。 | 未观察到 429。 | 未观察到；S13 仍需处理 partial/failure states。 | toy sample failed；未观察到 empty-hit success。 | OpenAPI schema 可达；failed job result payload 为 `status=FAILURE`、`result=null`、`page_count=null`，successful result payload 包含 `status`、`result.hits` 和 `page_count`。 |

## Host Local Non-route Observations

### Host Local Runtime Packaging

Sandbox SDK import probe：

- `openzyme_pipeline` 在本地 package environment 中可成功 import。
- 当前 `openzyme_pipeline.__all__` 为 `artifacts,bio,bio_tools,hpc,preprocess,run`。
- 当前 `hpc` export 只作为 current-state context 记录；agent-facing HPC SDK namespace 的去留将由 Session 11 在 persistent sandbox 外部能力桥完成后重新决策，不是任何 Session 06 `bio_tools.*` backend 的证据。

<a id="host-local-non-route-hmmer"></a>

### Host Local Non-route Observation：HMMER

Runtime packaging：Host-local Apptainer/SIF。

观察结果：

- Apptainer runtime 可用；`apptainer --version` 返回 `apptainer version 1.4.5`。
- HMMER SIF digest 匹配 `d46324cc2a1bc93d68997960c6aeb035f46e2037dbdb9cb609dc8492bbdd9634`。
- `hmmbuild -h`、`hmmalign -h` 和 `hmmsearch -h` 均显示 `HMMER 3.4 (Aug 2023)`。
- 受控 `hmmbuild` smoke exit code 为 `0`，产物以 `HMMER3/f [3.4 | Aug 2023]` 开头。
- 受控 `hmmalign` smoke exit code 为 `0`，产物以 `# STOCKHOLM 1.0` 开头，并包含预期 query rows。
- 受控 `hmmsearch --tblout` smoke exit code 为 `0`，tblout 文件包含 `target1` 的非注释 hit row。

状态判断：

- 这些 HMMER observation 只证明本次 operator 环境曾经可以通过 Host-local SIF 跑受控小样本。
- 根据当前部署标准，本机默认不安装 AOX/HMM 生信工具；所有跑通最终 AOX/HMM 测试所需的 CLI 生信工具统一安装到 HPC。
- 因此 `hmmbuild`、`hmmalign` 和 `hmmsearch` 的 Host-local observation 均不能进入 `bio_tools.*` evidence matrix 的 primary route，也不能作为 HPC prerequisite 缺失时的 fallback。

已执行的 expected output validation：

- HMM output 以 HMMER format marker 开头。
- Alignment output 以 Stockholm marker 开头，并包含预期 sequence rows。
- Search table 包含 HMMER tblout header 和至少一个非注释 target hit。

Host-local 非 route observation 表：

| Tool | Configured path status | Resolved path status | Version evidence | Exit code evidence | stdout/stderr summary | Runtime packaging | Resource limit evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `hmmbuild` | 通过 digest 选择 Host-local SIF；不记录 path。 | entrypoint 在 SIF 内 resolved；不记录 path。 | `-h` 显示 `HMMER 3.4 (Aug 2023)`。 | help `0`；smoke `0`。 | help 显示 usage；smoke summary 显示 3 条 sequence、alignment length 20、model length 20。 | `host_apptainer_sif` | 非 route observation；Session 14 必须用 HPC evidence 证明 production route。 |
| `hmmalign` | 通过 digest 选择 Host-local SIF；不记录 path。 | entrypoint 在 SIF 内 resolved；不记录 path。 | `-h` 显示 `HMMER 3.4 (Aug 2023)`。 | help `0`；smoke `0`。 | help 显示 usage；smoke output 为 Stockholm 且包含预期 rows。 | `host_apptainer_sif` | 非 route observation；Session 14 必须用 HPC evidence 证明 production route。 |
| `hmmsearch` | 通过 digest 选择 Host-local SIF；不记录 path。 | entrypoint 在 SIF 内 resolved；不记录 path。 | `-h` 显示 `HMMER 3.4 (Aug 2023)`。 | help `0`；supplementary smoke `0`。 | help 显示 usage；supplementary smoke 输出包含一个 hit 的 tblout。 | `host_apptainer_sif` | 非 route observation；Session 14 必须用 HPC evidence 证明 production route。 |
| `mafft` | 无 configured Host-local path。 | 当前 shell PATH 中缺失。 | 无。 | `127`。 | command not found。 | `configured_binary` missing | 未证明。 |
| `cd-hit` | 无 configured Host-local path。 | 当前 shell PATH 中缺失。 | 无。 | `127`。 | command not found。 | `configured_binary` missing | 未证明。 |

### Host Local Non-route Observation：MAFFT / CD-HIT

观察结果：

- `mafft --version` 失败，原因是 command-not-found。
- `cd-hit -h` 失败，原因是 command-not-found。
- `cd-hit-est -h` 失败，原因是 command-not-found。

状态判断：

- Host-local MAFFT availability：`prerequisite_missing` / `tool_missing`。
- Host-local CD-HIT availability：`prerequisite_missing` / `tool_missing`。

这符合当前部署标准：Host 本机不作为 AOX/HMM 生信工具部署面。这里只有边界观察价值，不能作为 `bio_tools.*` route evidence。

## Sandbox Image Recommendations

Session 06 不决定 sandbox image 依赖，也不安装依赖。以下只是给 Session 09 实施前确认 `sandbox lightweight dependency allowlist` 的建议输入。

建议考虑的轻量依赖候选：

- `biopython`：用于 sandbox 内 FASTA/sequence 解析、简单格式校验和轻量派生处理；不得用于直接访问 NCBI/UniProt/EBI provider credential 或绕过 `bio.*`。
- `pandas`：用于 sandbox 内 CSV/TSV 表格过滤、打分、排序和 Cytoscape edge/node 表生成；大结果仍应 artifact 化，不能作为 inline RPC payload。
- `numpy`：用于简单数值评分、阈值过滤和向量化派生计算；不代表任何外部 bio tool backend。

不建议放入 sandbox image：

- MAFFT、CD-HIT、HMMER CLI、Apptainer、SSH/Slurm client、HPC runner config、provider credential、database mount 或任何领域 backend packaging。

最终 allowlist 需要在 Session 09 实施前由 operator 明确确认。未确认时，sandbox image 只应按 S07/S09 的最低 contract 验收标准库、`bash`、`python`、`openzyme_pipeline` 和 Host supervisor RPC transport。

<a id="hpc-evidence"></a>

## HPC Evidence

Runner/config 观察：

- 本地 HPC runner config 文件可被 runner package 成功加载。
- Runner mode 加载为 `auto`。
- Runner artifact transport setting 加载为 `use_rsync=True`。
- Configured adapter sections 为 `alphafold3`、`chai_fold`、`colabfold`、`fpocket`、`hhblits`、`tunnels` 和 `vina`。
- Runner MCP tool list 暴露 generic `exec.run`、`job.submit`、`job.status`、`job.logs`、`job.cancel` 和 `job.fetch_artifacts`。

Bio-tool contract / runtime 观察：

- Repo-backed HPC tool contract manifest 中没有 `mafft`、`cdhit`、`cd-hit`、`hmmbuild`、`hmmalign` 或 `hmmsearch` adapter contract。
- 唯一 HMMER-family entry 是 `jackhmmer`，deployment 为 `spack`，support status 为 `blocked_missing_db_or_sample`。
- `jackhmmer` entry 不是必需的 `bio_tools.hmmer_search_cli` contract，不能证明 AOX/HMM HMM search route readiness。
- Diannan operator-managed container directory 中观察到 AOX/HMM 所需 SIF basenames：`mafft_7.525.sif`、`cd-hit_4.8.1.sif`、`hmmer_3.4.sif`；本文不记录 remote path。
- `apptainer --version` 返回 `1.5.0-rc.2-dirty`。
- SIF entrypoint/version help：
  - `mafft --version` 返回 `v7.525 (2024/Mar/13)`。
  - `cd-hit -h` 返回 `CD-HIT version 4.8.1 (built on Dec 13 2024)`。
  - `hmmbuild -h`、`hmmalign -h`、`hmmsearch -h` 均返回 `HMMER 3.4 (Aug 2023)`。
- 新增小样本 fixture：`apps/mcp-hpc-runner/fixtures/hpc_tool_samples/aox_hmm/`。
- Runner SSH smoke `eb1c0f9dfc08` 完成，上传 4 个输入并 fetch 9 个 declared outputs；missing/empty validation 均为空。
- Runner Slurm smoke `ea89d01e8fa8` / job `195538` 完成，fetch 9 个 declared outputs；missing/empty validation 均为空。
- Slurm smoke 覆盖 MAFFT alignment、CD-HIT clustering、`hmmbuild`、`hmmalign` 和 `hmmsearch` against tiny FASTA target set。`hmmsearch.tblout` 含 3 条非注释 hit row；`toy.hmm` 以 `HMMER3/f [3.4 | Aug 2023]` 开头；CD-HIT `.clstr` 含 1 个 cluster 和 4 条成员记录。

状态判断：

- HPC 上的 `bio_tools.mafft` runtime prerequisite：`ok`；S14 仍需固化产品 adapter contract。
- HPC 上的 `bio_tools.cdhit` runtime prerequisite：`ok`；S14 仍需固化产品 adapter contract。
- HPC 上的 `bio_tools.hmmbuild` runtime prerequisite：`ok`；S14 仍需固化产品 adapter contract。
- HPC 上的 `bio_tools.hmmalign` runtime prerequisite：`ok`；S14 仍需固化产品 adapter contract。
- HPC 上的 `bio_tools.hmmer_search_cli` runtime prerequisite：`ok` for tiny FASTA smoke；production logical target database 仍为 `prerequisite_missing` / `database_missing`。S15 主路使用 `bio.hmmer_search(..., database="refprot")` 的 EBI HMMER REST provider，不依赖 HPC target database。

未证明：

- 生产 HMMER target database 的 logical name、version、digest、record count 或 availability。
- S14 产品 adapter contract、typed params schema、command template id、route policy id 和 failure signatures。
- log truncation / failure-log artifactization 的失败路径；本次只证明 successful smoke 的 fetch 与 declared-output validation。
- 正式 `hpc_batch_small` policy 是否采用本次 smoke 的资源值；本次 Slurm smoke 使用 1 CPU、1024 MB、0 GPU、10 minutes、partition `3090`。

<a id="database-evidence"></a>

## Database Evidence

Provider-visible database inventory：

- UniProt REST response 暴露 `x-uniprot-release: 2026_01`。
- EBI HMMER database list 暴露了 [Provider Evidence：EBI HMMER REST](#provider-evidence-ebi-hmmer-rest) 中列出的 enabled logical database names 和 versions。

HPC managed database inventory：

- 未证明任何 HPC HMMER target database 的 logical name、version、digest、record count 或 availability。
- 未证明任何由 HPC policy 管理的 UniProt/RefProt FASTA 或 index inventory。
- 本文不记录 private path 或 mount。

状态判断：

- Provider logical DB inventory：UniProt 和 EBI HMMER 的部分信息已观察到。
- HPC toolchain DB inventory：`prerequisite_missing` / `database_missing` for optional offline/HPC `bio_tools.hmmer_search_cli` route；不阻塞 Session 06 作为当前 S15 主路实施输入的完成判断。

## Parameter Inventory

Session 06 只记录参数能力证据。它不定义最终 Session 14 的 `params` schema、allowlist、SDK contract 或 route policy。

<a id="parameter-inventory-mafft"></a>

### Parameter Inventory：MAFFT

证据引用：

- MAFFT v7 官方手册：`https://mafft.cbrc.jp/alignment/software/index.html`。
- MAFFT 官方 algorithms/parameters 页面：`https://mafft.cbrc.jp/alignment/software/algorithms/algorithms.html`。
- 已捕获 HPC SIF 中当前 MAFFT help/version evidence：`mafft --version` 返回 `v7.525 (2024/Mar/13)`。

AOX/HMM 必需能力：

- 输入 FASTA artifact。
- 输出 MSA artifact。
- 适用于 protein sequence alignment 的 algorithm selection。

Session 14 可考虑的安全 typed logical params：

- alignment mode enum，例如 `auto`、`fast` 或 `accurate`。
- 如果 Host 不能安全 infer，可暴露 sequence type enum。
- 只有在针对已安装版本验证后，才考虑保守的 gap/algorithm knobs。

Host-policy-managed params：

- threads、memory、walltime、partition/queue、temporary directory、output path、log cap 和 max input size。

Forbidden params：

- Host path、HPC remote path、shell metacharacter、output redirect、arbitrary command、raw passthrough string、custom executable 和 file path override。

<a id="parameter-inventory-cd-hit"></a>

### Parameter Inventory：CD-HIT

证据引用：

- CD-HIT User's Guide：`https://www.bioinformatics.org/cd-hit/cd-hit-user-guide`。
- CD-HIT upstream guide：`https://github.com/weizhongli/cdhit/blob/master/doc/cdhit-user-guide.wiki`。
- 已捕获 HPC SIF 中当前 CD-HIT help evidence：`cd-hit -h` 返回 `CD-HIT version 4.8.1 (built on Dec 13 2024)`。

AOX/HMM 必需能力：

- 输入 protein FASTA artifact。
- representative FASTA 输出。
- cluster membership 输出。
- 用于去冗余的 identity threshold。

Session 14 可考虑的安全 typed logical params：

- identity threshold。
- protein/nucleotide mode enum；AOX/HMM 默认应为 protein。
- coverage thresholds 只能作为带范围校验的 typed numeric fields。
- word length 只能由 Host 推导，或在 identity threshold 约束下做范围校验。

Host-policy-managed params：

- threads、memory、walltime、output base、temporary directory、log cap 和 resource class。

Forbidden params：

- pipeline code 提供的 `-i`/`-o` raw paths、arbitrary executable、shell metacharacter、output redirect、remote path、database mount 和 raw passthrough string。

<a id="parameter-inventory-hmmer-cli"></a>

### Parameter Inventory：HMMER CLI

证据引用：

- 从 Host-local SIF 中捕获的 HMMER `3.4 (Aug 2023)` 仍只是非 route 参数参考；2026-05-28 已从 HPC SIF 安装源重新捕获 `hmmbuild -h`、`hmmalign -h` 和 `hmmsearch -h`，均返回 `HMMER 3.4 (Aug 2023)`。
- HMMER project page：`https://hmmer.org/`。
- 当前 HMMER User's Guide：`https://eddylab.org/software/hmmer/CURRENT/Userguide.pdf`。

AOX/HMM 必需能力：

- `hmmbuild`：MSA artifact 生成 HMM artifact。
- `hmmalign`：HMM artifact 加 FASTA artifact 生成 alignment artifact。
- `hmmsearch`：HMM artifact 加 logical target database 生成 raw/parsed hit artifacts。

Session 14 可考虑的安全 typed logical params：

- 必要时暴露 alphabet assertion enum：`amino`、`dna`、`rna`。
- search 的 reporting/inclusion thresholds 作为 typed numeric fields。
- 必要时暴露 alignment output format enum。
- HMM name/label 只有经过 sanitize 和 bounded 后才可暴露。

Host-policy-managed params：

- CPU workers、memory、walltime、database logical name 到 physical mapping、output filenames、stdout/stderr cap、temporary directory、random seed policy 和 resource class。

Forbidden params：

- Host path、HPC remote path、database mount、pipeline code 直接覆盖 `--cpu`、`--mpi`、arbitrary command、shell metacharacter、output redirect、raw passthrough string，以及未由 Host policy 显式 provision 的 custom substitution matrix path。

## Evidence Matrix

只有下表这些行是 Session 14 的 static backend candidate 输入。推荐 backend 之外的补充观察结果不是 route candidate，不能被解释为 dynamic fallback。

按当前 S15 主路，required rows 是 `bio.ncbi_fetch_proteins`、`bio.uniprot_fetch`、`bio.hmmer_search`、`bio_tools.cdhit`、`bio_tools.mafft`、`bio_tools.hmmbuild` 和 `bio_tools.hmmalign`，这些行均为 `ok`。`bio_tools.hmmer_search_cli` 只保留为 optional offline/HPC route candidate；其 `database_missing` 不阻塞 Session 06 作为 S13/S14/S15 主路实施输入的完成判断。

| operation | backend | status | evidence_ref | prerequisite | resource_class | runtime_packaging | expected_outputs | approval_requirement | parameter_inventory_ref | error_code | remediation_hint |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `bio.ncbi_fetch_proteins` | `provider` | `ok` | [Provider Evidence：NCBI](#provider-evidence-ncbi) | NCBI endpoint 与 configured email/tool identity 已观察；batch policy、timeout、retry 和 rate-limit handling 由 S13 固化 | `network_io` | `provider_http` | FASTA artifact、metadata JSON/CSV artifact、bounded summary | Dry-run 应展示 provider、accession count、batch size、quota/rate-limit summary 和 outputs | N/A |  | S13 必须把 NCBI identity、retry/quota policy 和 invalid accession mapping 固化到 Host provider policy；credential 不得进入 workspace 或 tool result。 |
| `bio.uniprot_fetch` | `provider` | `ok` | [Provider Evidence：UniProt](#provider-evidence-uniprot) | UniProt REST availability、field selection、cursor pagination、invalid-accession handling | `network_io` | `provider_http` | FASTA/sequence artifact、metadata JSON/CSV artifact、bounded summary | Dry-run 应展示 provider、requested fields、page estimate 和 outputs | N/A |  | 真实 adapter 中保留 cursor pagination 和 schema validation。 |
| `bio.hmmer_search` | `provider` | `ok` | [Provider Evidence：EBI HMMER REST](#provider-evidence-ebi-hmmer-rest) | EBI HMMER submit/status/result、database selection、successful result pagination | `network_io` | `provider_http` | raw hits JSON artifact、parsed hits CSV artifact、bounded summary | Dry-run 应展示 provider、database logical name、polling timeout 和 expected hit artifacts | N/A |  | S13 必须把 failed-job、empty-result、pagination、large-result artifactization 和 schema validation 固化到 Host provider adapter；S15 仍需用 AOX/HMM 固定 prompt 重新证明 live cutover。 |
| `bio_tools.cdhit` | `hpc` | `ok` | [HPC Evidence](#hpc-evidence) | HPC CD-HIT SIF/version、Slurm smoke、staging/fetch、declared output validation 已观察；S14 仍需产品 adapter contract | `hpc_batch_small` | `hpc_apptainer_sif` | representative FASTA artifact、cluster membership artifact、summary/log artifacts | Dry-run 必须展示 static backend `hpc`、identity threshold、resource profile 和 declared outputs | [Parameter Inventory：CD-HIT](#parameter-inventory-cd-hit) |  | S14 固化 Host-managed HPC CD-HIT contract、typed params schema、command template 和 failure signatures。 |
| `bio_tools.mafft` | `hpc` | `ok` | [HPC Evidence](#hpc-evidence) | HPC MAFFT SIF/version、Slurm smoke、staging/fetch、declared output validation 已观察；S14 仍需产品 adapter contract | `hpc_batch_small` | `hpc_apptainer_sif` | MSA artifact、summary/log artifacts | Dry-run 必须展示 static backend `hpc`、alignment mode、resource profile 和 declared outputs | [Parameter Inventory：MAFFT](#parameter-inventory-mafft) |  | S14 固化 Host-managed HPC MAFFT contract、typed params schema、command template 和 failure signatures。 |
| `bio_tools.hmmbuild` | `hpc` | `ok` | [HPC Evidence](#hpc-evidence) | HPC HMMER SIF/version、Slurm smoke、staging/fetch、declared output validation 已观察；S14 仍需产品 adapter contract | `hpc_batch_small` | `hpc_apptainer_sif` | HMM artifact、bounded summary、stdout/stderr log artifact | Dry-run 必须展示 static backend `hpc`、HMMER version/source、resource profile 和 declared outputs | [Parameter Inventory：HMMER CLI](#parameter-inventory-hmmer-cli) |  | S14 固化 Host-managed HPC `hmmbuild` contract、typed params schema、command template 和 failure signatures。 |
| `bio_tools.hmmalign` | `hpc` | `ok` | [HPC Evidence](#hpc-evidence) | HPC HMMER SIF/version、Slurm smoke、staging/fetch、declared output validation 已观察；S14 仍需产品 adapter contract | `hpc_batch_small` | `hpc_apptainer_sif` | alignment artifact、bounded summary、stdout/stderr log artifact | Dry-run 必须展示 static backend `hpc`、HMMER version/source、resource profile 和 declared outputs | [Parameter Inventory：HMMER CLI](#parameter-inventory-hmmer-cli) |  | S14 固化 Host-managed HPC `hmmalign` contract、typed params schema、command template 和 failure signatures。 |
| `bio_tools.hmmer_search_cli` | `hpc` | `prerequisite_missing` | [HPC Evidence](#hpc-evidence), [Database Evidence](#database-evidence) | Optional offline/HPC route candidate：HPC HMMER SIF/version、tiny FASTA Slurm smoke、staging/fetch、declared output validation 已观察；production logical target database inventory 缺失 | `hpc_batch_small` | `hpc_apptainer_sif` | raw HMMER output artifact、tblout/domtblout artifact、parsed hits CSV artifact、log artifact | Dry-run 必须展示 static backend `hpc`、database logical name、resource profile 和 declared outputs | [Parameter Inventory：HMMER CLI](#parameter-inventory-hmmer-cli) | `database_missing` | 不计入当前 S15 主路放行条件；若后续启用 offline/HPC `hmmsearch` 产品 route，必须提供 logical database inventory；S15 主路继续使用 EBI HMMER REST `refprot`。 |

## Remediation Hints

- S13 必须把已复核的 NCBI email/tool identity、retry/quota policy 和 invalid accession mapping 固化到 Host provider policy。
- S13 必须把 EBI HMMER REST failed-job、empty-result、pagination、large-result artifactization 和 schema validation 固化到 Host provider adapter；S15 仍需用 AOX/HMM 固定 prompt 重新证明 live cutover。
- 为 MAFFT、CD-HIT、`hmmbuild`、`hmmalign` 和 `hmmsearch` 增加 S14 产品 adapter contracts，包含安全 logical tool ids、resource profiles、staging/fetch expectations、command template ids 和 failure signatures。
- 若启用 offline/HPC `bio_tools.hmmer_search_cli` 产品 route，记录 HPC database logical names、versions、digests、record counts 和 availability，但不得暴露 private paths 或 mounts；S15 主路不依赖该数据库。
- MAFFT/CD-HIT/HMMER CLI 参数必须保持 typed 且 bounded；Session 14 必须拒绝 path、shell、redirect 和 raw passthrough 参数。
- 不能用 deterministic adapters、fixture outputs、synthetic artifacts、Host-local observation、sandbox 内 binary 或 sibling backend 的成功来修复本 matrix 中任何 `prerequisite_missing` 或 `failed` 行。
