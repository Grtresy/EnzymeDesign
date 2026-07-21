# Sandbox Host authority handoff

Status: `implemented-archived`; implemented and verified by OpenSpec change
`simplify-sandbox-host-authority-handoff` on 2026-07-21.

## Problem

attached sandbox process 的寿命可以跨过创建它的 agent turn。原 turn 释放
`SessionRuntimeLease` 后，durable execution worker 完成外部 effect，continuation delivery
worker 恢复 exact process；该进程随后发起 `ws.fetch_outputs()` 等新 Host call。旧组合根让
`ExecutionEngine` 捕获 agent-turn repository factory，再通过 reflected callback、第二套 scope
factory 或可选 `repositories: Any | None` 覆盖路径修补。r44 证明这种 wiring 会让“进程已经被
合法恢复”与“后续 Host 写仍绑定失效 turn lease”同时成立。

这不是放宽 fence 的理由。session turn、sandbox process、durable execution、continuation
delivery 与 mutation writer 本来就是不同 owner；真正缺失的是一个显式 Host-call boundary。

## Accepted design

- `SandboxHostCallContext` 每次只承载一个 immutable owner authority、一个 thread-owned
  `CoreRepositories` 和显式 mutation-writer 派生能力。
- owner authority 闭集为 session turn、sandbox process epoch、durable execution fence 和
  continuation delivery fence；任一类型不能冒充另一类型。
- `_ControlSocketServer` 在 process epoch 启动时获取 sandbox-process context，并在 park/
  delivery 后保持该 context；delivery worker 不把自己的短 authority 注入进程。
- `SandboxHostGateway` 是 sandbox 到 engine 的唯一 typed boundary。engine 不再选择或回退到
  创建时捕获的 repository scope。
- durable route 以 exact execution context 调 adapter；continuation authority只写 delivery；
  artifact publication 使用从当前 owner writer 派生的 bounded child writer。
- runtime barrier 只是现有 canonical rows 的 closed、bounded、read-only projection；它不拿
  lease、不 drain、不 dispatch、不写 task，也不成为 campaign reducer。

## Implementation evidence

实现入口：

- `packages/openzyme-core/src/openzyme_core/sandbox_host.py`
- `apps/openzyme-host-api/src/openzyme_host_api/sandbox_host_gateway.py`
- `packages/openzyme-core/src/openzyme_core/runtime_barrier.py`
- `apps/openzyme-host-api/src/openzyme_host_api/aox_runtime_observation.py`

file-backed lifecycle test 覆盖：agent lease acquire → sandbox park → lease release → durable
execution → continuation delivery → 同一 process 后续 `hpc.fetch_outputs`。测试同时证明不重发
external effect、只发布 declared outputs、immutable refs 不漂移且 task 保持业务
`in_progress`。fault matrix 分别拒绝 stale session/execution/delivery、process epoch mismatch 与
frozen mutation writer。

## Boundaries deliberately left separate

- OS-level process-group retirement、parent-owned fatal evidence 与 descendant hard-kill 属于
  [process-isolated live-attempt supervision](/openspec/changes/archive/2026-07-21-add-process-isolated-live-attempt-supervision/architecture-proposals/process-isolated-live-attempt-supervision.md)；
- 任意 Python stack/journal replay 不在本 proposal；
- 本 change 不启动新编号 campaign，也不把 deterministic test 写成 live GO；
- historical r41-r44 rows/evidence 保持不可变，旧 weak callback path 只停止新增依赖。

验证证据：聚焦回归 `365 passed, 1 deselected`；非 live 主线 `2167 passed,
31 deselected`；前端 `40/40`、构建、Ruff、兼容调用审计与 strict OpenSpec 均通过。本文件已随
OpenSpec change 移入其 archive 下的 `architecture-proposals/`，生命周期索引只保留归档链接。
