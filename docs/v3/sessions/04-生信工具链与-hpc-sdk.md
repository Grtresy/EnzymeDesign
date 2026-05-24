# Session 04：生信工具链与 HPC SDK

## 目标

补齐 AOX/HMM 工作流所需的确定性生信工具链边界，明确 MAFFT、CD-HIT、HMMER CLI、Biopython、pandas 等依赖如何通过 Host-supervised SDK 使用。目标是让 pipeline 能在受控环境中完成参考序列去冗余、MSA、HMM 构建、HMM 搜索后处理、活性位点打分、候选导出和聚类，而不是依赖 notebook 本地 conda 环境。

## 当前缺口

- 现有 execution SDK 文档主要覆盖 molecular preprocess、fpocket 和 Vina，没有 AOX/HMM 所需的 sequence-mining 工具链。
- notebook 依赖本地 `hmmbuild`、`hmmsearch`、`hmmalign`、`mafft`、`cd-hit`、BioPython、pandas 等环境，当前 V3 没有把这些作为稳定 sandbox image 或 Host/HPC SDK contract。
- MAFFT、CD-HIT、HMMER CLI 当前没有固定 SDK 边界，pipeline code 可能被迫直接 shell/subprocess 调工具。
- 工具缺失、资源超限、命令失败、输出未声明、输入格式错误等失败语义需要明确。

## 实施范围

- 定义 AOX/HMM toolchain capability set：
  - Python library：Biopython、pandas，以及必要的 CSV/FASTA/JSON 处理库。
  - Host-supervised CLI：MAFFT、CD-HIT、HMMER `hmmbuild`、`hmmalign`、`hmmsearch`。
  - HPC supervised CLI：超过本地受控执行资源限制的 MAFFT、CD-HIT、HMMER operation。
- 为每类工具定义输入 artifact 类型、输出 artifact 类型、参数限制、resource estimate、expected outputs 和 provenance。
- Pipeline code 不直接调用 MAFFT、CD-HIT、HMMER binary，不使用 `subprocess` 或 shell 执行这些工具。
- Host/HPC 工具必须通过 `openzyme_pipeline.bio_tools` 间接请求 Host supervisor。
- Host supervisor 决定 operation 在本地受控环境执行还是提交 HPC runner。
- 所有远端输出必须来自 declared `expected_outputs`，由 Host fetch 后登记为 artifact。
- dry-run 必须识别工具调用、资源需求和输出声明。

## 接口变化

- 扩展 execution pipeline docs，新增 AOX/HMM sequence-mining 工具链说明。
- SDK module 固定为 `openzyme_pipeline.bio_tools`，首批函数固定为：
  - `bio_tools.cdhit(input_fasta_artifact_id=..., identity=..., mode=...)`
  - `bio_tools.mafft(input_fasta_artifact_id=..., params=...)`
  - `bio_tools.hmmbuild(alignment_artifact_id=..., params=...)`
  - `bio_tools.hmmalign(hmm_artifact_id=..., fasta_artifact_id=..., params=...)`
  - `bio_tools.hmmer_search_cli(hmm_artifact_id=..., target_fasta_artifact_id=..., params=...)`
- 每个 `bio_tools.*` call 必须声明 expected outputs；未声明输出不得登记为成功 artifact。
- 每个 `bio_tools.*` call 的 dry-run/preflight 必须检查工具版本、输入 artifact 类型、参数限制、资源估计和 approval 需求。
- output artifact metadata 至少记录 tool name、tool version、command template 或 sanitized args、input artifact ids、parameter digest、resource estimate 和 code digest。
- FASTA、HMM、MSA、CSV、`nodes.csv`、`edges_similarity.csv` 等关键输出登记前必须做最小格式检查；路径存在但内容为空、格式不合法或必需列缺失时，不能登记为成功 artifact。
- declared expected outputs 不只检查路径存在，还必须检查关键格式或必需列；格式不满足时返回结构化失败并保留诊断日志。
- stdout/stderr、tool logs 和大型中间结果必须有 size cap；超限内容写入 artifact catalog，RPC/result 只返回截断摘要、artifact ref、digest 和关键错误片段。
- 工具失败返回结构化错误：`tool_missing`、`invalid_fasta`、`resource_limit_exceeded`、`declared_output_missing`、`unexpected_output_rejected`、`hpc_runner_timeout`。

## 测试/验收

- dry-run 能在不执行真实长任务的情况下识别 MAFFT、CD-HIT、HMMER CLI/HPC 操作和 expected outputs。
- 缺少 MAFFT/CD-HIT/HMMER 时，preflight 返回 `tool_missing`，不能自动改用其他工具。
- 输入 FASTA/HMM/MSA artifact 类型错误时显式失败。
- pipeline code 直接调用 MAFFT、CD-HIT、HMMER binary、shell 或 subprocess 时，dry-run/preflight 必须拒绝。
- Host/HPC 工具输入必须来自 artifact catalog staging，不能使用 Host 本地 artifact path。
- 远端输出只登记 declared `expected_outputs`；未声明输出被拒绝或忽略并记录 warning，已声明但格式不合法的输出必须失败。
- 资源超限、超时、非零退出码、空输出、格式解析失败、日志截断都进入 run/event/provenance，可被 executor 总结给 master。
- unit/fixture tests 必须覆盖 `bio_tools.cdhit(...)`、`bio_tools.mafft(...)`、`bio_tools.hmmbuild(...)`、`bio_tools.hmmalign(...)`、`bio_tools.hmmer_search_cli(...)`、直接 CLI 调用拒绝、declared expected outputs 登记、关键输出格式校验和 oversized log artifact 化。

## 明确不做什么

- 不把 notebook 的 conda 路径、`aox_work/` 临时目录或本机 binary path 当作产品接口。
- 不允许 executor 直接调用 SSH、Slurm、runner config 或任意 shell。
- 不在本 session 做 AOX/HMM 端到端验收，只补工具链能力和边界。
- 不把 Cytoscape GUI 放进 execution pipeline。
- 不用静默 fallback 替代缺失工具或失败命令。
