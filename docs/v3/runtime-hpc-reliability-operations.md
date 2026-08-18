# Runtime / HPC 可靠性迁移与回滚 Runbook

## 1. 适用范围

本文只用于单 Host、file-backed SQLite、现有 OpenSSH/Slurm runner 部署。它不会授权
live scientific workload，也不会把 non-scientific transport soak 变成 `rxx` 实验。

所有切换都遵守同一原则：先停止新 admission，再审计并 drain 已存在的新 owner row；
绝不通过改配置、改字段或重启把 in-flight effect 交给另一个 owner。

## 2. 切换前检查

1. 使用新的 SQLite 路径创建 fresh database，或确认现有库已经由当前 migration chain
   升级并通过 schema/trigger verification。不要把未知旧库交给启动时猜测修复。
2. 运行 change 的 migration、repository、fault、security 与 non-live gates。
3. 保持 `rxx` frozen；runner 仅允许 fake/local soak，real SSH 需单独显式批准。
4. 保存当前 effective config digest、deployment id、runner control/job ledger、workspace/result roots 与 SQLite backup
   identity。不要在文档或 public log 中记录 credential、target、Host path 或 ControlPath。
5. 确认 Host 与 runner 均为单 active deployment owner；不要让两个进程共享同一 runner
   control/job ledger、workspace/result root 或 SQLite writer role。

## 3. 推荐启用顺序

### 3.1 Shadow observation

先启用：

```text
OPENZYME_RELIABILITY_SHADOW_OBSERVABILITY=shadow_v1
```

Shadow 只记录 bounded private observations，不能授权 retry/dispatch。观察 approval wait、
runtime authority hold、runner phase/effect、writer category 与 redaction 后再继续。

### 3.2 Persistent transport

1. 在 runner trusted TOML 设置短、绝对、deployment-scoped 的
   `runner.transport_control_root`；完整 `ControlPath` 受 Unix socket byte limit 约束，
   runner 会在创建目录或连接 SSH 前按最大 generation fail-fast。随后设置
   `ssh_transport.mode="controlmaster_v1"`，保持所有 bounds 在 example config 范围内。
2. 先运行 fake ControlMaster soak。
3. 经 operator 单独批准后，才可运行双 opt-in real-SSH transport-only soak；该命令只执行
   remote `true`，不得携带 RunSpec 或 scientific payload。
4. 验证 public report 只有 count/closed status，无 target/path/socket/generation。
5. 启动新 runner deployment；不要 hot-mutate旧 manager。

### 3.3 Durable operation owner

先按 route allowlist 小流量切换：

```text
OPENZYME_RELIABILITY_CONTROLLED_OPERATION_OWNER_POLICY=route_allowlist_v1
OPENZYME_RELIABILITY_DURABLE_EXECUTION_ROUTE_ALLOWLIST=<sorted exact route ids>
```

启动时 Host 会把已存在的 active durable route 与新 admission allowlist 合并装配 adapters，
以便 rollback 后仍可 drain old rows。确认每个新 operation 的 `owner_mode` 与 execution 唯一，
且 durable row 不进入 legacy adapter。

### 3.4 Command-based drain

保持：

```text
OPENZYME_RELIABILITY_RUNTIME_DRAIN_CONTRACT=command_v1
```

Public caller 使用 POST admission + GET polling。`sync_v1` 已退休；active durable command 或
continuation 存在时更不能降级。

### 3.5 Generic mutation closure

在所有 writer category 和 external snapshot tests 通过后设置：

```text
OPENZYME_RELIABILITY_MUTATION_CLOSURE_MODE=generic_v1
```

AOX live driver 还要求 command drain、全部 AOX provider/HPC route 的 durable owner，以及
generic closure 同时启用；缺任一 gate 都在 session/operation 前 fail closed。

## 4. Runtime command 调用例

```http
POST /v3/sessions/{session_id}/runtime/drain
Idempotency-Key: drain:{session_id}:1
Prefer: wait=1.5
Content-Type: application/json

{"max_signals":3,"max_steps_per_agent":8,"auto_enqueue_ready_tasks":false}
```

无论 command 是否在 1.5 秒内完成，POST 都返回 HTTP 202。客户端读取 `status_url`：

