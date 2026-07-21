# Slice 4 checkpoint：generic mutation quiescence 与 monotonic sealing

## 当前结论

Slice 4 的 generic mutation authority、writer coverage、receipt verifier 与 AOX consumer
已落地；完整 non-live gate、legacy caller audit 与文档链接检查均已通过。
Quiescence 是 Host evidence closure，不是 workflow reducer，也不授予 `rxx` GO。

## Landed contract

1. `MutationScope` 冻结 kind、policy、coverage manifest、generation 与 fence；同一
   session 同时最多一个 active scope。unsupported policy/coverage 在写入前拒绝。
2. writer 只能从 active parent 派生，或由 composition root/attempt driver以 trusted
   root 注册。detached、unknown category、stale generation/fence 全部 fail closed。
3. covered writer 包括 runtime command、agent turn、sandbox process、controlled
   operation、continuation delivery、runner/provider callback、artifact/report publisher、
   event/outbox publisher 与 live-token ledger writer。
4. SQLite triggers 在 commit 时调用 connection-bound authority verifier；producer
   boundaries 同时保护 artifact、report、tool-result 与 callback publication。read-only
   tools 不虚构 writer。
5. freeze transaction 先关闭 admission 并推进 fence。writer/descendant 必须显式退休；
   exact local process epoch 只证明 local writer 退出，不改变 remote effect certainty。
6. quiescence 要求两次一致的 bounded SQLite/event/external snapshot，并签发唯一 immutable
   receipt。offline verifier 可重算 writer proof、high-watermark、snapshot 与 receipt digest。
7. seal 只消费 exact verified receipt并拒绝 post-seal canonical mutation；后续合法工作
   创建显式链接的新 generation。closure failure不改 task，也不选择替代科学计划。
8. AOX driver 以 trusted ATTEMPT root/ATTEMPT_DRIVER writer 进入通用 API；external
   snapshot 包含 catalog artifact bytes/tree 与 bounded MICU ledger rows/high-watermark。
   eligible seal 强制 `generic_v1`，不再把 runtime idle 当静默证明。

## Deterministic evidence map

- lifecycle/race/writer ancestry/retirement/stable snapshots/tamper/post-seal/task independence：
  `packages/openzyme-core/tests/test_mutation_quiescence.py`；
- repository guards、controlled callback 与 continuation writer：
  `packages/openzyme-core/tests/test_reliability_repositories.py`；
- event/outbox、tool publisher、LLM ledger writer：
  `packages/openzyme-core/tests/test_harness.py`；
- exact sandbox-process epoch 与 control-socket child publisher：
  `packages/openzyme-core/tests/test_sandbox_runtime.py`；
- AOX generic consumer、real private snapshot、ledger inclusion 与 artifact drift：
  `apps/openzyme-host-api/tests/test_aox_cutover_live.py`。

## Rollback rule

可以停止新 scope admission，但不能删除、重开或改写 frozen/sealed generation、receipt、
snapshot、writer proof 或 fence。已有 scope 必须 seal 或显式 failed closure；不能用旧
AOX mutation-idle heuristic发布 eligible evidence。process-isolated hard-kill与 multi-Host
consensus 仍明确延后。
