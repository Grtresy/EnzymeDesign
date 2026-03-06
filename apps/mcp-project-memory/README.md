# mcp-project-memory

`mcp-project-memory` 是一个基于 MCP Python SDK 的本地文件系统状态服务，用来暴露项目配置、episode 状态、run manifest、candidate 摘要和实验结果等长期上下文。

## Quick Start

从仓库根目录：

```bash
uv sync
uv --project apps/mcp-project-memory run pytest
uv --project apps/mcp-project-memory run mcp-project-memory --config apps/mcp-project-memory/config/project_memory.example.toml serve
PYTHONPATH=apps/mcp-project-memory/src .venv/bin/python3 -m mcp_project_memory.cli --config apps/mcp-project-memory/config/project_memory.example.toml serve
```

## Stdio Transport

服务能力本身仍然构建在 MCP Python SDK 之上：

- resources、tools 注册走 `FastMCP`
- 协议处理走 SDK 的 low-level server

但 stdio 传输层没有直接使用 SDK 默认的 `stdio_server()`。

原因是当前仓库环境里的 Python 3.13 下，SDK 默认实现依赖的文本流包装在子进程 pipe 场景中不稳定，自动化测试里会出现：

- client 已写入 `initialize`
- server 已进入 stdio 模式
- 但 server 侧读不到 `stdin` 行

因此这里改用了一个更底层的本地 stdio transport：

- `stdin`：`asyncio.add_reader(...)` + `os.read(...)`
- `stdout`：`os.write(...)`

这只替换了进程标准输入输出的读写方式，没有替换 MCP 协议层、resource/tool 注册方式，也没有偏离 SDK 的 server 生命周期模型。

## Config

示例配置见 `config/project_memory.example.toml`。

支持两种方式：

- `projects_root`：所有项目都位于同一根目录下，目录名即 `project_id`
- `[projects]`：显式把 `project_id` 映射到某个绝对路径

## Resource URIs

- `enzyme://project/{project_id}/config`
- `enzyme://project/{project_id}/episodes`
- `enzyme://project/{project_id}/episode/{episode_id}/goal`
- `enzyme://project/{project_id}/episode/{episode_id}/state`
- `enzyme://project/{project_id}/episode/{episode_id}/plan`
- `enzyme://project/{project_id}/episode/{episode_id}/annotations`
- `enzyme://run/{run_id}/manifest`
- `enzyme://candidate/{candidate_id}/summary`
- `enzyme://experiment/{experiment_id}/result`

## Tools

- `update_episode_state`
- `record_decision`
- `confirm_plan`
- `save_structure_annotations`
- `import_experiment_results`
- `archive_episode`

## Workspace Layout

最小目录布局：

```text
<project_root>/
  enzyme.yaml
  episodes/
    <episode_id>/
      goal.md
      state.json
      plan.yaml
      annotations.json
      decision_log.jsonl
      runs/
      artifacts/
      manifest.json
  .enzyme/
    indexes/
      runs.json
      candidates.json
      experiments.json
```
