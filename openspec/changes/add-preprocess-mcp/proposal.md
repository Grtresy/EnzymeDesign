## Why

当前工作流（hhblits → folding → fpocket/tunnels → vina）中，各工具对输入格式要求严格（Vina 需 PDBQT，fpocket/caver 需 PDB，folding 需 FASTA），但上游产物（AlphaFold3 的 CIF、用户提供的 SMILES/SDF）与下游工具的格式之间没有任何桥接层，导致 Agent 无法自动完成端到端工作流。

## What Changes

- **新增** `packages/preprocess-backend`：纯本地分子格式转换库（openbabel-wheel + rdkit + meeko），无 HPC 依赖
- **新增** `apps/mcp-preprocess`：轻量 MCP 服务，通过 JSON-RPC stdio 暴露格式转换工具，调用 preprocess-backend
- **新增** 根级 `pyproject.toml`：将项目升级为 uv workspace，统一管理 apps/* 和 packages/* 的依赖与 lock 文件
- **删除** `apps/mcp-hpc-runner/uv.lock` 和 `apps/mcp-hpc-tool-contracts/uv.lock`，由根级 `uv.lock` 替代
- **更新** 根级 `pytest.ini`：testpaths 增加 `packages`

## Capabilities

### New Capabilities

- `molecular-format-conversion`: 分子文件格式互转（CIF↔PDB、SDF↔PDBQT、PDB→SDF 等），基于 openbabel-wheel
- `smiles-to-3d`: 从 SMILES 字符串生成带 3D 坐标的 SDF 文件，基于 rdkit ETKDGv3
- `vina-input-prep`: 为 Vina 对接准备 PDBQT 格式——受体（PDB→PDBQT + 电荷）和配体（SDF/SMILES→PDBQT），基于 meeko
- `uv-workspace`: 根级 uv workspace 配置，统一管理 apps/* 和 packages/* 成员

### Modified Capabilities

## Impact

- `apps/mcp-hpc-runner`、`apps/mcp-hpc-tool-contracts`：加入 workspace，删除各自的 `uv.lock`，依赖关系不变
- `pytest.ini`：testpaths 扩展
- 未来 HPC 路径（obabel on cluster）：通过在 `mcp-hpc-tool-contracts` 新增 obabel adapter 实现，`preprocess-backend` 本身不变
