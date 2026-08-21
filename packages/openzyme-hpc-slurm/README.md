# openzyme-hpc-slurm

HPC Plugin 的 Slurm scheduler Adapter。

本包实现 `openzyme.hpc.scheduler-port@1`。submit 只接受 Compute admission 创建并绑定 exact occurrence 的
`PrivateSchedulerOccurrenceCredential`；SSH/login/file credential 不是该类型，不能调用 backend。每个请求绑定
route、target inventory generation/closure、qualification、workload、deadline 和 request digest。

Slurm raw job id 只保存在 HPC Plugin 所有的持久 SQLite occurrence ledger，公开面仅返回 `slurmh-*` opaque
handle。每个 submit/cancel 在首次 effect 前原子 reserve exact provider/kind/operation/request identity；响应丢失
保持 `dispatch_in_doubt`，新 Host/Adapter epoch 的重复请求只读取原记录，`reconcile_submit`/
`reconcile_cancel` 只观察原 occurrence，不重新 submit/cancel，也不切换 scheduler、target 或 route。

`SlurmSchedulerAdapterFactory` 只接受显式注入的 backend、occurrence credential resolver 与 durable ledger。
EnzymeDesign application root 已把该 factory 作为 exact selected `hpc.scheduler:hpc-primary` Adapter runtime
校验并构造到 non-live 产品图中；这叫 `selected + runtime_mounted`，不证明远端 Slurm 已配置、target 已通过
live qualification 或生产流量已经 cut over。因此组件仍标记为 `target_implemented_not_cutover`。

```bash
.venv/bin/pytest -q packages/openzyme-hpc-slurm/tests
```
