## ADDED Requirements

### Requirement: Convert molecular file between supported formats
系统 SHALL 支持通过 `convert_format` 将分子结构文件从一种格式转换为另一种格式，使用 openbabel-wheel Python bindings（无需系统级 obabel）。

支持的格式对（最小集）：
- `cif` → `pdb`
- `pdb` → `sdf`
- `sdf` → `pdbqt`
- `pdb` → `pdbqt`（通用转换，不保证电荷模型；Vina 对接请使用 vina-input-prep）

#### Scenario: CIF to PDB conversion
- **WHEN** 调用 `convert_format(input_path="/path/to/structure.cif", fmt_out="pdb")`
- **THEN** 在同目录或指定 output_path 产出 `.pdb` 文件，且文件非空

#### Scenario: SDF to PDBQT conversion
- **WHEN** 调用 `convert_format(input_path="/path/to/ligand.sdf", fmt_out="pdbqt")`
- **THEN** 产出 `.pdbqt` 文件，包含原子坐标和原子类型行（ATOM/HETATM）

#### Scenario: Unsupported format pair returns error
- **WHEN** 调用 `convert_format` 时 `fmt_out` 不在支持列表内
- **THEN** 返回含 `error` 字段的响应，不产出文件

#### Scenario: Input file not found returns error
- **WHEN** `input_path` 指向不存在的文件
- **THEN** 返回含 `error` 字段的响应，不抛出未捕获异常

### Requirement: MCP tool exposes convert_format
`mcp-preprocess` 服务 SHALL 通过 `tools/list` 暴露 `convert_format` 工具，inputSchema 包含 `input_path`（required）、`fmt_out`（required）、`output_path`（optional）。

#### Scenario: Tool appears in tools/list
- **WHEN** MCP 客户端发送 `tools/list` 请求
- **THEN** 响应中包含名为 `convert_format` 的工具及其 inputSchema

#### Scenario: Successful tool call returns output path
- **WHEN** MCP 客户端调用 `convert_format` 且转换成功
- **THEN** 响应 content 中包含 `output_path` 字段，指向产出文件
