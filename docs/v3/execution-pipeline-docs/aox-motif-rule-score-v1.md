# AOX motif rule scoring v1

本文固定 `aox_motif_rule_score@1` 的开发来源、数学语义与 golden 边界。它描述的是参考位点启发式分数，不是实验活性预测器，也不是候选有效性的生物学保证。

## 授权来源与审计摘要

用户授权以下 ignored、只读 reference 作为规则和结果参考：

| reference 文件 | SHA-256 | 用途 |
|---|---|---|
| `reference/enz_miner_hmm_aox.ipynb` | `57314b470af3d0538d060d8f17f5e780feb57ab60046637513091364e300d8f5` | 原始位点表、坐标映射和历史交互记录 |
| `reference/enz_miner_hmm_aox/run_workflow.py` | `4fd0f55bd3667b3f6b336a0eb18bd235a25ffd818a78b059b1707ffd4f7b4cb4` | 独立 runner 中的规则与相似度实现 |
| `reference/enz_miner_hmm_aox/AOX_coordinate_reference_AAB57849.1.fasta` | `e954dcb39ac3e131855ccf8189165c4a803b318dcc7facf92479c5ded0037a19` | 开发期坐标 reference 对照 |
| `reference/enz_miner_hmm_aox/AOX_all_sequences_for_msa.mafft.fasta` | `993ee2b3175abb68d2e1a4aad56edce1c3d33a19b07a600912fe6844e6484bfa` | 开发期 golden 行提取和全量重算 |
| `reference/enz_miner_hmm_aox/scored_results.csv` | `2a18e2d207bb606e7cf52c4d6c76772a7bc63e82f50d1778c26ec0c0b1845df5` | 旧浮点行为的反例 |
| `reference/enz_miner_hmm_aox/execution_summary.json` | `c9a9725f48c8fcdb211b01a66fda6dd6e8cada35a3acb43cebdad5adb7bfd5fe` | 历史 runner 计数，仅用于偏差说明 |
| `reference/enz_miner_hmm_aox/nodes.csv` | `df8722d0e9b14e2f58f174a758490e1d35a7d8b559ad3eb418c0040f8993641e` | 旧 graph 输出审计 |
| `reference/enz_miner_hmm_aox/edges_similarity.csv` | `8f69f1243e41fa5d895ef7a081fabef66e3e9e47b3b82a03c6bb69137afaef28` | 旧 similarity 输出审计 |

`reference/` 被仓库 `.gitignore` 排除。产品测试只保存最小、可解释的 tracked golden；live attempt 不得读取、复制、mount 或 materialize 上述文件，历史输出也不得进入 artifact lineage 或 cutover evidence。

## 不把历史行数作为 golden 的原因

Notebook 的 EBI HMMER 分页在第 58/1395 页附近发生 SSL 错误并被 `KeyboardInterrupt` 中止；其保存的 821 条 alignment、218 条通过、209 条候选来自早于当前 alignment 重建的交互状态。当前 runner 又允许复用已有 FASTA、HMM 和 hit CSV，保存的 62 秒运行不是 blank-world 证明。

当前 runner 目录显示 69,717 个 hit、2,675 个 filtered hit、2,689 个 scored row、68 个旧候选和 1,066 条 edge。这些计数反映缓存、分页状态和下述浮点错误，不是 `@1` 的验收常量。

## 规则与精确计算

坐标 reference 必须唯一、精确解析为 `AAB57849.1`。坐标是一基、reference 去 gap 后的残基位置；实现从 alignment 左向右扫描 reference 的每个非 `-` 字符，把 residue coordinate 映射到当前 alignment column。当前 9,932-column alignment 的列号只是一份审计证据，不属于不可变合同：

| residue coordinate | 当前 0-based column | reference residue |
|---:|---:|---|
| 13 | 1508 | G |
| 15 | 1588 | G |
| 18 | 1664 | G |
| 98 | 2770 | F |
| 417 | 6753 | F |
| 566 | 7815 | W |
| 567 | 7832 | H |
| 616 | 8382 | N |
| 660 | 9741 | L |
| 661 | 9888 | A |
| 662 | 9889 | R |
| 663 | 9890 | F |

唯一内部计分单位是十分之一分：

| reference coordinate | 匹配条件 | score tenths |
|---:|---|---:|
| 13 | `G` | +50 |
| 15 | `G` | +50 |
| 18 | `G` | +50 |
| 98 | `F/W/Y` | +50 |
| 417 | `F/W/Y` | +20 |
| 566 | `F/W/Y` | +20 |
| 567 | `H` | +50 |
| 616 | `H/N/P` | +50 |
| 660–663 | 每个非 gap residue | -1 |

`passes_motif_rule = motif_rule_score_tenths >= 336`。`motif_rule_score` 是固定一位小数的展示值。八个正向条件总分 340；任何一个正向条件缺失至少损失 20，因此无法通过。660–663 的 penalty 只影响 336–340 间的精确分值和稳定排序。

旧实现逐次加 `-0.1`，数学上的 `33.6` 会变成 `33.599999999999994` 并被错误拒绝。以整数十分制重算当前 alignment 后，旧通过数 69 变为 520；和 filtered-hit 相交的旧候选数 68 变为 505，其中 451 条位于精确 336 边界。这是 correctional breaking change，不能通过兼容旧 pass flag 修补。

## HMMER AFA 输入规范化

