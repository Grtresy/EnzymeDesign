## Why

EnzymeDesign 需要以比赛平台可探测、可试聊的 OpenAI-compatible HTTP 形态发布，但 OpenZyme 的真实产品语义是 Session、Task、Lane、Approval 与显式 bounded runtime command，不能把 `/v1/chat/completions` 直接伪装成 Kernel contract 或删减成普通模型调用。现在需要增加一个独立、薄且可移除的 delivery surface，在不改变 Kernel/Plugin/Driver 所有权和不绕过 Host `/v3` 控制面的前提下完成比赛接入。

## What Changes

- 新增独立 `openzyme-openai-compatible-api` delivery surface，对外提供 Bearer 鉴权的 `GET /v1/models` 与 `POST /v1/chat/completions`，覆盖比赛指南的 L0 文本对话、非流式 JSON、流式 SSE、`usage`、合法 `finish_reason` 以及可选 `sessionId`。
- 将每个兼容协议 turn 映射为一个确定的 OpenZyme Session 上的用户消息和恰好一个显式 bounded `runtime.drain` command；固定 `auto_enqueue_ready_tasks=false`，不循环 drain、不从 runtime completion 推断 Task terminal，也不经聊天文本批准受控操作。
- 新增独立 `enzymedesign-openai-compatible` Distribution，显式选择 EnzymeDesign 的 exact Kernel、Adapters、Plugins、Drivers、原生运维 surfaces 与新的兼容 surface；它不是 Standard 的语义层，也不会因安装包存在而 ambient activation。
- 第一版明确不支持 function/tool calling、reasoning 输出、多模态输入、文件输入/附件输出或由请求 `model` 选择内部 Provider；这些字段不得被静默解释为别的能力。
- 增加协议契约、错误/超时/断连语义、单租户固定项目配置、Session identity/lifecycle、secret separation、distribution/wheel closure、non-live probe 与文档一致性验证。
- 本 change 的设计与实施以 `separate-openzyme-kernel-from-capability-extensions` 已完成并完成 `file_workspace_public@2`/Host-client cutover 为前置条件；不在本 change 内回填或兼容未完成的目标架构。

## Capabilities

### New Capabilities

- `openai-compatible-delivery-surface`: 定义外部 `/v1` L0 wire contract、鉴权、Session/turn 映射、单次显式 runtime command、响应投影、流式与失败语义。
- `enzymedesign-openai-compatible-distribution`: 定义包含该 surface 的 exact EnzymeDesign 派生 Distribution、配置/凭证边界、启动门禁、wheel closure、资格验证与运维方式。

### Modified Capabilities

无。该 surface 与 Distribution 只新增组合和外部协议能力，不修改既有 Kernel、Standard、EnzymeDesign、Plugin、Driver 或 `file_workspace_public@2` 的 requirement；若实施发现必须改变这些契约，应先修订本 proposal/spec，而不是把变更隐藏在实现中。

## Impact

- 新增应用：`apps/openzyme-openai-compatible-api`。
- 新增 Distribution wheel 与组合 manifest：`packages/enzymedesign-openai-compatible-distribution`、`distributions/enzymedesign-openai-compatible`。
- 复用且只通过公开边界调用：`openzyme-client`、`openzyme-host-api` 的 `/v3` Session/message/runtime-command/workspace projection contracts，以及既有 EnzymeDesign component manifests。
- 更新 workspace/build 配置、architecture qualification/test-gate inventory、主架构与相关 `docs/v3/`、Distribution/operator 文档，并将比赛方指南保留为外部 wire-contract 验收来源。
- 不授权 live Provider/HPC、真实公网部署、凭证写入仓库、比赛平台提交或产品代码实现；这些属于后续 apply/deploy 阶段。
