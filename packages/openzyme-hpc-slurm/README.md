# openzyme-hpc-slurm

HPC Plugin 的 Slurm scheduler Adapter。

本包实现 `openzyme.hpc.scheduler-port@1`。submit 只接受 Compute admission 创建并绑定 exact occurrence 的
`PrivateSchedulerOccurrenceCredential`；SSH/login/file credential 不是该类型，不能调用 backend。每个请求绑定
route、target inventory generation/closure、qualification、workload、deadline 和 request digest。

Slurm raw job id 只保存在 Adapter 私有 ledger，公开面仅返回 `slurmh-*` opaque handle。响应丢失保持
`dispatch_in_doubt`，`reconcile_submit`/`reconcile_cancel` 调用独立 backend observation，不重新 submit/cancel，
也不切换 scheduler、target 或 route。exact target-scoped manifest 已存在，但尚未被 Distribution 激活，因此
当前状态为 `target_implemented_not_cutover`。

```bash
.venv/bin/pytest -q packages/openzyme-hpc-slurm/tests
```