```http
GET /v3/sessions/{session_id}/runtime/commands/{command_id}
```

只在 `completed|failed|locked|cancelled` 时停止 polling。`locked` 的安全处理是稍后提交一个
新的 idempotency key；不要复用不同 payload、不要并发绕过 session lease。

## 5. Active-row 审计

以下 SQL 只读执行。任何返回值非零都禁止对应 downgrade：

```sql
SELECT COUNT(*) AS active_durable_executions
FROM controlled_operation_execution_records
WHERE lifecycle_state <> 'terminal';

SELECT COUNT(*) AS active_runtime_commands
FROM runtime_command_records
WHERE status IN ('accepted', 'claimed');

SELECT COUNT(*) AS active_continuations
FROM continuation_state_records
WHERE delivery_state IN ('awaiting_result', 'ready', 'claimed');

SELECT COUNT(*) AS active_mutation_scopes
FROM mutation_scope_records
WHERE state IN ('open', 'freezing', 'quiescent');

SELECT COUNT(*) AS active_mutation_writers
FROM mutation_writer_records
WHERE state IN ('registered', 'retiring');
```

Owner-mode invariant必须返回零行：

```sql
SELECT operation.operation_id
FROM controlled_operation_records AS operation
LEFT JOIN controlled_operation_execution_records AS execution
  ON execution.operation_id = operation.operation_id
WHERE (operation.owner_mode = 'durable_async_v1' AND execution.execution_id IS NULL)
   OR (operation.owner_mode = 'legacy_sync' AND execution.execution_id IS NOT NULL)
   OR (execution.execution_id IS NOT NULL
       AND execution.owner_mode <> operation.owner_mode);
```

Runner 使用 `RunnerAttemptJournal.audit_existing()` / startup recovery report 检查每个 attempt。
允许的 nonterminal disposition 只有 same-run pre-effect resume、exact-handle query、same-run
output fetch、preserved reconciliation-required 或 quarantine。未知 disposition、journal drift、
unclosed owned master、direct ambiguity 或 dispatch count 大于一都是 NO-GO。

## 6. 回滚步骤

### 6.1 Persistent transport

1. 从负载入口停止向旧 runner 发送新 admission。
2. 审计所有 nonterminal attempts；让 exact-handle poll/output fetch 收口，保留 direct-SSH
   reconciliation-required evidence。
3. 调用旧 server bounded close。只清理 proven-owned master；保留 attempt journal、RunSpec、
   manifest、handle、output evidence 与 quarantine records。
4. 只有 active attempt audit 为零后，才以 `ssh_transport.mode="disabled"` 启动新 deployment。
5. 不得让 disabled deployment 打开仍由旧 process 拥有的 control/job ledger、workspace/result root，也不得用 legacy
   one-shot SSH 接管 in-flight attempt。

### 6.2 Durable operation admission

1. 将新 admission policy 改为 `legacy_only_v1`。
2. 保持 durable supervisor 和 active routes/adapters 装配，直到 active execution 为零；unknown
   effect 可以长期保持 reconcile-required，不能为了清零而重发或改 terminal。
3. 不修改既有 operation 的 `owner_mode`，不删除 execution，不调用 legacy adapter。
4. active execution 为零后，才可在下一 deployment 禁用相应 durable admission。

### 6.3 Runtime command contract

Command API 不支持回滚到同步 public request。若 active commands/continuations 非零，Host
启动会拒绝 downgrade；即使为零，`sync_v1` 也因已退休而 fail startup。兼容客户端必须升级
为 POST 202 + GET polling，而不是要求 Host 恢复同步 fallback。

### 6.4 Mutation closure

可以停止新 scope admission，但不能删除、重开或改写 frozen/sealed generation、receipt、
snapshot、writer proof 或 fence。已有 `open/freezing/quiescent` scope 必须完成 seal 或显式
failed closure；后续工作使用链接的新 generation。

## 7. Re-entry 判定

只有 deterministic、focused、complete non-live、migration、security/redaction、quiescence、
fake soak、经批准的 real-SSH transport-only soak与主线检查全部通过，才可另行形成恢复
`rxx` 的 GO 决策。任何未跑 gate 都产生 NO-GO，不允许由一次 live 成功补齐。
