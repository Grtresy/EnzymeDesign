# Enzyme Shrinkage Closed-Loop Pipeline (Snakemake)

本项目提供一个“可复现、可缓存、可回退”的酶体积缩小闭环流水线，
支持 **mock** 与 **real** 两种模式。mock 模式无需外部工具即可跑通；
real 模式会尝试调用本地已安装的工具并解析输出。

## 目录结构
```
project/
  Snakefile
  config/
    config.yaml
    target_spec.yaml
  inputs/
    target.fasta
    reference_structure.pdb
    variants.txt
    variants/
      <variant_id>.fasta
    ligands/
      cellobiose.sdf
    key_residues.json
    hitl_decisions.csv
  schemas/
  scripts/
    run_tool.py
    score_variants.py
    build_leaderboard.py
    utils/
    tools/
  runs/
  cache/
  requirements.txt
  README.md
```

## 安装
```bash
cd project
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Snakemake + Mamba 环境管理
日常运行建议使用 Snakemake 的 Conda 环境管理（mamba 作为前端），确保每个规则使用独立环境：
```bash
cd project
snakemake -j 16 --use-conda --conda-frontend mamba --config mode=real
```

## 一键运行
### Mock 模式（默认）
```bash
cd project
snakemake -j 4 --config mode=mock
```

### Real 模式
```bash
cd project
snakemake -j 16 --config mode=real
```

## 工具下载与使用说明
真实模式所需工具的下载与使用说明见：
- `docs/tools/folding.md`
- `docs/tools/hhblits.md`
- `docs/tools/fpocket.md`
- `docs/tools/caver.md`
- `docs/tools/docking.md`

## 输入说明
- `inputs/variants.txt`：变体列表（header 包含 `variant_id`）。
- `inputs/variants/<variant_id>.fasta`：变体序列（允许长度变化）。
- `inputs/reference_structure.pdb`：WT 参考结构（至少包含 CA 坐标）。
- `inputs/key_residues.json`：关键位点约束示例。
- `inputs/hitl_decisions.csv`：人工审阅决策示例。
- `inputs/ligands/*.sdf`：可选配体文件。

## 输出说明
- 单变体输出：`runs/<target_id>/<variant_id>/outputs/` 下包含
  `structures/`, `metrics/`, `scores/` 等。
- `geometry_metrics.json`：体积缩小核心指标。
- `score_breakdown.json`：综合评分与排名依据。
- `*.meta.json`：每个 JSON 输出的元数据（缓存、版本、hash 等）。
- 批量排行榜：`runs/<target_id>/batch/outputs/scores/leaderboard.csv`。

## 配置开关说明
- `config/target_spec.yaml` 中 `shrink_mode` 与 `allow_*` 决定体积缩小策略。
- `config/config.yaml` 中 `features.*` 控制 pockets/tunnels/docking 可选模块。

## 常见失败排查
- 查看 `runs/<target_id>/<variant_id>/work/<tool>/stdout.log` 与 `stderr.log`。
- Schema 校验错误会记录在 meta 的 `errors` 字段中。
- 若需要验证回退/重试，可加 `--config fail_tool=fpocket`。
