# enzymedesign-alphafold

AlphaFold 3 产品插件。`enzymedesign.alphafold.predict` 只接受 immutable job JSON revision input、
exact route 和政策 digest；HPC Driver 将它编译为 closed `ExecutionWorkloadSpec`，不接收或公开模型参数、
数据库、credential、Host/remote path 或 scheduler handle。

可用性要求同一 target 同时满足 Compute route、`software.alphafold3 >=3,<4`、
`asset.alphafold3-model-parameters`、`dataset.alphafold3-database` 与 `accelerator.cuda`。任一资源缺失
都会形成结构化 blocker，不得偷偷换 route、数据库或本地执行。正式结果必须经过 Compute lifecycle；raw
Shell receipt 不是 scientific evidence，也不完成 Task。

```bash
.venv/bin/pytest -q packages/enzymedesign-alphafold/tests
```
