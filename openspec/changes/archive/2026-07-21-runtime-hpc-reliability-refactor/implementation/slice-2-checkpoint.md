# Slice 2 checkpoint：canonical durable controlled-operation execution

## 当前结论

Slice 2 的 execution ownership、route recovery、immutable result 与 public
projection 已落地。Slice 4 的 generic writer registry/fence 现已接入
controlled-operation worker、runner/provider callback、artifact/event publisher；
每个 external dispatch 前和晚归 callback commit 都同时比较 execution 与 mutation
authority。完整 non-live rerun、active-row rollback composition 与 caller audit 已通过，
`4.3`、`4.18` 均已闭环。

`rxx` campaign 继续冻结。本 checkpoint 没有运行 live LLM、live SSH、live HPC
或科学实验，也没有修改 `openspec/changes/aox-hmm-blank-world-cutover`。

## Canonical ownership chain

1. 新 operation 只有在 trusted `ReliabilityRefactorSettings@1` admission policy
   命中时才冻结为 `durable_async_v1`；既有 row 的 owner 永不随配置变化而改写。
2. `DurableControlledOperationAdmissionService` 在一个 transaction 中创建
   approval、operation、execution、immutable dispatch request、continuation 与
   admission event；任一晚期写失败时整组回滚。
3. `ControlledOperationExecutionWorker` 使用 execution-specific lease/fence，
   每次只执行一个 claim/dispatch/poll/reconcile/materialize/terminalize slice；
   external wait 期间不持有 SQLite transaction，也不借用 session lease。
4. compatibility `ControlledOperation.status/result/error` 只由
   `ControlledOperationExecutionTransitionService` 派生。durable owner 的 raw save
   在 repository boundary 被拒绝，execution event 只追加事实而不充当第二 reducer。

## Exact effect and recovery semantics

- Provider route 只使用冻结的 provider request identity，并从同一 identity 的
  persisted artifacts 恢复；不会换 backend、重建 operation 或 fallback。
- HPC route 先冻结 runner opaque run identity。direct SSH acknowledgement 丢失时
  保持 `dispatch_in_doubt` 且不重发；terminal-known run 只恢复 Host persistence、
  declared-output fetch 与 digest verification。
- process restart 后，`ready` 可继续；`dispatching` 只 query/reconcile exact handle；
  `result_ready` 可在 route adapter 缺失时直接复用 immutable handle 完成 terminalize；
  unknown effect 保持 reconcile-required。
- route adapter 在 pre-dispatch 前缺失时可以产生 `no_effect` closed failure；一旦
  frozen handle/dispatch generation 已存在，adapter 缺失只能保留原 effect facts，
  不能降格为 `no_effect`。
- SQLite `busy/locked` 使用独立 `database_busy` taxonomy。它不生成 backend failure、
  不重置 effect certainty，也不触发 duplicate dispatch；supervisor 延后重试且不把
  contention 计作业务推进。

## Result staging and atomic promotion

1. Provider/HPC callbacks 只能在携带 execution fence 的同一 repository connection
   上写入。即使 ExecutionEngine 通常拥有 scope factory，durable adapter 也会把它
   绑定到当前 fenced callback scope，避免新 connection 绕开 lease validation。
2. HPC success 自动 fetch declared outputs，并把 operation id/digest、Host run、runner
   run、invocation、workspace 与 exact catalog digest 写入 staging artifact metadata。
3. staging artifact 带 durable operation identity，但在
   `controlled_operation_result_artifacts` promotion 前不会进入 workspace、activity
   或 `world.inspect`。
4. result handle、canonical artifact-set digest、catalog digest validation、artifact
   bindings、execution transition、compatibility projection 与 event 在同一 transaction
   提交。partial set、identity drift 或 catalog digest drift 全部回滚；immutable DB
   triggers 禁止 result/binding update/delete。
5. terminal failure/rejection 也拥有 deterministic Host result handle，artifact set 为
   canonical empty set；execution terminal、result readiness、continuation delivery、
   agent wakeup 与 task business terminal 彼此独立。测试明确证明 execution success
   不会机械完成 task。

## Supervisor and rollback semantics

- `V3DurableWorkSupervisor` 属于 Host lifespan，使用独立 repository scopes 与 bounded
  concurrency；stop 先关闭新 claim。超时不能杀死 `asyncio.to_thread` 中的 callback，
  因而 supervisor 会公开 bounded `active_worker_count/shutdown_incomplete`，直到晚归
  worker 真正退休，而不会宣称 remote action cancelled。
- `legacy_only_v1` 只停止新 durable admission。Host 会扫描 nonterminal execution，
  为其保留 frozen route adapter 并继续启用 supervisor；显式关闭 durable worker 且
  active count 非零会 fail startup。这样 rollback 不会把在途 effect 交给 legacy owner。
- 最终 downgrade audit 仍是：

  ```sql
  SELECT COUNT(*)
  FROM controlled_operation_execution_records
  WHERE lifecycle_state <> 'terminal';
  ```

  返回非零时只能继续 drain/reconcile，不能删除、relabel 或同步执行这些 rows。

## Deterministic evidence

本 checkpoint 的 focused deterministic gate：

```text
uv run pytest \
  packages/openzyme-core/tests/test_reliability_repositories.py \
  packages/openzyme-core/tests/test_migrations.py \
  apps/openzyme-host-api/tests/test_durable_routes.py \
  packages/openzyme-engines/tests/test_execution.py \
  -k "reliability_repositories or migrations or durable_routes or (hpc and not product_route_live)"

77 passed, 96 deselected
```

另有 Host supervisor focused tests 覆盖 nonblocking tick、database contention、bounded
shutdown 与 rollback drain composition。最终 `./scripts/check-mainline.sh` 通过：Python
`2144 passed, 31 deselected`，Web UI `40 passed` 且 build 成功。

## Exit result

Slice 2 exit gate 已通过。没有 active durable row 时可以停止新 admission；存在 active
row 时 composition 必须保留 frozen adapter/supervisor 并 drain/reconcile。显式关闭 worker
会 fail startup，owner mode 由数据库约束保持 immutable，不能 relabel 或交给 legacy。
