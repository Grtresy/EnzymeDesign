# Caver (tunnel detection)

## 下载与安装
Caver 通常以可执行脚本形式发布，建议使用官方发布包或 Conda：
```bash
mamba create -n caver -c bioconda -c conda-forge caver
```
如果使用官方包，请确保 `caver.sh` 在 `PATH` 中。

## 使用说明
1. 确保 `caver.sh` 可执行。
2. 运行：
```bash
snakemake -j 16 --use-conda --conda-frontend mamba --config mode=real
```

## 输出
- tunnels：`runs/<target_id>/<variant_id>/outputs/tunnels/caver/tunnels.json`
