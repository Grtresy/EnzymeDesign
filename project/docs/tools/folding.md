# Folding Backends (ESMFold / OmegaFold / OpenFold)

## 下载与安装
- **ESMFold**：推荐通过官方仓库或容器安装。GPU 环境建议使用官方提供的 Docker 镜像，CPU 环境可使用官方 Python 包与权重文件。
- **OmegaFold**：通过官方仓库或容器安装，并下载对应模型权重。
- **OpenFold**：通过官方仓库编译，确保依赖与模型权重齐备。

> 由于不同后端的依赖栈差异较大，建议使用独立的 Conda 环境或容器，并在 `config/config.yaml` 中配置可执行文件路径。

## 使用说明
1. 在 `config/config.yaml` 中配置：
   - `structure_backends`: 候选后端列表（如 `esmfold`, `omegafold`, `openfold`）。
   - `structure_primary_backend`: 主后端名称。
   - `structure_backend_configs.<backend>`: 每个后端的可执行路径与权重参数，例如：
     ```yaml
     structure_backend_configs:
       esmfold:
         executable: /opt/esmfold/bin/esmfold
         model_weights: /opt/esmfold/weights/esmfold_v1.pt
         args: ["--device", "cuda"]
     ```
2. 确保后端可执行文件在 `PATH` 中，或在脚本中显式指定路径。
3. 使用 Snakemake + mamba 管理环境并运行：
   ```bash
   snakemake -j 16 --use-conda --conda-frontend mamba --config mode=real
   ```

## 输出
- 结构文件：`runs/<target_id>/<variant_id>/outputs/structures/<backend>/variant.pdb`
- 置信度：`.../structure_confidence.json`
