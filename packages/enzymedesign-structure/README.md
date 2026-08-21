# enzymedesign-structure

EnzymeDesign 的结构分析产品插件。首个能力是 `enzymedesign.fpocket.detect`：Agent 选择 exact route 后，
local/HPC Driver 只把一个 immutable PDB revision input 编译为 closed `ExecutionWorkloadSpec`；
`openzyme-compute` 才能执行、观察与 reconcile。Driver 不导入 SSH/Slurm/HPC 实现，不持有 credential，
也不自动切换 route。

插件声明 `software.fpocket >=4,<5` 以及 `fpocket --version`/`fpocket --help` qualification。
直接用 workspace Shell 调用 fpocket 仍只是 exploratory process receipt，不能作为 formal structure result、
Scientific adoption 或 Task finish evidence。

```bash
.venv/bin/pytest -q packages/enzymedesign-structure/tests
```
