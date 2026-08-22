# openzyme-hpc-slurm

HPC Plugin 的 Slurm scheduler Adapter。

本包实现 `openzyme.hpc.scheduler-port@1`。submit 只接受 Compute admission 创建并绑定 exact occurrence 的
`PrivateSchedulerOccurrenceCredential`；SSH/login/file credential 不是该类型，不能调用 backend。每个请求绑定
route、target inventory generation/closure、qualification、workload、deadline 和 request digest。

Slurm raw job id 只保存在 HPC Plugin 所有的持久 SQLite occurrence ledger，公开面仅返回 `slurmh-*` opaque
handle。每个 submit/cancel 在首次 effect 前原子 reserve exact provider/kind/operation/request identity；响应丢失
保持 `dispatch_in_doubt`，新 Host/Adapter epoch 的重复请求只读取原记录，`reconcile_submit`/
`reconcile_cancel` 只观察原 occurrence，不重新 submit/cancel，也不切换 scheduler、target 或 route。
reconcile 会先读取 ledger：既有 terminal receipt 无需 credential；既有 uncertain receipt 遇到 credential 暂时
缺失时保持原 `dispatch_in_doubt`，只有从未 reserve 的新请求才可据 credential 缺失返回 `no_effect`。

`SlurmSchedulerAdapterFactory` 只接受显式注入的 backend、occurrence credential resolver 与 durable ledger。
EnzymeDesign application root 已把 factory/backend/credential resolver 封装在 exact selected
`hpc.scheduler:hpc-primary` Adapter runtime binding 中，并只从该 binding 派生 operational scheduler；这叫
`selected + runtime_mounted`，不证明远端 Slurm 已配置、target 已通过
live qualification 或生产流量已经 cut over。因此组件仍标记为 `target_implemented_not_cutover`。

```bash
.venv/bin/pytest -q packages/openzyme-hpc-slurm/tests
```
