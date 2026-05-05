## ADDED Requirements

### Requirement: LLM sidecar 通过本地结构化协议暴露 Host agent 模型操作
系统 MUST 提供一个本地 Node sidecar 进程，供 Python Host runtime 通过受控的进程边界调用真实 LLM 能力，而不是在 Python 进程内直接耦合 provider SDK。

sidecar 至少必须暴露与 `AgentModelAdapter` 对齐的结构化操作：

- `derive_design_contract`
- `build_working_plan`
- `propose_candidate_actions`
- `select_action`
- `build_clarification_interrupt`
- `summarize_observation`

每次请求至少必须包含：

- 操作名
- 请求 id
- 规范化的 episode / agent state 上下文
- 调用配置或 backend 标识

每次成功响应至少必须包含：

- 请求 id
- 操作结果
- provider 名称
- model 名称
- sidecar 名称或版本

#### Scenario: Python runtime 通过 sidecar 请求候选动作
- **WHEN** `LLMAgentAdapter` 需要为某个 episode 生成 candidate actions
- **THEN** Python runtime 通过本地 sidecar 协议发送包含规范 agent state 的 `propose_candidate_actions` 请求
- **THEN** sidecar 返回经过结构化校验的候选动作列表以及 provider/model 元数据

### Requirement: LLM sidecar 对模型输出执行 schema 校验并拒绝未结构化结果
sidecar MUST 在把 provider 响应返回给 Python runtime 之前完成操作级 schema 校验，拒绝缺字段、类型错误或无法映射到目标结构的输出。

对于每个操作，sidecar MUST：

- 使用固定的结构化输出 schema
- 返回成功或失败的二元结果，而不是混合自由文本
- 在失败响应中返回稳定的错误类别、错误消息和可选重试标记

sidecar MUST NOT 将未通过 schema 校验的动作、设计契约或摘要直接返回给 Host runtime 作为成功结果。

#### Scenario: provider 返回无效动作对象时 sidecar 返回结构化失败
- **WHEN** provider 返回的 `select_action` 结果缺少必填字段或字段类型不匹配
- **THEN** sidecar 将该结果标记为 schema-validation 失败
- **THEN** Python runtime 收到的是结构化错误响应，而不是部分可用的成功对象

### Requirement: LLM sidecar 规范化 provider 失败与运行时元数据
sidecar MUST 对 provider 不可用、认证失败、超时、速率限制和内部异常进行规范化映射，使 Python runtime 可以基于稳定错误类别决定 fallback 或阻断策略。

sidecar 失败响应至少必须包含：

- 错误类别
- 错误摘要
- 是否可重试
- backend/provider 标识
- 请求 id

成功响应和失败响应都 MUST 带上 backend provenance 元数据，以便宿主界面和测试判断当前决策来自哪个 provider/model 以及是否发生 sidecar 降级。

#### Scenario: provider 超时时 sidecar 返回可重试错误
- **WHEN** sidecar 在 provider 调用期间达到配置超时
- **THEN** sidecar 返回 `timeout` 或等价的稳定错误类别
- **THEN** 响应同时包含 provider/model 标识和 `retryable=true` 的结构化元数据

### Requirement: LLM sidecar 将非敏感 backend 配置与凭据注入分离
系统 MUST 将 LLM backend 的非敏感运行配置与敏感 provider 凭据分开管理，而不是把所有配置混合到单一输入面上。

sidecar 集成至少必须满足：

- backend、provider、model、timeout、allow_fallback 和 sidecar 启动参数可通过配置文件或等价非敏感配置源声明
- provider 凭据 MUST 通过环境变量注入，而不是写入项目级配置文件
- 环境变量可以覆盖非敏感配置中的等价字段，以支持调试和部署环境切换

#### Scenario: 使用配置文件选择模型并通过环境变量注入密钥
- **WHEN** 项目或进程配置将 backend 设为 `llm-sidecar` 并声明 provider/model/timeout
- **THEN** Python runtime 和 sidecar 可以在不读取项目内明文密钥的前提下完成模型调用
- **THEN** provider 凭据从环境变量解析，而非从项目级配置文件读取
