## Context

`ControlledOperationExecution` 已拥有真实 execution occurrence、effect certainty、retry eligibility 和 immutable result；Host quiescence 已拥有 writer retirement 与 sealing authority。缺少的是二者之间的科学选择层：当前 collector 只能从 occurrence history 推断唯一成功链，因此一个已知失败或重复 operation 会让整个 attempt 永久失效。

本设计提升已有 deferred proposal `canonical-scientific-chain-adoption-and-attempt-closure`，但不允许事后为 r48–r51 或其他历史 attempt 补造 adoption。目标是“完整审计所有发生事实，显式采用一条合法链”，不是“忽略失败”。

## Goals / Non-Goals

**Goals:**

- 保存完整 operation universe，并让 agent 显式处置每个 occurrence。
- 允许同一 formal attempt 内跨 sandbox run 采用已知、完整、授权的 effect 和 materialize sealed bytes。
- 独立 seal selection 与 attempt closure；known closed failure 不自动否决最终结果。
- 允许 agent 在 durable authorization envelope 内创建新 attempt，同时原子执行预算/target/expiry 限制。

**Non-Goals:**

- 不自动选择“最新”“成功”“相同 digest”或下游已消费的 operation。
- 不跨 formal attempt、campaign、positive/probe/fault scope 复用 effect/artifact。
- 不将 closure、quiescence 或 selection 推导为 task completed。
- 不把 workflow DAG/科学策略硬编码进 Harness；workflow contract 只声明可验证 role/约束。

## Decisions

### 1. 通用 control-plane 对象而非 AOX 私有表

新增 append-only canonical objects：

- `ScientificAttemptAuthority`：formal attempt 身份、scope/root、envelope、consumption 与 lifecycle；
- `ScientificChainSelection`：immutable revision，`draft|sealed|invalidated`；
- `ScientificOperationDisposition`：selection revision 下每个 occurrence 的 `adopted|superseded|failed|abandoned`；
- `ScientificEffectAdoption`：被采用 execution/result/effect certainty 与来源 scope；
- `ScientificArtifactMaterialization`：source artifact/blob、target workspace/path、digest 和 Host receipt；
- `ScientificAttemptClosure`：selection、operation universe、quiescence、authority consumption 的 immutable closure。

对象属于 domain/core control plane。AOX 只提供 workflow contract 和 verifier，不拥有通用 authority。

### 2. Operation universe 由 Host 枚举并 digest

selection 创建/封存时，Host 按 exact attempt/session/task/lane/scope 枚举所有 canonical controlled operations、相关 sandbox runs 和 materialization。agent 不能自报 universe，也不能漏项。每个 occurrence 必须恰有一个当前 disposition；selection seal 后不可原位修改，只能建立新 revision 并引用 parent。

`adopted` 必须进入唯一 selected chain；`superseded` 必须引用 replacement/adopted role；`failed` 必须绑定 terminal known failure；`abandoned` 只允许 no-effect 或已 reconciliation/闭合且不再活动的 occurrence。

### 3. Effect adoption 受 certainty 和 scope 限制

可 adoption 的 operation 必须 terminal，结果 immutable，`effect_certainty` 为 `effect_known` 或 `terminal_known`，且 workflow role、approval、provider/backend、input/output contract 均匹配。`dispatch_in_doubt`、活动 execution、未决 reconciliation、权限或 integrity violation 一律阻止 selection/closure。

同 attempt 跨 run 不要求伪造新的 `ControlledOperation`。adoption record 指向原 occurrence；后续 run 通过 materialization receipt 消费 bytes。相同 digest 不能合并 identities。

### 4. Materialization 是 Host-owned copy，不是路径约定

agent 提交 source artifact ref、target workspace 和用途；Host 重验 catalog grant、sealed blob digest、attempt/scope、target authority与无覆盖策略，然后写入目标并记录 receipt。sandbox 自行 copy、checkpoint、shared path 或 prompt 文本没有 materialization authority。

### 5. Closure 同时要求 selection completeness 和 quiescence

closure command 先 freeze attempt mutation scope，消费 exact quiescence receipt，再重算 operation universe、dispositions、selected chain、materializations、authorization consumption 和未决 effect。全部一致才创建 immutable closure。quiescence 证明“不会再变”，selection 证明“采用什么”，两者不可替代。

closure 不写 task terminal；agent 仍须显式 `task.finish`。

### 6. Fresh-attempt authorization envelope 是 durable capability grant

envelope 至少绑定 grantor、session/task/campaign、allowed scope/workflow、最大 attempt 数、MICU/cost/time ceilings、allowed effect classes、provider/HPC target allowlist、expiry、policy digest 和 idempotency key。创建 attempt 在单事务内检查并消耗 slot，生成 Host attempt id/root/scope。

unknown effect 会在 campaign/task authority 上建立 unresolved blocker；只要 blocker 存在，新 attempt 即使额度未用完也不能创建。越界返回结构化 `authorization_required` 给 agent，由 agent 请求用户/操作者，不静默缩小计划。

### 7. Command surface 保留 agent 自由

提供窄 command：`attempt.create`、`scientific.selection.begin`、`scientific.operation.disposition`、`scientific.effect.adopt`、`scientific.artifact.materialize`、`scientific.selection.seal`、`scientific.attempt.close`。Host 只校验事实/权限/一致性，不推荐选择。所有命令 idempotent、actor-bound、CAS/fenced。

## Risks / Trade-offs

- [状态对象较多] → 每个对象只拥有一个 authority，使用 service 编排和 consistency audit，避免万能 attempt row。
- [agent 错误处置成功历史] → seal 前完整 universe/role/policy 校验；UI 展示所有 occurrence 和差异。
- [跨 run bytes 引入污染] → Host-only materialization、digest/permission/target revalidation、禁止覆盖和跨 scope。
- [额度并发超发] → 单事务 consumption、idempotency key、版本/CAS。
- [旧证据被追溯升级] → 无 migration backfill；只有新 authority 创建后的 attempt 可写 selection/closure。

## Migration Plan

1. 新增 migration、domain/repositories 和 consistency checks；历史 attempt 不回填。
2. 增加 service/commands/projection，再接 artifact materialization。
3. 用 synthetic workflows 验证 duplicate, failed, unknown-effect, concurrent consumption 和 tamper cases。
4. AOX 单独迁移到新 bundle schema；旧 verifier 保留。

## Open Questions

无。已采用用户决策 1A（durable envelope）和 2A（先迁移 selected-chain，再启动新 live attempt）。
