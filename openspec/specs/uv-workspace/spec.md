## ADDED Requirements

### Requirement: Root pyproject.toml declares uv workspace
项目根目录 SHALL 包含 `pyproject.toml`，其中 `[tool.uv.workspace]` 声明 `members = ["apps/*", "packages/*"]`，使所有 apps 和 packages 成为 workspace 成员。

#### Scenario: Workspace sync succeeds at root
- **WHEN** 在项目根目录执行 `uv sync`
- **THEN** 命令成功，产出根级 `uv.lock` 文件，所有成员依赖被解析

#### Scenario: Existing apps remain functional after workspace migration
- **WHEN** 在根目录执行 `uv run --package mcp-hpc-tool-contracts pytest`
- **THEN** 测试套件通过，与迁移前行为一致

#### Scenario: Existing apps remain functional after workspace migration (runner)
- **WHEN** 在根目录执行 `uv run --package mcp-hpc-runner python -c "import mcp_hpc_runner"`
- **THEN** 模块正常导入，无错误

### Requirement: packages/preprocess-backend is a workspace member with correct dependencies
`packages/preprocess-backend` SHALL 有自己的 `pyproject.toml`，声明 `dependencies = ["openbabel", "rdkit", "meeko"]`，且可被其他 workspace 成员通过 `{ workspace = true }` 引用。

#### Scenario: preprocess-backend installs via workspace reference
- **WHEN** `apps/mcp-preprocess/pyproject.toml` 中声明 `preprocess-backend = { workspace = true }` 并执行 `uv sync`
- **THEN** `preprocess-backend` 在 mcp-preprocess 的环境中可导入

#### Scenario: preprocess-backend unit tests pass
- **WHEN** 执行 `uv run --package preprocess-backend pytest`
- **THEN** 测试套件通过

### Requirement: Single root uv.lock replaces per-app lock files
迁移后 SHALL 只存在一个 `uv.lock`，位于项目根目录。`apps/mcp-hpc-runner/uv.lock` 和 `apps/mcp-hpc-tool-contracts/uv.lock` SHALL 被删除。

#### Scenario: No per-app uv.lock files exist after migration
- **WHEN** 迁移完成后检查仓库
- **THEN** `apps/*/uv.lock` 不存在，仅 `./uv.lock` 存在

### Requirement: pytest.ini testpaths includes packages
根级 `pytest.ini` 的 `testpaths` SHALL 包含 `packages`，使 `uv run pytest` 可发现 packages 下各成员的测试。

#### Scenario: Root pytest discovers preprocess-backend tests
- **WHEN** 在项目根目录执行 `uv run pytest`
- **THEN** `packages/preprocess-backend/tests/` 下的测试被发现并执行
