# OpenZyme V3 公共接口

## 1. 总体原则

V3 允许引入破坏性新接口，并以替代 V2 为目标。

目标：

- 给前端、CLI、外部调用方一个新的 harness-first 语义面
- 不要求调用方理解 LangGraph、phase graph、internal engine state

说明：

- `/v3` namespace 仍然保留，便于在迁移窗口内识别新接口
- 但 V3 默认不承担长期兼容 V2 语义的义务
- 任何兼容层都只应视为短期迁移措施，而不是长期产品承诺

## 2. API 设计默认值

建议最小接口按两层理解。

面向普通用户与 Web UI 的主入口：

- `POST /v3/sessions`
- `GET /v3/sessions/{session_id}`
- `POST /v3/sessions/{session_id}/messages`
- `GET /v3/sessions/{session_id}/workspace`
- `GET /v3/sessions/{session_id}/events`
- `POST /v3/approvals/{approval_id}/resolve`

面向 harness tools、CLI/ops、测试与迁移调试的 control-plane secondary endpoints：

- `POST /v3/tasks`
- `PATCH /v3/tasks/{task_id}`
- `POST /v3/lanes`
- `POST /v3/lanes/{lane_id}/claim`
- `POST /v3/lanes/{lane_id}/keep`
- `POST /v3/lanes/{lane_id}/remove`

说明：

- `POST /v3/sessions/{session_id}/messages` 是默认的 harness command ingress，可触发普通消息处理、task updates、delegation、engine 调用
- 当 `model_factory` 可用时，该入口默认走真实 top-level LLM harness driver
- Web UI 默认不要求用户手动创建或编排 task / lane；这些对象主要由 master agent 在 loop 中创建和编排，再通过 workspace projection 展示
- task / lane endpoints 可以存在，但不得反向主导产品交互，把 V3 退化成手工 workflow 管理后台
- V3 初期不要求单独暴露 `agents` REST 资源，但 workspace projection 必须能显示 teammate / delegation / protocol 状态
- 默认主路径是 `conversation -> master planning -> task -> delegation -> teammate loop -> lane/capability -> user feedback`，而不是用户消息直接裸触发 capability

## 3. Workspace Contract

`GET /v3/sessions/{id}/workspace` 返回统一 snapshot。

最低字段分区：

- `session`
- `conversation`
- `task_board`
- `lane_board`
- `pending_approvals`
- `inbox`
- `memory`
- `delegation`
- `activity_feed`
- `artifacts`
- `reports`
- `capabilities`

说明：

- `conversation` 来源于持久化的 user / assistant message content，是用户与 master agent 的 canonical read model
- UI 刷新后必须可以仅靠 workspace projection 恢复 conversation timeline，而不是依赖浏览器本地消息历史
- `capabilities` 是可扩展分区，按 `capability_key` 挂载各 engine 的投影
- 不应把当前 engine 名称直接固化为 workspace 顶层 contract，避免后续每新增一种能力都破坏接口
- `task_board`、`delegation`、`lane_board` 共同表达内部执行状态；它们不是 conversation 的附属调试信息，而是与 conversation 并列的 control-plane 读模型
- `artifacts` 默认是 session 共享工作面的只读投影，供 UI 呈现，也供后续 agent loops 作为可读取 catalog 理解当前工作面

## 4. CLI 语义

V3 CLI 不再围绕 `episode phase` 渲染。

默认能力：

- 查看 session workspace
- 查看 task board，并在高级/ops 场景下更新 task board
- 处理 approvals
- 观察 lane 状态
- 发起消息 / 继续 agent loop

CLI 可以保留 task / lane mutation 命令，作为自动化、调试、迁移和 operator 用途；这不代表 Web UI 的默认用户需要手动维护这些对象。

## 5. Web UI 语义

V3 Web UI 默认是 conversation-first。

主交互：

- 用户发送自然语言消息
- top-level master agent loop 决定如何创建和编排 task
- 具体 research / execution / reporting task 默认委托给 teammate agent 推进
- teammate 围绕 task 读取共享 workspace / artifacts、按需绑定 lane、调用 engine、请求 approval，并可通过 protocol 与 peers 沟通
- approval 以对话流中的卡片形式出现，用户只需要 approve / reject
- task、lane、engine、artifact、report 变化通过 workspace projection 和 control-plane events 回填

默认展示：

- 对话 timeline
- approval cards
- tool / engine / report / artifact activity cards
- task board、lane/workspace 状态、delegation、artifacts / runs / reports 的只读 inspector

不要求用户理解：

- 哪个 graph 节点正在运行
- 哪个 subgraph 持有当前局部状态
- 如何手动创建 task / lane 才能推进工作

同时也不应要求用户理解：

- 具体哪个 teammate 在什么时刻被 spawn
- 为什么某个 capability 缺少 `task_id`
- 内部 team protocol / lane / engine / artifact catalog 是如何串起来的

## 6. Streaming

V3 streaming 默认围绕 control-plane events，而不是围绕 graph implementation 细节。

推送单位：

- `conversation.user_message`
- `conversation.assistant_message`
- `tool.invoked`
- `tool.completed`
- `task.updated`
- `approval.requested` / `approval.resolved`
- `lane.created` / `lane.bound` / `lane.removed`
- `agent.spawned` / `agent.delegated` / `agent.message.delivered`
- `engine.invocation.started` / `engine.invocation.updated` / `engine.invocation.completed`
- `report.generated`

这些事件默认服务于“用户与 master agent 的单一对话体验”，而不是把 V3 暴露成多线程运维控制台。

## 7. 弃用策略

- V2 进入 `deprecated / frozen` 状态，不再继续功能性演进
- V3 完成后应直接制定 V2 retirement plan，而不是默认长期双栈并行
- 若迁移窗口内仍需保留少量兼容入口，它们只能作为临时 shim，不能反向主导 V3 设计
- `current_phase`、phase rail、supervisor-route 等 V2 词汇不再是 V3 公共接口基线
