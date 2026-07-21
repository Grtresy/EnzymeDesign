# Final verification and `rxx` re-entry decision

- Recorded: 2026-07-21
- Change: `runtime-hpc-reliability-refactor`
- Deterministic implementation verdict: `GO`
- Persistent-SSH deployment qualification verdict: `GO`
- Numbered `rxx` campaign re-entry eligibility: `GO`
- Actual numbered `rxx` execution state: `HOLD / NOT STARTED`

这里的 `GO` 只表示实现和部署资格闸门已经闭环，不会自动修改目标部署配置，
也不授权或启动任何编号 `rxx` 实验。本次获批外部验证只临时启用
`controlmaster_v1`，并且只允许远端 `true` 和只读 rollback audit；验证结束后，
ignored deployment config 已逐字节恢复为 transport disabled。

## Complete evidence

| Gate | Result |
| --- | --- |
| Python lint and compatibility caller audit | `ruff` green；21 seams，0 violations |
| Focused domain/core/runtime/quiescence | `273 passed` |
| Focused engines/execution/migrations | `143 passed, 1 deselected` |
| Complete runner non-integration suite | `240 passed`；包含 256-channel fake-ControlMaster soak |
| Explicit real-SSH transport-only soak | 32 次远端 `true`，4 generations，clean shutdown，0 ambiguity |
| Host API/runtime/AOX non-live focused suites | green |
| Public projection and secret-canary suite | `182 passed` |
| Repository mainline | Python `2146 passed, 31 deselected`；Web UI `40 passed`；build green |
| V3 local workflow eval | 2 scenarios passed，0 failed；AOX fixture 明确不可作 cutover proof |
| Documentation links | 65 files，125 local links，0 broken |
| OpenSpec and patch hygiene | strict validation green；`git diff --check` green |

这些测试覆盖 migrations 26-31、clean/upgrade/legacy reads、owner-mode immutability、
active-row downgrade rejection、durable execution/continuation/runtime-command recovery、
generic mutation quiescence、public redaction，以及 cross-layer transport fault matrix。
direct SSH post-transmission ambiguity 的 payload dispatch count 保持至多一次，未知结果
不会被转换为 retryable success 或 replacement operation。

## Completed external qualification

外部资格验证及其 redacted evidence 见
[`real-ssh-soak-and-rollback-audit.md`](real-ssh-soak-and-rollback-audit.md)。结论如下：

1. 启用前只读审计确认 transport disabled、runner process 不在运行、runner attempt 为
   0、nonterminal/reconciliation 为 0，且 control root 不存在。
2. 第一次本地启动在任何 SSH 连接之前发现历史默认 ControlPath 过长；远端命令数为
   0。实现随后改为在创建目录或连接 SSH 之前，按最大 generation fail-fast 校验 socket
   path；example 和 runbook 改用短的 absolute deployment-scoped root。
3. 双重 opt-in 的真实 soak 完成 32 次远端 `true`，每 8 次轮换 generation，共 4 个
   generation；clean shutdown 为 true，ambiguous direct run 为 0。
4. post-soak 与最终只读 rollback audit 均为 0 attempts、0 nonterminal、0 invalid、
   0 reconciliation。配置 digest 与 artifact-tree digest 恢复为原值，临时 control root
   和 ownership metadata 已清除，transport 最终保持 disabled。
5. 全程没有调用 runner `call-tool`、RunSpec、Slurm、科学 payload、provider/LLM 或任何
   编号 `rxx`。

因此 tasks `3.23` 与 `3.24` 的目标部署证明均已完成；之前阻止资格放行的两个外部
gate 不再 open。

## Re-entry and activation rule

本 change 现在允许 operator 另行决定是否恢复编号 campaign，但本次执行状态仍为
`HOLD / NOT STARTED`。实际重启前仍必须有新的显式授权，并且：

1. 为目标部署配置短的 absolute、private、deployment-scoped
   `runner.transport_control_root`，显式启用 `controlmaster_v1`；不得复用本次已删除的
   临时 root。
2. 在配置或部署状态发生变化后，重新执行只读 admission audit，确认不存在未分类 active
   attempt、foreign/unclosed generation 或 evidence drift。
3. 只启动被明确点名的 campaign/attempt；本资格记录不构成任何 rxx 的隐式 admission。
4. 任一 ambiguity、secret-canary 命中、未分类 active attempt、payload count 大于一，
   或 cleanup/evidence drift 都立即回到 `NO-GO`，不得 fallback 或 replacement dispatch。

operation/result/delivery/quiescence terminal 均不替代 agent 对业务 task 的显式
`task.finish`。
