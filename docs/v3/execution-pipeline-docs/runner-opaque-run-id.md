# Runner Opaque Run Identity

Host 与 runner 之间的 public lifecycle identity 是 server-issued opaque `run_id`。它绑定一次已准入的
revision execution occurrence、scheduler credential、target qualification 和 request digest。

公开调用只允许围绕 exact handle 执行 dispatch/reconcile/observe/logs/cancel。raw Slurm job id、remote
run directory、RunSpec recovery payload 和 SSH transport state 不返回 Host client、agent 或 UI。

dispatch 的 effect 语义：

- credential/validation/source preparation 在 submit 前失败：`no_effect`；
- payload 已可能送达但 handle receipt 未完成：`dispatch_in_doubt`，只允许 reconcile；
- handle 已持久化：restart/lease takeover 继续观察同一 occurrence；
- cancel request：只写 intent，直到 backend observation/receipt 才能判断结果。

runner 从 exact commit/tree/LFS closure 准备 compute source。compute payload 不含 `.git`、Git/LFS binary、
repository credential、endpoint 或 Host path。expected-output validation 只针对 declared contract；无输出
contract的 success 不创建空输出。

ControlMaster 复用只是 runner-owned transport optimization，不保持 shell cwd/environment，也不给 executor
控制 SSH options 或 scheduler authority。
