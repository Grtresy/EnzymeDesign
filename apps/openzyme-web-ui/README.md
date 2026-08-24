# openzyme-web-ui

OpenZyme 的 `file_workspace_public@2` 浏览器交付面。生产入口只接受一个由 Distribution
显式注入、版本固定的 Core/Extension 组合，不提供 `@1`、artifact-era 或按 Session 选择的在线兼容模式。

## 当前边界

- `src/client.js` 校验 exact media type、layered release、public contract、projection、Session capability
  binding、ToolAffordanceSnapshot 和每个 extension projection digest；mutation 先读取当前 projection，绑定
  全部 identity，发送后再次读取 canonical `@2` state。响应 identity 丢失或漂移按
  `dispatch_in_doubt` 处理，不消费旧 workspace body，也不重试或 fallback。Host 当前没有公开 event
  stream，client 因而只轮询现有 workspace inspection，并在完整校验后形成 browser-local projection
  change observation；它不把该 observation 声称为 Host event。
- `src/file_workspace_v2_state.js` 校验 closed `core`、各 Core 子 section、工具 affordance 和 namespaced
  extension section；Core 中的产品、artifact、claim/lease token 和私有 locator 字段会被拒绝。
- `src/core_shell.js` 只拥有 Kernel state。Extension payload 只进入其 renderer，不会合并回 Core。
- `src/extension_renderer_loader.js` 只接受 manifest/catalog 声明的 exact renderer。缺少 renderer、renderer
  catalog drift 或 section contract drift 会禁用所有 mutation controls。
- `src/controller.js` 管理 verified projection polling、消息 admission、显式 bounded runtime drain、exact
  runtime command status polling 和 approval decision。轮询失败或 release/Session/cursor/projection identity
  漂移会立即禁用 mutation；重连只接受重新验证的 projection，`close()` 会撤销 timer 和旧请求 generation。
- `src/view.js` 直接显示 readiness、ordered transcript、Task、Agent、delegation/inbox、Approval、
  AgentAuthorityLease、Workspace generation、checkpoint、publication、runtime command、controlled operation、
  failure 和 blocked affordance，并明确把本地 change observation 与 Host canonical event stream 区分开；
  Plugin-free Standard 不显示 Research/Report/Science/Compute/HPC 占位面板。

这表示目标 UI 代码和 build closure 已经只使用 `@2`。它不表示真实部署已切换：真正 activation 仍要求
后续获批的 offline cutover、exact release 文件和 Host Distribution mount。

## Distribution 配置

Host 页面在加载 `src/main.js` 前必须注入：

```html
<script>
window.OPENZYME_WEB_UI_V2 = {
  sessionId: "session-opaque-id",
  rendererCatalogDigest: "sha256:...",
  release: {
    schema_version: "openzyme_layered_release_identity@1",
    kernel_contract_digest: "sha256:...",
    core_schema_digest: "sha256:...",
    adapter_bundle_digest: "sha256:...",
    extension_bundle_digest: "sha256:...",
    declared_tool_catalog_digest: "sha256:...",
    route_catalog_digest: "sha256:...",
    projection_catalog_digest: "sha256:...",
    migration_catalog_digest: "sha256:...",
    workspace_backend_digest: "sha256:...",
    host_build_digest: "sha256:...",
    client_build_digest: "sha256:...",
    release_digest: "sha256:...",
    public_contract_digest: "sha256:..."
  }
};
window.OPENZYME_EXTENSION_RENDERERS = [];
</script>
```

`session_id` 也可由 `?session_id=...` 提供。缺少配置时页面显式进入 non-operational 状态；它不会探测
已安装包、调用旧接口或猜测 release。Extension renderer 必须由 Distribution 以 exact section/renderer
contract 注册；空数组是 Plugin-free Standard 的合法配置。

## 验证

```bash
cd apps/openzyme-web-ui
npm test
npm run build
```

测试覆盖 Plugin-free Core shell、inactive/degraded affordance、missing/stale renderer、closed Core 子结构、
私有 claim/lease token 拒绝、旧 projection observation 拒绝、轮询失败/重连/关闭、完整响应 identity、
post-dispatch unknown effect、stale pre-mutation projection 和 canonical mutation re-inspection。
