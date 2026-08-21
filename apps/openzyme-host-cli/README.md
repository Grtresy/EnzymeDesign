# openzyme-host-cli

OpenZyme exact `file_workspace_public@2` 的薄命令行客户端。它只依赖公开 client/contracts 与 HTTP，不拥有
runtime，不 import Provider、scheduler、Host internals 或旧 mixed runtime。

## Contract

`HostApiV2Client` 要求 operator 提供完整 `LayeredReleaseIdentity`，并使用共享 `openzyme-client` 校验：

- exact media type 与 closed `@2` root/core/extensions；
- release/public-contract/projection identity；
- Session capability-binding 与 per-turn affordance snapshot；
- 每个 Plugin section 的 contract/projection digest；
- mutation response 与发送前 inspection 的 identity 连续性。

Session bootstrap 发生在 projection 尚不存在时，只发送 release/public-contract identity；CLI 不伪造
projection、binding 或 affordance header。Session-scoped mutation 先 inspection，再携带六个 exact identity
与调用者提供的 `Idempotency-Key`。发送后的 identity 丢失或漂移报告 `dispatch_in_doubt`，不重试、不切换
`@1`。

## 使用

```bash
uv --project apps/openzyme-host-cli run openzyme \
  --release-identity /absolute/operator/release-identity.json \
  sessions create --project-id proj_001 --session-id sess_123 \
  --objective "Design a thermostable enzyme candidate" \
  --idempotency-key bootstrap-sess-123

uv --project apps/openzyme-host-cli run openzyme \
  --release-identity /absolute/operator/release-identity.json \
  --session-id sess_123 sessions show

uv --project apps/openzyme-host-cli run openzyme \
  --release-identity /absolute/operator/release-identity.json \
  --session-id sess_123 sessions message \
  --message "Create a bounded research task" \
  --idempotency-key message-001
```

当前 exact 模式只执行 CLI 已显式映射且 Host Distribution 已激活的命令。缺少 release 文件、命令不在当前
route closure、旧 receipt/seal 参数或任何 contract drift 都在 HTTP 前拒绝，不会进入 legacy client。

配置优先级为命令行参数后环境变量：

- `OPENZYME_HOST_BASE_URL`
- `OPENZYME_HOST_AUTH_TOKEN`
- `OPENZYME_PROJECT_ID`
- `OPENZYME_OUTPUT_FORMAT`
- `OPENZYME_RELEASE_IDENTITY_FILE`

环境读取只构造 closed CLI 配置；本机存在某个 Plugin/Provider 包不会改变工具或 route 可用性。

```bash
uv --project apps/openzyme-host-cli run pytest
```
