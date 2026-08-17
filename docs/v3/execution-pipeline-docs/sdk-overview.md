# Current Pipeline SDK Overview

`openzyme_pipeline` 当前导出：

- `workspace_revision`：提交、观察和取消 revision-bound job；
- `aox_reference`：选择 HMM/coordinate reference 并组装 scoring input；
- `aox_hmmer`：解析和过滤 HMMER CSV；
- `aox_sequence_join`：以 accession identity 连接候选 sequence/length；
- `aox_motif`：reference-coordinate motif scoring；
- `aox_similarity`：candidate similarity graph；
- `aox_candidate`：候选集合确定性校验；
- `aox_finalization`：向 Host 提交 exact published-file deliverable finalization。

模块分两类：纯计算函数只读取调用方提供的 bytes/text 并返回确定性结果；Host-bound function
通过 pipeline client 发出 typed operation。SDK 不发现 ambient credential/path，也不提供旧 catalog、
registration、materialization 或 staging helper。

## Revision job

```python
from openzyme_pipeline import workspace_revision

job = workspace_revision.submit(
    operation=operation,
    execution_request=execution_request,
    clean_observation=clean_observation,
)
state = job.observe()
```

三个对象必须来自同一 Host admission flow，并精确绑定 source revision、commit/tree、LFS closure、
workspace generation、lease、command/resource/environment 和 target policy。不要手工合成或从 filename
推断 identity。

`observe()` 只观察同一 execution/operation/request。`cancel(reason_code=...)` 创建 cancel intent；返回
不等于 backend 已取消。未知 dispatch 不能用新的 submit 代替。

## Scientific finalization

AOX finalization request 传递 published revision/path entries、producer adoptions、format contract 和 bundle
identity。Host 从 immutable Git/LFS source fresh-read actual bytes 后验证。local 文件存在、job success 或
17 个 path 齐全都不自动形成 accepted deliverable。

typed empty 只允许 installed calculation 的 exact zero receipt；missing/failed input 不得当作 empty。
