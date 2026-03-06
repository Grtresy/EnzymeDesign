## ADDED Requirements

### Requirement: Generate 3D conformer from SMILES string
系统 SHALL 接受 SMILES 字符串，使用 rdkit ETKDGv3 算法生成带 3D 坐标的 SDF 文件，并进行能量最小化（MMFF94 力场）。

#### Scenario: Valid SMILES produces SDF with 3D coordinates
- **WHEN** 调用 `smiles_to_3d(smiles="CC(=O)Nc1ccc(O)cc1", output_path="/tmp/mol.sdf")`
- **THEN** 产出非空 `.sdf` 文件，文件中包含 3D 坐标（Z 轴值不全为 0）

#### Scenario: Multiple conformers requested
- **WHEN** 调用 `smiles_to_3d` 时指定 `n_confs=10`
- **THEN** 产出的 SDF 文件包含最多 10 个构象（实际数量取决于 rdkit 采样结果）

#### Scenario: Invalid SMILES returns error
- **WHEN** 调用 `smiles_to_3d` 时 `smiles` 不是合法的 SMILES 字符串
- **THEN** 返回含 `error` 字段的响应，不产出文件

#### Scenario: Default output path uses temporary file
- **WHEN** 调用 `smiles_to_3d` 时未指定 `output_path`
- **THEN** 系统在临时目录生成文件，路径在响应中返回；调用方负责在使用后清理该文件

### Requirement: MCP tool exposes smiles_to_3d
`mcp-preprocess` 服务 SHALL 通过 `tools/list` 暴露 `smiles_to_3d` 工具，inputSchema 包含 `smiles`（required）、`output_path`（optional）、`n_confs`（optional，default 1）。

#### Scenario: Tool appears in tools/list
- **WHEN** MCP 客户端发送 `tools/list` 请求
- **THEN** 响应中包含名为 `smiles_to_3d` 的工具及其 inputSchema

#### Scenario: Successful tool call returns output path
- **WHEN** MCP 客户端调用 `smiles_to_3d` 且 SMILES 合法
- **THEN** 响应 content 中包含 `output_path` 字段，指向产出的 SDF 文件
