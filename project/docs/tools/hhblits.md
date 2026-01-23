# HHblits (MSA)

## 下载与安装
建议通过 Conda 安装 HH-suite：
```bash
mamba create -n hhblits -c bioconda -c conda-forge hh-suite
```
同时准备 HHblits 数据库（如 UniRef、Uniclust），并记录数据库路径。

## 使用说明
1. 配置数据库路径（建议新增到 `config/config.yaml`）。
2. 确保 `hhblits` 命令在 `PATH` 中。
3. 运行：
```bash
snakemake -j 16 --use-conda --conda-frontend mamba --config mode=real
```

## 输出
- MSA：`runs/<target_id>/<variant_id>/outputs/features/msa.a3m`
