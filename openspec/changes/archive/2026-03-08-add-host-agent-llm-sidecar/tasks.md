## 1. Node Sidecar 基础

- [x] 1.1 在 `apps/` 下新增 Node `pi-ai` sidecar app，安装并锁定 `@mariozechner/pi-ai` 包版本，补齐启动脚本、依赖声明和本地开发入口
- [x] 1.2 实现基于 `stdio` 的结构化请求/响应协议，覆盖 `AgentModelAdapter` 对应的 6 个 sidecar 操作
- [x] 1.3 为 sidecar 增加 provider/model 非敏感配置加载、环境变量凭据注入、schema 校验和规范化错误映射

## 2. Python Runtime 接入

- [x] 2.1 在 `packages/enzyme-host-runtime` 中增加 sidecar 配置模型、配置文件加载入口、进程客户端和生命周期管理
- [x] 2.2 实现 `LLMAgentAdapter`，把 sidecar 响应映射为本地 agent dataclass，并执行二次类型校验
- [x] 2.3 让 `HostRuntime` / `AgentWorkflowOrchestrator` 支持按配置选择 LLM backend，并在需要时回退到 `HeuristicAgentAdapter`
- [x] 2.4 将 backend、provider、model、fallback 和 sidecar 错误摘要写入 canonical agent state / decision trace 元数据

## 3. 宿主界面与服务输出

- [x] 3.1 扩展 episode snapshot 和共享 runtime 服务输出，暴露当前 agent backend 与降级状态
- [x] 3.2 更新 `apps/enzyme-host-cli`，在默认摘要中显示 backend、sidecar 错误和 fallback 状态，并为调试输出保留 provider/model provenance
- [x] 3.3 更新 `apps/enzyme-web-host`，在主界面显示 backend 与 blocked/degraded 状态，并把 provider/model 细节收纳到详情视图

## 4. 验证

- [x] 4.1 为 Node sidecar 增加协议与 schema 测试，覆盖成功响应、无效结构、超时和 provider 错误
- [x] 4.2 为 `LLMAgentAdapter` 增加单元测试，覆盖 sidecar 成功、结构化失败和启发式降级
- [x] 4.3 增加 runtime 集成测试，验证 LLM backend 成功推进 workflow，以及无效输出不会直接触发工具执行

## 5. 文档

- [x] 5.1 更新开发文档，说明 `apps/` 下 sidecar 的安装方式、非敏感配置文件、环境变量凭据和本地调试方法
- [x] 5.2 更新 Web Host / CLI 相关说明，解释首页与详情视图中的 backend provenance、fallback 语义和常见故障排查
