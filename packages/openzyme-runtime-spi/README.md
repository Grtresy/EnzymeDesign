# openzyme-runtime-spi

本包定义框架无关的 `AgentRuntimeAdapter`、`RuntimeTurnCommand`、`RuntimeTurnOutcome`、
`RuntimeCapabilityGateway` 与 `ProcessIsolationPort`。它只依赖 `openzyme-contracts`，不包含 LangChain、
模型 Provider、prompt、Research、Podman 或 subprocess 实现。

`RuntimeTurnCommand` 绑定 exact Session/Agent/member/turn/signal claim、runtime lease generation/fence、process
epoch、Distribution manifest、Adapter/Extension bundles、declared catalog、capability-binding ID/revision/digest、
affordance snapshot ID/digest、完整 layered release digest、selected runtime Adapter identity 与 bounded turn
budgets。Kernel 生成 continuation 时必须原样固定这些 identity；旧 release/bundle/catalog 不能在恢复时转换，
stale binding/affordance 也不能复用原 tool dispatch。
`RuntimeTurnOutcome` 只是模型消息、工具请求、用量、continuation/approval wait 或结构化 failure 的提案；
它回显 command/session/member/signal/fence/epoch identity，由 Kernel closed validation 和 once-only consume；
不能直接写 repository、完成 Task、延长 lease 或返回 Provider/process 私有对象。

`ProcessIsolationPort` 接收 opaque workspace binding、authority generation/fence、process epoch、bounded
stdin/output budget 与 explicit foreground argv，并只返回 opaque process identity、bounded/truncation facts 和
effect certainty receipt。`reconcile(original_request)` 只查同一 process identity 的既有 terminal receipt；
它不得启动 replacement process，Adapter epoch 中没有证明时必须继续返回 `dispatch_in_doubt`。具体
Podman/native/Kubernetes 机制属于 Adapter。

本 wheel 仍是迁移中的 SPI，不因已安装而成为可用 capability；Distribution 必须显式选择 exact Adapter。

```bash
uv run pytest packages/openzyme-runtime-spi/tests
```
