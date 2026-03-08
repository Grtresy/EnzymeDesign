# OpenZyme Agent TODO (OpenCode + MCP)

## 目标

- 基于 OpenCode 构建可调用的 OpenZyme Agent。
- 将工作流能力封装为 MCP 工具，通过 skill 编排任务，通过 command 提供用户入口。
- 采用 **Evaluator-first** 路线，先跑通和稳定评估闭环，再扩展到 5-Agent 全闭环。

## 总体方案（分层）

```text
User
  -> /enzyme ... (command)
    -> skill (工作流策略、失败分流、报告模板)
      -> MCP tools (结构化 JSON 输入/输出)
        -> 执行内核 (run_tool.py / score_variants.py / snakemake)
          -> 生信工具 (HHblits/Fold/Fpocket/Caver/Vina/...)
            -> artifacts + meta + leaderboard
```

## 里程碑总览

- [ ] P1（当前优先级最高）确定最少工具集并在 Diannan 服务器部署
- [ ] P2 打通最小 MCP 工具集（preflight/run/status/explain）
- [ ] P3 打通 `/enzyme` 统一命令与 `enzyme-evaluator-round` skill
- [ ] P4 增强可观测性（run_id、日志索引、失败分类、重跑策略）
- [ ] P5 扩展到 Evidence/Prompt/Generator/Update（5-Agent 闭环）

---

## P1：最少工具集 + Diannan 部署（第一步）

服务器已具备（不建议重复安装）
- 生成/折叠核心：alphafold3、colabfold_batch、colabfold_search、colabfold_search_gpu、chai-lab
- 设计模型：LigandMPNN、ProteinMPNN、SoluableMPNN
- 精细评估替代：rosetta
- 额外可用环境：DiffDock、RFdiffusion2、mmseqs2（在 /opt/tools_env）
- 通过 spack 可用：hmmer(jackhmmer)、gromacs、namd、cuda、cudnn
本机（uv 管理 Python）建议安装
- 必装（开发+流程控制）：snakemake、pyyaml、pydantic、biopython、numpy、pandas、scipy、scikit-learn
- 建议（日志与配置）：rich、typer、jinja2
- HITL 前端（二选一）：streamlit 或 gradio
- 文献/RAG 侧：httpx、requests、beautifulsoup4、lxml
- 可选（本机仅调试小样本）：py3Dmol
服务器还需要补装（最小可用闭环）
- P0 必装：
  - 编排：snakemake
  - Evidence 侧补齐：hh-suite（给 hhblits）
  - 结构功能评估：fpocket
  - 通道分析：caver、p2rank（二者至少一个，最好都要）
  - 结构比较：foldseek 或 TM-align（至少一个）
- P1 强烈建议：
  - MSA 备选工具：mafft、clustal-omega、muscle、blast-plus
  - 对接备选工具：autodock-vina 或 gnina（有 DiffDock 时可作为交叉验证）
  - 配体预处理：openbabel、rdkit
- P2 可选：
  - openmm（如果你们要把 MD 打分纳入 Evaluator）
是否需要 ESM3
- 如果接受替代（MPNN/RFdiffusion2 + AF3/ColabFold），可以先不装 ESM3。
- 如果你要和 Slide 完全一致，就再补 ESM3 运行栈（放服务器，不放本机）。
补一句实操建议：你这台服务器现在最关键不是再堆大模型，而是补齐 snakemake + hh-suite + caver/p2rank + fpocket，这样就能把 Real Mode 真正闭环起来。

---

## P2：最小 MCP 工具集

- [ ] `enzyme.preflight`：检查环境、路径、依赖、输入完整性
- [ ] `enzyme.run_workflow`：按模式运行 evaluator workflow（mock/real）
- [ ] `enzyme.get_status`：查询 run_id 状态、阶段、失败原因
- [ ] `enzyme.explain_score`：将 `score_breakdown.json` 转成可读解释

可选扩展：

- [ ] `enzyme.run_step`（调试时单步执行）
- [ ] `enzyme.collect_artifacts`（产物索引/摘要）

---

## P3：Skill 与 Command

### Skills

- [ ] `enzyme-evaluator-round`（预检 -> 执行 -> 汇总 -> 解释）
- [ ] `enzyme-triage-failure`（失败分类与修复建议）
- [ ] `enzyme-hitl-review`（生成审阅清单与决策模板）

### Commands

- [ ] `/enzyme run ...`（统一入口，默认走 evaluator-round）
- [ ] `/enzyme status <run_id>`
- [ ] `/enzyme explain <variant_id|path>`
- [ ] `/enzyme triage <run_id>`

---

## P4：工程稳健性

- [ ] 修复已知流程问题（如 wildcard 输入拼接问题）
- [ ] 统一 real-mode 文档与实现（尤其 Caver 路径与调用方式）
- [ ] 增加 run_id 语义和状态机（queued/running/failed/succeeded）
- [ ] 标准化日志目录与错误码
- [ ] 补齐关键测试：mock 回归 + real smoke

---

## P5：向 5-Agent 闭环扩展

- [ ] Evidence Agent：文献/保守性约束抽取
- [ ] Prompt Agent：多模态 prompt pack 组装
- [ ] Generator Agent：候选序列生成与采样管理
- [ ] Evaluator Agent：继续沿用并增强当前评估内核
- [ ] Update Agent：基于失败模式自动回写下一轮约束

---

## 风险与约束

- [ ] 安全治理：清理/失效历史明文 token，严禁写入仓库
- [ ] 资源治理：大模型与数据库体量大，先做路径与配额策略
- [ ] 成本治理：坚持两级筛选，避免高成本步骤过早全量运行

## 本周建议执行顺序

1. 先完成 P1 的“最少工具集确认 + Diannan 部署 + mock/real smoke”。
2. 再落地 P2 的最小 MCP 四件套。
3. 最后接 P3 的 `/enzyme` 命令入口。
