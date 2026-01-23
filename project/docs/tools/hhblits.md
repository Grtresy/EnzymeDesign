# HHblits (MSA)

## 下载与安装
建议通过 Conda 安装 HH-suite：
```bash
mamba create -n hhblits -c bioconda -c conda-forge hh-suite
```
同时准备 HHblits 数据库（如 UniRef、Uniclust），并记录数据库路径。

## 使用说明
1. 配置数据库路径与默认参数（`config/config.yaml` 示例）：
   ```yaml
   hhblits_db: /path/to/hhblits_db
   hhblits:
     evalue: 1e-3
     num_iterations: 3
     maxseq: 10000
     cpu: 4
     extra_args: []
   ```
2. 确保 `hhblits` 命令在 `PATH` 中。
3. 使用 Snakemake 与 mamba 管理环境并运行：
```bash
snakemake -j 16 --use-conda --conda-frontend mamba --config mode=real
```

## 输出
- MSA：`runs/<target_id>/<variant_id>/outputs/features/msa.a3m`
