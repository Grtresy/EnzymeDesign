# openzyme-runtime-llm

LLM/provider bounded-turn Adapter，唯一实现 `openzyme.agent-runtime-adapter@1`。

本包拥有显式模型/provider 配置、provider backend、prompt/context 的有界压缩、
step/token/time budget、tool-call 翻译和结构化失败。`LangChainProviderBackend` 仅在
Standard composition 已选择本 Adapter、配置与 credential slot 已精确解析之后延迟
导入 LangChain；环境变量、可 import 的 provider 包或 Provider 异常都不能静默切换
模型、provider 或 Adapter。

基础 wheel 不依赖 LangChain。官方 OpenAI-compatible 实现位于 `openai` extra；locator
导入不会导入 provider 实现、读取环境或发起网络请求。`preflight()` 只验证依赖和精确
身份，不做网络探测。LangChain invoker/model factory、同 Provider retry、prompt tokenizer、
token ledger、LLM debug recorder 与 live connectivity mechanism 的唯一实现均位于本包；旧
`openzyme-runtime` compatibility package、alias 和 CLI bridge 已删除。package 状态为
`target_implemented_not_cutover`：Distribution 可显式选择它，但真实 deployment activation/cutover 仍需独立证明。

一次 `run_turn()` 只消费 Kernel 提供的 immutable `RuntimeTurnCommand` 和 scoped
`RuntimeCapabilityGateway`。模型只看到当前 affordance snapshot 的工具；每次工具调用
带回同一 snapshot digest。达到 step/time/usage 上限只产生 runtime outcome，不推断
`Task` 完成。Provider failure 公开 `mutation_applied=false`、`fallback_performed=false`，
是否重试仅由当前 provider 的显式 retry policy 决定。

`StandardLlmAdapterFactory` 是官方 composition owner：它构造 exact
`LlmRuntimeAdapter + LangChainProviderBackend`，并在旧 harness 退出前提供同一 owner 下的
legacy chat-model factory。generic Host 在 LLM 启用时没有显式 factory 会在任何网络调用前
fail closed。live connectivity 是单独的显式操作，不属于 `preflight()`，不得被启动探测隐式调用。
