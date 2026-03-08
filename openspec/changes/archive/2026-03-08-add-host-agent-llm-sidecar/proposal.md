## Why

当前 `host-agent-planning` 默认依赖启发式适配器来生成设计契约、候选动作和 observation 摘要，尚未接入真实 LLM，因此只能验证 workflow 骨架，无法支撑实际的多轮决策。既然 Host runtime、Web Host、CLI 和 project memory 的 agent 基础已经完成，下一步最关键的是把真实模型能力接到现有编排边界上，而不是再引入新的编排框架。

## What Changes

- 新增一个基于 Node 和 `pi-ai` 的 sidecar 进程，统一承接多 provider LLM 调用、结构化输出和模型调用元数据。
- 在 `packages/enzyme-host-runtime` 中新增 Python 侧的 `AgentModelAdapter` 实现，通过受控的 sidecar 协议请求设计契约、候选动作、动作选择、澄清问题和 observation 摘要。
- 让 host agent backend 变为可配置：默认仍可保留启发式适配器用于测试和离线开发，但在配置开启时优先使用 LLM adapter。
- 为 sidecar 调用失败、结构化输出校验失败、超时和 provider 不可用场景定义一致的降级与错误呈现行为，避免 workflow 因外部模型依赖进入不可恢复状态。
- sidecar 依赖通过安装 npm 发布的 `@mariozechner/pi-ai` 包接入，并锁定明确版本，而不是把 `pi-ai` 或 `pi-mono` 源码 vendoring 到仓库中。
- 增加 sidecar 协议、配置、假实现和集成测试，验证 Python runtime 与 Node sidecar 之间的结构化契约。

## Capabilities

### New Capabilities
- `host-agent-llm-sidecar`: 定义 Host agent 与 Node `pi-ai` sidecar 之间的结构化模型调用契约、配置和失败语义。

### Modified Capabilities
- `host-agent-planning`: 将 agent 决策 backend 从仅启发式适配器扩展为支持真实 LLM adapter、结构化输出校验以及受控降级。
- `web-chat-host`: 在浏览器宿主中显示当前 agent backend、降级状态和 sidecar 错误摘要，并将 provider/model 细节收纳到详情视图。

## Impact

- `packages/enzyme-host-runtime`：新增 LLM adapter、sidecar client、配置模型和降级策略。
- 在 `apps/` 下新增一个 Node sidecar app，用于封装 `pi-ai` provider 访问与结构化响应。
- `apps/enzyme-web-host` 与 `apps/enzyme-host-cli`：显示当前 agent backend、sidecar/LLM 错误和降级状态。
- 测试体系：新增 sidecar 协议测试、adapter 集成测试和失败恢复测试。
- 依赖：引入 npm 发布的 `@mariozechner/pi-ai` 依赖并锁定版本，在仓库内维护 Python 与 Node 的跨进程调用边界。
- 配置：新增非敏感 agent/backend 配置文件加载方式，并继续通过环境变量注入 provider 凭据。
