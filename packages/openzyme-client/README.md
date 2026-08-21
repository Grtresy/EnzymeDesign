# openzyme-client

公开 `file_workspace_public@2` HTTP/媒体契约客户端边界。

`inspect_workspace()` 校验 exact media type、closed root/core/extensions、layered release、section projection
digest，以及 Host 返回的 workspace-contract、release、public-contract、projection、capability-binding、
affordance-snapshot 六项响应 identity。正文中的 SessionCapabilityBinding 和 ToolAffordanceSnapshot 必须与响应头
一致；缺失或漂移均 fail closed。

`send_mutation()` 在 transport 可达前重验 release/public-contract/binding/affordance，并把当前
projection/binding/snapshot digest 绑定到请求。响应还要与发送前 identity 连续；已发送后的响应 identity
不可确认时返回 `dispatch_in_doubt`，不会自动重发、切换 route 或翻译 `@1`。

`bootstrap_session()` 是独立 pre-Session contract，只发送 exact release/public-contract 和调用者提供的
idempotency key。Session 尚不存在时禁止伪造 projection、binding 或 affordance header。

本包只定义 `ClientHttpTransportPort`，不依赖 runtime、Host internals 或具体 HTTP 库。它已被目标 CLI 使用；
真实部署是否可写仍由 exact Distribution activation 和 Session pin 决定，不由安装状态决定。
