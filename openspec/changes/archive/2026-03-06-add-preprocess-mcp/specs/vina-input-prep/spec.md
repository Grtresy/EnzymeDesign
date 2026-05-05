## ADDED Requirements

### Requirement: Prepare protein receptor for Vina docking
系统 SHALL 接受蛋白 PDB 文件，使用 meeko 添加氢原子、分配 Gasteiger 部分电荷，产出 Vina 兼容的 `.pdbqt` 受体文件。

#### Scenario: Valid PDB produces PDBQT receptor
- **WHEN** 调用 `prepare_receptor(input_path="/path/to/receptor.pdb", output_path="/path/to/receptor.pdbqt")`
- **THEN** 产出非空 `.pdbqt` 文件，文件包含 ATOM 行和电荷字段（每行末尾有数值）

#### Scenario: Default output path derived from input filename
- **WHEN** 调用 `prepare_receptor` 时未指定 `output_path`
- **THEN** 系统在 input_path 同目录产出 `<stem>.pdbqt`，路径在响应中返回

#### Scenario: PDB with HETATM lines processed without error
- **WHEN** 输入 PDB 文件含非标准残基（HETATM 行）
- **THEN** 转换完成（meeko 忽略 HETATM），不返回 error

#### Scenario: Invalid or empty PDB returns error
- **WHEN** 输入文件不是合法 PDB 格式或为空文件
- **THEN** 返回含 `error` 字段的响应，不产出文件

### Requirement: Prepare small molecule ligand for Vina docking
系统 SHALL 接受 SDF/MOL2 文件或 SMILES 字符串，使用 meeko 分配电荷，产出 Vina 兼容的 `.pdbqt` 配体文件。

#### Scenario: SDF input produces PDBQT ligand
- **WHEN** 调用 `prepare_ligand(input_path="/path/to/ligand.sdf", output_path="/path/to/ligand.pdbqt")`
- **THEN** 产出非空 `.pdbqt` 文件，包含 ROOT/ENDROOT/TORSDOF 行（Vina 扭转树结构）

#### Scenario: SMILES input triggers 3D generation then PDBQT
- **WHEN** 调用 `prepare_ligand(smiles="c1ccccc1", output_path="/path/to/ligand.pdbqt")`
- **THEN** 系统先调用 `smiles_to_3d` 生成中间 SDF，再转换为 PDBQT，最终产出合法配体文件

#### Scenario: Invalid input returns error
- **WHEN** `input_path` 不存在且未提供 `smiles`
- **THEN** 返回含 `error` 字段的响应

### Requirement: MCP tool exposes prepare_receptor and prepare_ligand
`mcp-preprocess` 服务 SHALL 分别暴露 `prepare_receptor` 和 `prepare_ligand` 两个工具。
对于 `prepare_ligand` 的入参约束（`input_path` 和 `smiles` 至少提供一个），当前在运行时校验；由于 Claude Code 对自定义工具 top-level `oneOf/anyOf` 的限制，不在 inputSchema 顶层表达该约束。

#### Scenario: Both tools appear in tools/list
- **WHEN** MCP 客户端发送 `tools/list` 请求
- **THEN** 响应中同时包含 `prepare_receptor` 和 `prepare_ligand`

#### Scenario: prepare_receptor call returns output path
- **WHEN** MCP 客户端调用 `prepare_receptor` 且输入合法
- **THEN** 响应 content 中包含 `output_path` 字段，指向产出的 PDBQT 受体文件

#### Scenario: prepare_ligand call returns output path
- **WHEN** MCP 客户端调用 `prepare_ligand` 且输入合法
- **THEN** 响应 content 中包含 `output_path` 字段，指向产出的 PDBQT 配体文件
