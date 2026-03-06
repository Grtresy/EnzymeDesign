## Context

现有 HPC 工具（hhblits、fpocket、vina 等）通过 `mcp-hpc-tool-contracts` + `mcp-hpc-runner` 两层架构在 Diannan 集群执行。每个工具的 adapter 都对输入格式有严格要求（Vina 需 `.pdbqt`，fpocket 需 `.pdb`），但上游产物（AF3 CIF、用户 SMILES）与这些格式之间没有任何转换层。

项目目前没有 uv workspace，两个 app 各自维护独立的 `uv.lock` 和 `.venv`，引入共享 `packages/` 库需要先建立 workspace。

## Goals / Non-Goals

**Goals:**
- 引入 uv workspace，统一管理 `apps/*` 和 `packages/*`
- 实现 `preprocess-backend`：纯本地分子格式转换库，零 HPC 依赖
- 实现 `mcp-preprocess`：通过 JSON-RPC stdio 暴露 4 个转换工具
- 现有两个 app 无功能变化，只加入 workspace

**Non-Goals:**
- HPC 路径（obabel on cluster）不在本次范围内
- 批量转换、并发任务管理不在本次范围内
- GUI/Web 界面不在本次范围内

## Decisions

### 1. preprocess-backend 不含任何 HPC 逻辑

**决策**：`packages/preprocess-backend` 是纯本地计算库，不依赖 mcp-hpc-runner 或 mcp-hpc-tool-contracts。

**理由**：HPC 路由是基础设施关切，属于 app 层（`mcp-preprocess`）决策。未来 HPC 路径通过在 `mcp-hpc-tool-contracts` 新增 obabel adapter 实现，`preprocess-backend` 不动。

**备选方案**：在 preprocess-backend 里放 `backends/hpc.py` → 导致纯逻辑库感知 SSH/sbatch 细节，职责混乱，排除。

### 2. MCP 服务器复用 JSON-RPC stdio 模式

**决策**：`mcp-preprocess` 的 server.py 采用与 `mcp-hpc-tool-contracts` 完全相同的 JSON-RPC 2.0 over stdin/stdout 实现，不引入外部 MCP SDK。

**理由**：风格一致，零额外依赖，现有模式已验证可用。

### 3. Python 依赖全部通过 pip 安装，不依赖系统工具

**决策**：使用 `openbabel-wheel`（内含 libopenbabel）、`rdkit`、`meeko`，本机无需安装系统级 obabel。

**理由**：uv 管理的虚拟环境中可直接 `uv add`，不需要 apt/brew，跨平台一致。

**注意**：`openbabel-wheel` 在 PyPI 上发布为 `openbabel`，内含 Python bindings + libopenbabel。

### 4. uv workspace Big Bang 迁移

**决策**：一次性建根级 `pyproject.toml` workspace root，include `apps/*` 和 `packages/*`，删除各 app 的 `uv.lock`。

**理由**：现有两个 app 的 `dependencies = []`，重新 lock 无风险。增量方式（只 include 新成员）会在后续合并时增加麻烦。

### 5. 四个 MCP 工具的粒度

**决策**：
- `convert_format`：通用格式转换（CIF↔PDB、SDF↔PDBQT 等）
- `smiles_to_3d`：SMILES → SDF（3D 构象）
- `prepare_receptor`：PDB → PDBQT（蛋白受体，含电荷）
- `prepare_ligand`：SDF/MOL2/SMILES → PDBQT（小分子配体，含电荷）

**理由**：`prepare_receptor` 和 `prepare_ligand` 虽然都产出 PDBQT，但电荷模型和处理方式不同（meeko 对蛋白和小分子的处理逻辑有别），分开暴露语义更清晰。

## Risks / Trade-offs

- **openbabel Python bindings 在某些平台的 wheel 覆盖不完整** → 优先使用 `openbabel-wheel` 包，如遇平台问题降级到 subprocess 调用系统 obabel
- **meeko 版本与 rdkit 版本耦合较紧** → 在 pyproject.toml 中约束 meeko >= 0.5，rdkit >= 2024
- **uv.lock 迁移后，CI 如有独立 app 的安装步骤需更新** → 当前无 CI，风险低；迁移后记录在 README

## Migration Plan

1. 在根目录新建 `pyproject.toml`（workspace root，无 `[project]` 表）
2. 删除 `apps/mcp-hpc-runner/uv.lock` 和 `apps/mcp-hpc-tool-contracts/uv.lock`
3. 新建 `packages/preprocess-backend/` 和 `apps/mcp-preprocess/`
4. 在根目录执行 `uv sync` 生成新的根级 `uv.lock`
5. 验证：`uv run --package mcp-hpc-runner pytest` 和 `uv run --package mcp-hpc-tool-contracts pytest` 仍正常

**Rollback**：git revert 根级 pyproject.toml，从 git history 恢复各 app 的 uv.lock。

## Open Questions

- `prepare_receptor` 是否需要支持多链 PDB（去除 HETATM、保留 chain A）？当前先做最简版本（直接 meeko 转换），后续按需扩展。
