## Context

当前 `packages/enzyme-host-runtime` 中的 `AgentWorkflowOrchestrator` 已经具备持续决策、审批门控、interrupt 恢复和 observation 回写能力，但默认依赖 `HeuristicAgentAdapter`。这意味着 workflow 的状态机、持久化和 UI 恢复路径已经具备，却仍然缺少真实模型推理能力。

与此同时，仓库主体是基于 `uv` 的 Python monorepo，而候选依赖 `pi-ai` 来自 Node 生态。直接把 Host agent 重写到 TypeScript 或把 `pi-mono` 整体引入当前运行时，都会与现有 Python runtime、tests、workspace 语义和 OpenSpec 已归档设计发生重叠。我们需要的是把真实 LLM 接到既有的 `AgentModelAdapter` 边界上，而不是替换掉整个 Host agent 编排层。

## Goals / Non-Goals

**Goals:**
- 保留现有 Python `HostRuntime`、`AgentWorkflowOrchestrator` 和 canonical project memory 作为状态真源。
- 新增一个可配置的真实 LLM backend，使 agent 能通过结构化模型输出生成设计契约、候选动作、动作选择、澄清中断和 observation 摘要。
- 通过本地 sidecar 边界复用 Node `pi-ai` 的 provider 统一能力，而不把 TypeScript runtime 直接嵌入 Python 进程。
- 为 sidecar 不可用、provider 错误、超时和结构化输出校验失败场景提供一致的降级与错误语义。
- 保留启发式 adapter，供测试、离线开发和 sidecar 降级使用。

**Non-Goals:**
- 不重写 `AgentWorkflowOrchestrator`、LangGraph 图或 Web/CLI 的核心 workflow 逻辑。
- 不引入 `pi-agent-core`、`pi-coding-agent` 等完整 agent runtime 替代现有 Host agent。
- 不在本变更中实现流式 token 展示、对话式聊天 UI 或跨会话模型记忆。
- 不解决所有领域 prompt 工程问题，本次只覆盖现有 `AgentModelAdapter` 所需的结构化操作。

## Decisions

### 1. 保持 Python Host agent 编排层不变，只替换 adapter backend

Python 侧新增一个 `LLMAgentAdapter`，继续实现现有 `AgentModelAdapter` 协议，并由 `HostRuntime` / `AgentWorkflowOrchestrator` 按配置注入。这样可以复用现有状态机、审批策略、持久化和测试基座，避免把“接模型”与“重写编排”捆绑到一次变更里。

备选方案：
- 直接把 Host agent 改写到 TypeScript，并用 `pi-agent-core` 统一编排。
- 在 Python 中直接接各 provider SDK，不引入 Node sidecar。

不采用的原因：
- 改写编排会扩大范围，且与已实现的 Python runtime 重复。
- 直接接 provider SDK 会把多 provider 适配、结构化输出和后续模型切换成本重新拉回 Python 侧。

### 2. 采用本地 Node sidecar + `stdio` JSON 请求/响应协议

Node sidecar 作为本地子进程运行，由 Python runtime 按需启动并管理生命周期。该 sidecar 以独立可运行组件的形式放在 `apps/` 下，而不是新建 `tools/` 目录。Python 通过 `stdin/stdout` 发送单请求单响应的结构化 JSON，sidecar 使用 `pi-ai` 调用 provider，并返回 schema 校验后的结果。

`pi-ai` 的接入方式采用 npm 发布包 `@mariozechner/pi-ai`，并在 sidecar 自己的 `package.json` / lockfile 中锁定明确版本；本变更不把 `pi-ai` 或整个 `pi-mono` 仓库源码 vendor 到当前 monorepo。

选择 `stdio` 而不是本地 HTTP 的原因：
- 无需管理端口、监听地址和额外的服务发现。
- 生命周期自然绑定到当前 Host 进程，适合 CLI 与本地 Web Host 的单机使用方式。
- 仓库现有 MCP server 已经大量使用本地 stdio 边界，测试和调试模式一致。
- 当前仓库工作区结构只正式承载 `apps/*` 和 `packages/*` 两类成员，把 sidecar 放在 `apps/` 更符合现有 monorepo 组织。

备选方案：
- 本地 HTTP sidecar。
- 远程共享模型网关服务。

不采用的原因：
- HTTP 会引入端口冲突、健康检查和清理问题。
- 远程网关超出当前单机场景，且会引入额外鉴权与部署复杂度。

对于 `pi-ai` 依赖本身，备选方案还包括：
- 直接把 `pi-mono` 仓库作为 git 子模块或源码副本引入。
- 通过 git commit 依赖而不是 npm 发布包接入。

不采用的原因：
- vendoring 源码会显著增加升级、审计和仓库噪音成本。
- git commit 依赖更适合上游尚未发布或必须临时打补丁的场景，不应作为默认方案。

### 2.5 配置文件承载非敏感运行参数，凭据仅通过环境变量注入

LLM backend 的配置分为两层：

- 非敏感运行配置放在 agent/backend 配置文件中，例如 backend 类型、provider 名称、model、timeout、allow_fallback 和 sidecar 启动命令。
- 敏感凭据仅通过环境变量注入 sidecar，例如 `OPENAI_API_KEY` 或其他 provider token。

Python runtime 负责读取项目或进程级 agent 配置；Node sidecar 负责从环境变量读取凭据。环境变量可以覆盖配置文件中的非敏感项，以支持本地调试和 CI。

备选方案：
- 所有配置都走环境变量。
- 把 provider 凭据写入项目级 TOML/YAML 配置文件。

