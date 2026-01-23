# Fpocket (pocket detection)

## 下载与安装
推荐通过 Conda：
```bash
mamba create -n fpocket -c bioconda -c conda-forge fpocket
```

## 使用说明
1. 确保 `fpocket` 在 `PATH` 中。
2. 运行：
```bash
snakemake -j 16 --use-conda --conda-frontend mamba --config mode=real
```

## 输出
- pockets：`runs/<target_id>/<variant_id>/outputs/pockets/fpocket/pockets.json`
