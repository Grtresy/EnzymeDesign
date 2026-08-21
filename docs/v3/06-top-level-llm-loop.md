# V3 Top-level LLM Loop

## 一次 turn

```text
claim signal -> acquire session lease -> build truthful projection
-> invoke model -> validate/dispatch tool calls -> persist outcomes
-> enqueue explicit follow-up facts -> release/heartbeat lease
```

loop 是 bounded coordinator，不是 workflow truth owner。它读取 typed repositories，通过 canonical
tool router mutation，并将每个 outcome 显式记录。

新 Kernel 的 coordinator 从 exact claimed signal、SessionRuntimeLease、Distribution/Adapter/Extension/catalog
identities、SessionCapabilityBindingRevision 与本 turn ToolAffordanceSnapshot 构造 immutable
`RuntimeTurnCommand`。Runtime Adapter 只返回 closed proposal；Kernel 在原子 once-only consume 时重验全部
identity/budget，并分别写 continuation 与 settlement outbox。重复 outcome 不重跑 Adapter，runtime settlement
也没有 `Task` 终态写权限。目标 LLM Adapter 已实现 exact provider/backend、bounded context/step/time/usage、
同 provider 有限 retry 和 no-switch failure；LangChain factory/invoker、token/model limits、debug 与
connectivity mechanism 也由该包唯一拥有并由 Standard factory 构造。旧 production loop 在显式 composition
cutover 前仍保留，不能把目标实现存在当成已激活。

## Projection

model context 包含：objective、task/lane、assignment、inbox、approval、workspace status、private/published
revision facts、reports、scientific state、external job/result、failures 和 docs references。credential、
private locator、raw backend handle 和未授权 owner view 不进入 prompt。

world observation 必须区分 observed、unknown、stale、not-authorized 和 absent。projection missing 不等于
业务不存在。

## Tool loop

provider-visible schema 来自 exact `ToolSpec` catalog。response tool name 先恢复 canonical name，再进入
router。每次调用绑定 session、agent、task/lane、lease/fence、call id 和 catalog digest。

tool 参数错误以安全结构返回给 model；不得自动修正或重新调用。pending approval/continuation 会暂停
当前 exact operation，后续 delivery 使用 durable continuation fence，不由 model 自行 polling。

## Strategy neutrality

loop 不规定 agent 必须采用的工具顺序、Git 合并方式、research source、HPC placement 或失败处置。它可以
提出 available capabilities 和真实 gate，但不得把单一路线写成隐藏强制序列，除非该顺序来自 authority/
effect/safety machine contract。

## Progress

只有 typed outcome 明确报告 `semantic_progress=true` 才计入 durable supervisor progress。poll、heartbeat、
lease extension、state version、timestamp 或重复 diagnostic 不计。全部 worker slot 都发生 semantic progress
时最多发一个 backlog notification，下一 tick 仍独立 claim。

## Completion

model 可以选择调用 `task.finish`，但必须通过 task owner 的显式证据校验。loop 不从自然语言“完成”、
report presence、scientific closure、job success 或 max-step exit 推断 terminal。

## Failures

provider unavailable、invalid tool response、context overflow、lease loss 和 repository conflict 都有 typed
failure。unknown external effect 交给 execution owner reconcile；loop 不重发。stale context 终止当前 turn，
不把旧 catalog/tool/filesystem shape 翻译到新 contract。

LLM provider failure 不是 Task failure 或外部业务 mutation proof。公开 observation 只包含 selected provider、
backend/config digest、稳定 error code、retry eligibility、`mutation_applied=false` 和
`fallback_performed=false`；原始 provider prose/credential/URL 只进入 private diagnostic。Adapter 不尝试另一
provider/model/base URL。
