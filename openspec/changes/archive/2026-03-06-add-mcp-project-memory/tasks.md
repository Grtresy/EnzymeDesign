## 1. 服务骨架与配置

- [x] 1.1 创建 `apps/mcp-project-memory/pyproject.toml`，声明可执行入口、开发依赖和 MCP Python SDK 稳定版本依赖
- [x] 1.2 创建 `apps/mcp-project-memory/src/mcp_project_memory/__init__.py`
- [x] 1.3 创建 `apps/mcp-project-memory/src/mcp_project_memory/cli.py`，支持启动基于 SDK 的 stdio MCP server 与加载配置
- [x] 1.4 创建 `apps/mcp-project-memory/src/mcp_project_memory/server.py`，用 MCP Python SDK 初始化 server，并组织 tool/resource 注册入口
- [x] 1.5 提供示例配置文件，定义项目工作区根目录或项目 id 到根目录的映射方式

## 2. 数据模型与存储层

- [x] 2.1 实现 `models.py`，定义 project / episode / decision / run manifest / candidate summary / experiment result 的最小结构
- [x] 2.2 实现 `store.py`，封装项目根目录解析、资源 URI 到文件路径的映射和边界校验
- [x] 2.3 实现原子写入辅助逻辑，确保 `state.json`、`plan.yaml`、`annotations.json`、`manifest.json` 写入不会产生半写状态
- [x] 2.4 实现索引读取与更新逻辑，支持 episode 列表、run manifest、candidate summary、experiment result 的定位

## 3. 资源读取能力

- [x] 3.1 基于 SDK 注册 `enzyme://` resources，列出配置项目下可见的资源
- [x] 3.2 实现 `project config`、`episodes`、`goal`、`state`、`plan`、`annotations` 的 resource 读取逻辑
- [x] 3.3 实现 `run manifest`、`candidate summary`、`experiment result` 的 resource 读取逻辑
- [x] 3.4 为 URI 解析和越界访问补充单元测试，覆盖合法 URI、缺失资源和路径穿越输入

## 4. 状态写入工具

- [x] 4.1 基于 SDK 注册 `update_episode_state`，把结构化状态写入 canonical state 文件
- [x] 4.2 基于 SDK 注册 `record_decision`，生成稳定 `decision_id`、时间戳并追加写入决策日志
- [x] 4.3 基于 SDK 注册 `confirm_plan`，将结构化计划写入 canonical plan 文件
- [x] 4.4 基于 SDK 注册 `save_structure_annotations`，持久化 annotations 并与 episode 资源联通
- [x] 4.5 为上述四个 tools 编写测试，验证写入后能通过对应 resource 读回

## 5. 实验反馈与归档

- [x] 5.1 基于 SDK 注册 `import_experiment_results`，写入实验结果并维护与 episode / candidate / run 的引用关系
- [x] 5.2 基于 SDK 注册 `archive_episode`，生成或更新 episode `manifest.json` 并标记归档状态
- [x] 5.3 为实验结果导入和 episode 归档补充测试，验证 lineage 引用和 manifest 内容

## 6. 文档与验证

- [x] 6.1 编写 `apps/mcp-project-memory/README.md`，说明 SDK 依赖、目录布局、资源 URI、tools 与启动方式
- [x] 6.2 用项目夹具执行一次基于 SDK 的 `tools/list`、`resources/list`、`resources/read` 与关键 `tools/call` 端到端验证
- [x] 6.3 运行 `openspec validate add-mcp-project-memory`，确认变更文档通过校验
