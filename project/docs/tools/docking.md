# Docking (AutoDock Vina / DiffDock)

## 下载与安装
### AutoDock Vina
推荐通过 Conda：
```bash
mamba create -n vina -c bioconda -c conda-forge autodock-vina
```

### DiffDock
DiffDock 通常通过官方仓库或 Docker 镜像安装，并需要模型权重。
建议参照官方发布说明安装，并确保 `diffdock` 可执行文件在 `PATH` 中。

## 使用说明
1. 准备配体文件：`inputs/ligands/*.sdf`。
2. 确保 `vina` 或 `diffdock` 已安装。
3. 运行：
```bash
snakemake -j 16 --use-conda --conda-frontend mamba --config mode=real
```

## 输出
- docking：`runs/<target_id>/<variant_id>/outputs/docking/docking.json`