Aligned FASTA 输入绑定 `hmmer_afa_alignment_canonicalization@1`。`input_digest`
始终是规范化前完整输入 bytes 的 SHA-256；换行、大小写或 gap 字符不同都会保留为
不同 raw identity。parser 按 LF 分割物理段，只有确实由 LF 终止的段才可剥掉一个
紧邻 LF 的 CR。文件末尾 lone CR、重复 CR 或物理段中的其他 CR 都不得被解释为
换行或静默删除。

header 的 `>` 必须位于 raw column 0；前导空白后的 `>` 不是 header。显式空物理行
可忽略，但空格或其他 whitespace 组成的非空行不是空行。每条非空 sequence 物理行
必须在 strip、大小写转换或其他 Unicode 规范化之前完整匹配 ASCII
`^[A-Za-z.-]+$`。因此前导、尾随或内部空格、Tab、NBSP、Unicode line separator、
`ß`、`ſ` 和其他非 ASCII 字符全部 fail closed；它们不能借助 `.strip()`、
`.upper()` 的 Unicode 扩张或 `splitlines()` 变成合法残基。

通过 raw 校验后，仅执行两步 canonicalization：ASCII residue 转大写，然后把 HMMER
AFA insert-column gap `.` 转为 canonical alignment gap `-`。所以仅在大小写或
`.`/`-` 上不同的合法输入具有不同 `input_digest`，但产生相同 canonical aligned
sequence、`aligned_sequence_digest`、`alignment_digest`、位点观察和评分 row。
`alignment_digest` 是按 `sequence_id` 排序后的 canonical uppercase/hyphen-gap
records 与 alignment width 的 canonical JSON SHA-256。

## 最小 golden 语义

Tracked golden 从授权 alignment 中只提取三行，并删除三行均为 gap 的列；它不是 live input：

| sequence id | residue vector（13,15,18,98,417,566,567,616,660–663） | score tenths | pass |
|---|---|---:|---|
| `AAB57849.1` | `GGGFFWHNLARF` | 336 | true |
| `tr|K3VE05|K3VE05_FUSPC` | `GGGFFWHN----` | 340 | true |
| `pdb|9AVH|A` | `GGGFVWHH----` | 320 | false |

提取后的 alignment 必须由测试固定 byte digest；正式 canonical golden vector 使用产品字段重新计算 digest，不能把旧 `pass_rule` 字段结构的 digest 冒充 contract digest。相同分数按 `sequence_id ASC` 稳定排序。

当前 tracked 实现身份为：

- implementation digest：`sha256:795535d9d6c232a79bc9791f8c2780c2f4aa64b234b15a83deb8c76d3406871c`
- contract digest：`sha256:71aff3b872aaef3254550db53c7554011923d19293f9c5837ddc4bb8ca0bec10`
- golden input bytes：`sha256:f8fd28b9c1e6f7963a9ae4deb488b79ad1bbd00c3d3630e194f058f72be9ae29`
- golden normalized alignment：`sha256:da5a3f49f3a03b985d143f262eb30b0967a50bbdf12cbe82d0eff0826afd0b9b`
- golden canonical CSV：`sha256:8dde77f5cbf86d861b37da25fabb4cd68d2159e2a9e0304608ac28ee5ecd0cc9`

implementation digest 会随 scorer 源码变化；任何有意修改都必须同时 bump contract 或重新 pin workflow/golden，未同步的 drift 必须在运行前失败。

## 真实 AFA 只读预检（non-cutover）

最终 parser/scorer 对一份真实 HMMER 3.4 AFA 做了普通 `/tmp` 只读预检。输入为
`12,273,402` bytes、`2,562` records、alignment width `4,700`，raw/input digest
为 `sha256:d72e36bc5c0431d8f3806eb4d0d0cadb51e7d3825c873610d8e4c0098eccf7a6`；
规范化后的 alignment digest 为
`sha256:2df12971eae2d83c390f22e689e04e493539cf6be2d79599f33823f0f52df836`，
canonical sequence 中 `.` 计数为零。评分产生 `517` 条 total pass，其中包含坐标
reference `AAB57849.1`；排除 reference 后是 `516` 条 non-reference pass。一次本地
重放用时约 `0.507s`。

这只证明最终代码能读取真实 HMMER `.` gap 输出并保持 raw/canonical digest 与计数
口径。该 AFA 及其上游 bytes 位于普通 `/tmp`，没有 clean-root、sealed artifact、
formal operation、provider、report、offline bundle 或 campaign closure，绝不是 positive
attempt、cutover artifact 或 GO evidence，也不得被后续 live attempt adoption。

## Fail-closed 条件

下列情况不得注册 cutover-eligible scored/candidate artifact：contract、implementation 或 golden digest 漂移；reference 缺失/重复/截断；header 不在 raw column 0；lone/重复/非行终止 CR；sequence line 含 whitespace、非 ASCII、gap/residue 非法；alignment 不等宽或不可解析；规则列不可映射；filtered hit 和 alignment 身份集合不闭合；sequence digest 不一致；legacy-only schema；任何 row 的 residue、score 或 pass 无法重算；candidate/count/FASTA 不一致；CD-HIT 输入不是 candidate artifact；cluster membership 或 graph edge 无法由真实输出重建。

真实 no-hit 或 zero-candidate 可以产生带 header 的规范空 artifact，但必须有完整 provider/tool operation、known-positive probe 和明确 empty-result 报告；它不能被描述为候选发现。
