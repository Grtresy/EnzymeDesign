# Snakemake Enzyme Design Pipeline

该目录提供一个基于 Snakemake 的酶设计打分流程脚手架，用于读取
`config/config.yaml` 和 `config/target_spec.yaml`，解析 `inputs/variants.txt`
中的变体列表，并产出每个变体的打分细节以及批量排行榜。

## 目录结构
- `config/`: 管线配置与目标信息。
- `inputs/`: 输入数据（目标序列、参考结构、变体列表等）。
- `runs/`: 输出目录（本地运行生成）。
- `cache/`: 中间缓存目录。
- `schemas/`: JSON schema 定义。
- `scripts/`: 工具模拟器与辅助脚本。

## 安装
```bash
cd project
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 运行命令
### Mock 运行（默认 stub 工具）
```bash
cd project
snakemake -j 1
```

### Real 运行（替换真实工具）
本仓库默认通过 `scripts/run_tool.py` 生成 mock 输出。若需真实后端，
请将 `scripts/run_tool.py` 替换为实际工具封装（或在 Snakemake
规则中调用真实二进制/容器），然后执行相同命令：
```bash
cd project
snakemake -j 1
```

## 输出说明
- 单变体产物：`runs/<target_id>/<variant_id>/outputs/` 下包含结构、map、
  conservation、volume、可选 pockets/tunnels/docking 以及 `scores/score_breakdown.json`。
- 批量排行榜：`runs/<target_id>/batch/outputs/scores/leaderboard.csv`。
- 每个 JSON 输出会同时生成 `.meta.json` 元数据文件，记录 run id、参数和输入输出。

## 配置开关说明
`config/config.yaml` 中的 `features` 字段控制可选模块：
- `features.pockets: true/false` 以启用或关闭 pockets 工具。
- `features.tunnels: true/false` 以启用或关闭 tunnels 工具。
- `features.docking: true/false` 以启用或关闭 docking 工具。

目标 ID 可在 `config/config.yaml` 的 `target_id` 或 `config/target_spec.yaml`
中指定，输出路径将基于该 ID。

## 故障排查
- 每个工具执行时会写入 `work/<tool>/stdout.log` 与 `work/<tool>/stderr.log`。
- 解析失败或 schema 校验失败会记录在 `work/<tool>/meta.errors`。
- 若需要清理缓存，可删除 `.cache/run_tool` 或 `runs/` 目录后重试。
