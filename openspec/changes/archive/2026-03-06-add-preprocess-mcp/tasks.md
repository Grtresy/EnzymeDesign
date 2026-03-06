## 1. uv Workspace 迁移

- [x] 1.1 在项目根目录新建 `pyproject.toml`，声明 `[tool.uv.workspace]` members = ["apps/*", "packages/*"]
- [x] 1.2 删除 `apps/mcp-hpc-runner/uv.lock` 和 `apps/mcp-hpc-tool-contracts/uv.lock`
- [x] 1.3 在根目录执行 `uv sync`，生成根级 `uv.lock`
- [x] 1.4 验证现有 app 测试通过：`uv run --package mcp-hpc-tool-contracts pytest`
- [x] 1.5 更新根级 `pytest.ini`：testpaths 追加 `packages`

## 2. packages/preprocess-backend 骨架

- [x] 2.1 创建 `packages/preprocess-backend/pyproject.toml`（name, dependencies: openbabel, rdkit, meeko）
- [x] 2.2 创建 `packages/preprocess-backend/src/preprocess_backend/__init__.py`
- [x] 2.3 创建 `packages/preprocess-backend/src/preprocess_backend/models.py`（ConversionResult dataclass）
- [x] 2.4 创建 `packages/preprocess-backend/tests/` 目录及 `conftest.py`
- [x] 2.5 执行 `uv sync` 确认 preprocess-backend 的依赖（openbabel/rdkit/meeko）解析成功

## 3. preprocess-backend 核心操作

- [x] 3.1 实现 `operations/format_convert.py`：`convert_format(input_path, fmt_out, output_path=None) -> ConversionResult`，基于 openbabel Python bindings
- [x] 3.2 为 `convert_format` 编写单元测试（CIF→PDB、SDF→PDBQT、不支持格式报错）
- [x] 3.3 实现 `operations/conformer.py`：`smiles_to_3d(smiles, output_path=None, n_confs=1) -> ConversionResult`，基于 rdkit ETKDGv3 + MMFF94
- [x] 3.4 为 `smiles_to_3d` 编写单元测试（合法 SMILES、非法 SMILES 报错）
- [x] 3.5 实现 `operations/receptor_prep.py`：`prepare_receptor(input_path, output_path=None) -> ConversionResult`，基于 meeko
- [x] 3.6 实现 `operations/receptor_prep.py`：`prepare_ligand(input_path=None, smiles=None, output_path=None) -> ConversionResult`，SMILES 输入时先调用 `smiles_to_3d`
- [x] 3.7 为 `prepare_receptor` 和 `prepare_ligand` 编写单元测试

## 4. apps/mcp-preprocess 骨架

- [x] 4.1 创建 `apps/mcp-preprocess/pyproject.toml`（依赖 preprocess-backend via workspace = true，entry point: mcp-preprocess-server）
- [x] 4.2 创建 `apps/mcp-preprocess/src/mcp_preprocess/__init__.py`
- [x] 4.3 创建 `apps/mcp-preprocess/src/mcp_preprocess/cli.py`（argparse，启动 server）

## 5. apps/mcp-preprocess MCP 服务器

- [x] 5.1 实现 `server.py`：`MCPPreprocessServer` 类，JSON-RPC 2.0 stdio（参照 mcp-hpc-tool-contracts/server.py 模式）
- [x] 5.2 注册 `convert_format` 工具（inputSchema: input_path required, fmt_out required, output_path optional）
- [x] 5.3 注册 `smiles_to_3d` 工具（inputSchema: smiles required, output_path optional, n_confs optional）
- [x] 5.4 注册 `prepare_receptor` 工具（inputSchema: input_path required, output_path optional）
- [x] 5.5 注册 `prepare_ligand` 工具（inputSchema: input_path optional, smiles optional, output_path optional；两者至少一个）
- [x] 5.6 实现 `call_tool` 路由：调用对应 preprocess-backend 操作，捕获异常返回 error 字段

## 6. 集成验证

- [x] 6.1 手动测试：启动 `mcp-preprocess-server`，发送 `tools/list` 请求，确认 4 个工具出现
- [x] 6.2 手动测试：CIF → PDB 转换（用 AF3 输出的实际 CIF 文件）
- [x] 6.3 手动测试：SMILES → PDBQT 完整路径（smiles_to_3d + prepare_ligand）
- [x] 6.4 手动测试：PDB → PDBQT 受体准备（用 1iep receptor.pdb）
- [x] 6.5 在 Claude Code MCP 配置中注册 `mcp-preprocess-server`，验证 Agent 可调用
