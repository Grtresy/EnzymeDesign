# Slice 3 checkpoint：non-blocking continuation 与 command-based drain

## 当前结论

Slice 3 的实现与 exit gate 已闭环；完整 non-live gate 与 caller audit 均已通过。
Public `/runtime/drain` 已无同步 fallback，AOX driver 已迁移到 POST admission + GET
polling，CLI、Web UI、eval 在本次基线没有该 endpoint 的直接 caller。

`rxx` campaign 继续冻结。本 checkpoint 没有执行 live LLM、live SSH、live HPC 或
科学实验，也没有修改 `openspec/changes/aox-hmm-blank-world-cutover`。

## Landed contract

1. durable admission transaction 原子创建 operation、approval、execution、immutable
   dispatch request、continuation origin/process identity 与 event；失败整组回滚。
2. Host-private live-process registry 绑定 exact sandbox run/workspace/runtime identity、
   process epoch、control channel 与 delivery generation。registry 不是 canonical truth。
3. durable SDK wait 会 park exact process，由 outer sandbox supervisor 持有；原 agent
   turn 在 bounded deadline 内释放 signal claim、session lease、agent slot、runtime
   command 与 HTTP request ownership。suspension 不改 task terminal。
4. execution result 与 continuation delivery 分离。delivery worker 只向 exact process
   epoch 投递一次；identity/fence/generation drift fail closed，sandbox terminal 后才排队
   owner-agent wakeup。
5. Host restart 若丢失 attached process，会明确 terminalize delivery recovery failure；
   已完成 external execution 与 immutable result 被保留，backend dispatch counter不增加。
   `journaled_sdk_call_boundary` 保持 disabled closed enum。
6. `/runtime/drain` POST 强制 `Idempotency-Key`，closed request，始终 HTTP `202`；
   `Prefer: wait` 只允许 `0..2` 秒且不取消 command。GET 是 session-scoped closed
   `runtime_command_status@1` projection，不暴露 owner/lease/fence/process/path。
7. `RuntimeCommandWorker` 在 durable supervisor 中独立 claim command。session lease
   冲突把该 command 终结为 `locked`，不会创建 replacement 或并发 scheduler。
8. `sync_v1` public contract 已退休；配置 downgrade 在 startup fail closed，active
   command/continuation 进一步阻止任何 owner adoption。

## Deterministic evidence map

- core repository/worker/registry/restart：
  `packages/openzyme-core/tests/test_reliability_repositories.py`、
  `packages/openzyme-core/tests/test_runtime_commands.py`；
- process transfer/control-socket/suspension：
  `packages/openzyme-core/tests/test_sandbox_runtime.py`；
- HTTP 202/GET/auth/idempotency/prefer/lock/restart/background-disabled：
  `apps/openzyme-host-api/tests/test_runtime_commands.py`、
  `apps/openzyme-host-api/tests/test_durable_routes.py`；
- AOX caller polling与 error precedence：
  `apps/openzyme-host-api/tests/test_aox_cutover_live.py`（non-live fixtures only）。

## Rollback rule

Command API 不回滚为同步 HTTP。停止新 command admission 前后都必须保留 active
command/continuation rows 与 worker recovery；不得用 legacy worker接管 attached process
或重放 external effect。active rows 非零时 downgrade audit 是 `NO-GO`。