不采用的原因：
- 全环境变量方案不利于审计、示例配置和测试复现。
- 把凭据放进项目配置文件会让密钥管理和共享工作区边界变得危险。

### 3. sidecar 操作面与 `AgentModelAdapter` 方法一一对应

为了减少 Python/Node 两端的语义漂移，sidecar 直接暴露与 `AgentModelAdapter` 对齐的结构化操作：

- `derive_design_contract`
- `build_working_plan`
- `propose_candidate_actions`
- `select_action`
- `build_clarification_interrupt`
- `summarize_observation`

Python 负责收集 canonical state、调用 sidecar、把响应反序列化为本地 dataclass，并在写入 canonical state 前做二次类型校验。Node 负责 prompt 模板、`pi-ai` provider 调用和输出 schema 约束。

备选方案：
- 只让 sidecar 暴露一个通用 `generate_object` 接口，由 Python 自己维护 prompt 与 schema。
- 只把部分操作交给 sidecar，其余继续本地启发式生成。

不采用的原因：
- 通用接口会把 prompt/schema 编排复杂度重新推回 Python，并削弱 sidecar 的统一性。
- 部分操作仍本地生成会造成同一轮决策的来源不一致，难以解释 backend provenance。

### 4. LLM 输出必须经过双层校验，并支持显式降级

Node sidecar 首先对 provider 输出进行 schema 校验；Python adapter 收到结果后，再将其映射到本地 dataclass / typed object。只有通过两层校验的结果，才能进入 canonical agent state。

对于 sidecar 失败语义，采用两种明确路径：
- `allow_fallback=true` 时，记录 backend 错误并降级到 `HeuristicAgentAdapter` 完成当前操作。
- `allow_fallback=false` 时，停止自动推进，写入结构化错误并把 workflow 置于待反馈或 blocked 状态。

该策略保证：
- 不会因为无效模型输出而直接触发未校验的工具执行。
- 测试和本地开发仍可在没有 Node / provider 配置时运行。

### 5. backend provenance 进入 working state 与决策记录

每次通过 sidecar 产生的设计契约、working plan、selected action 或 observation 摘要，都需要记录：
- adapter/backend 类型
- sidecar 名称与版本
- provider 名称
- model 名称
- 是否发生 fallback

这些元数据进入 agent state 的 `_meta` 字段和 decision trace 引用，供 Web Host、CLI 和测试读取。这样用户才能区分“模型真实决策”“启发式降级”和“配置缺失导致的 fallback”。

### 6. Web Host 首屏优先显示 backend 与降级状态，provider/model 放入详情视图

Web Host 的主界面应该优先回答“当前是不是 LLM backend 在决策”“是否发生了 fallback / degraded”“最近一次失败原因是什么”。因此首页状态卡只显示：

- backend 名称
- fallback / degraded 状态
- 最近一次 sidecar 或 provider 错误摘要

更细的 provenance 信息，例如 provider、model 和 sidecar 版本，收纳到详情面板或调试区域，而不是挤占首页的主要 workflow 操作区。

备选方案：
- 首页直接展示完整 provider/model 元数据。
- 首页只显示一个笼统的 backend 名称，不显示降级或错误信息。

不采用的原因：
- 完整模型元数据放到首页会增加当前 Web Host 已较拥挤页面的认知负担。
- 只显示 backend 名称会让用户无法区分“LLM 正常运行”和“已经退回 heuristic fallback”。

## Risks / Trade-offs

- [跨语言边界增加调试成本] → 使用最小 `stdio` JSON 协议、假 sidecar 进程和契约测试固定请求/响应格式。
- [Node 依赖进入 Python 仓库后增加开发环境复杂度] → sidecar 独立成单独 app，默认不阻塞 Python-only 测试；缺少 Node 依赖时可显式 fallback。
- [模型输出不稳定导致 workflow 状态抖动] → 通过 schema 约束、Python 二次校验、预算限制和 approval gate 保护执行边界。
- [多 provider 差异导致行为不一致] → 先收敛到统一 sidecar 契约和单一默认 provider 配置，后续再扩展 provider 兼容矩阵。
- [Web Host / CLI 只能看到“失败”但不知道原因] → 将 backend、provider、错误类别和 fallback 状态显式写入 state / trace，并在宿主界面展示。

## Migration Plan

1. 新增 Node sidecar app 与最小启动方式，先提供假 provider / 假 sidecar 测试入口。
2. 在 `packages/enzyme-host-runtime` 中新增 sidecar client、配置模型和 `LLMAgentAdapter`，保留现有 heuristic adapter 作为默认 fallback。
3. 让 `HostRuntime` / `AgentWorkflowOrchestrator` 支持从配置或环境变量选择 backend，并把 backend provenance 暴露到 snapshot。
4. 更新 CLI / Web Host，显示当前 backend、sidecar 错误与 fallback 状态。
5. 增加单元测试、sidecar 协议测试和失败恢复测试后，再把真实 provider 配置纳入开发文档。

回滚策略：
- 关闭 LLM backend 配置，恢复使用纯 `HeuristicAgentAdapter`。
- sidecar app 可以保留在仓库中，但不参与运行路径。

## Open Questions

- agent/backend 配置文件最终挂在项目根目录、`.enzyme/` 私有目录，还是复用现有全局环境变量入口，需要在实现时收敛为单一约定。
- CLI 是否在默认摘要输出中展示 provider/model，还是仅在 `--verbose` 或等价调试输出中展示。
