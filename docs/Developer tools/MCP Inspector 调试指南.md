# MCP Inspector 调试指南

本文档记录本仓库各 MCP server 的常用 Inspector 调试命令，以及在远程机器上使用 Inspector 时的端口转发注意事项。

## 前提

- 在仓库根目录执行命令。
- 本地已安装 `node` / `npx`。
- 本地已安装 `uv`。

## 推荐调试顺序

1. `mcp-preprocess`
2. `mcp-hpc-tool-contracts`
3. `mcp-project-memory`
4. `mcp-hpc-runner`

先用依赖最少的 server 验证 Inspector 本身是否正常，再排查依赖 SSH / Slurm / 项目配置的服务。

## 本地调试命令

### 1. mcp-preprocess

最适合先做 Inspector 连通性和 tool schema 检查。

```bash
npx @modelcontextprotocol/inspector \
  uv --directory /home/grtresy/VSCodeRepo/EnzymeDesign/apps/mcp-preprocess \
  run mcp-preprocess serve
```

### 2. mcp-hpc-tool-contracts

先只验证 adapter schema 和编译结果；在 Inspector 的工具参数中优先传 `"_execute": false`，避免直接提交 HPC 作业。

```bash
npx @modelcontextprotocol/inspector \
  uv --directory /home/grtresy/VSCodeRepo/EnzymeDesign/apps/mcp-hpc-tool-contracts \
  run mcp-hpc-tool-contracts serve
```

如果需要通过该 server 直接调用 runner：

```bash
npx @modelcontextprotocol/inspector \
  uv --directory /home/grtresy/VSCodeRepo/EnzymeDesign/apps/mcp-hpc-tool-contracts \
  run mcp-hpc-tool-contracts \
  --runner-config /home/grtresy/VSCodeRepo/EnzymeDesign/apps/mcp-hpc-runner/config/hpc_runner.toml \
  serve
```

### 3. mcp-project-memory

适合在 Inspector 中重点检查 `Resources` tab 和各类 `enzyme://` URI。

```bash
npx @modelcontextprotocol/inspector \
  uv --directory /home/grtresy/VSCodeRepo/EnzymeDesign/apps/mcp-project-memory \
  run mcp-project-memory \
  --config /home/grtresy/VSCodeRepo/EnzymeDesign/apps/mcp-project-memory/config/project_memory.toml \
  serve
```

### 4. mcp-hpc-runner

该服务依赖 SSH / rsync / Slurm 环境，建议最后再测。

```bash
npx @modelcontextprotocol/inspector \
  uv --directory /home/grtresy/VSCodeRepo/EnzymeDesign/apps/mcp-hpc-runner \
  run mcp-hpc-runner \
  --config /home/grtresy/VSCodeRepo/EnzymeDesign/apps/mcp-hpc-runner/config/hpc_runner.toml \
  serve
```

## 单独验证 server 是否能启动

如果 Inspector 页面能打开，但浏览器控制台反复出现以下报错：

- `:6277/config net::ERR_CONNECTION_REFUSED`
- `:6277/health net::ERR_CONNECTION_REFUSED`
- `Couldn't connect to MCP Proxy Server`

这通常不是远端 MCP tool 本身的问题，而是 Inspector 的本地 proxy 没有正常启动，或者被启动后立即退出。

先不要急着怀疑 MCP server 的远程端口暴露。优先单独验证目标 server 能否直接运行：

```bash
uv --directory /home/grtresy/VSCodeRepo/EnzymeDesign/apps/mcp-preprocess run mcp-preprocess serve
```

如果单独运行都失败，先修复 server 启动问题；如果单独运行正常，再回到 Inspector 命令继续排查。

## 远程连接注意事项

如果 Inspector 是在远程机器上启动，而浏览器是在本地机器打开，那么通常需要做 SSH 本地端口转发。

至少转发两个端口：

- `6274`：Inspector Web UI
- `6277`：Inspector 本地 MCP Proxy

示例：

```bash
ssh -L 6274:127.0.0.1:6274 -L 6277:127.0.0.1:6277 <user>@<remote-host>
```

然后：

1. 在远程 shell 中启动 Inspector。
2. 在本地浏览器访问对应页面。

## 常见误区

- 只转发了 Inspector 页面端口，没有转发 proxy 端口。
  结果是页面能打开，但前端请求 `127.0.0.1:6277` 时直接 `ERR_CONNECTION_REFUSED`。
- 把问题归因到 MCP server 的业务端口。
  本仓库这些 server 主要是 `stdio` server，不是先去开放一个独立 HTTP 业务端口给 Inspector 连。
- 一开始就测 `mcp-hpc-runner`。
  该服务依赖最多，最容易把 Inspector 问题和 SSH / Slurm 配置问题混在一起。

## 建议

- 先用 `mcp-preprocess` 验证 Inspector 工作流。
- 再用 `mcp-hpc-tool-contracts`，并优先使用 `"_execute": false`。
- 需要远程调试时，默认检查 `6274` 和 `6277` 两个端口是否都已经转发。
