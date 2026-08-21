# Execution SDK 与领域计算包

`openzyme_execution_sdk` 是无生物依赖的受控 sandbox SDK，导出：

- `ControlClient` 与 closed `ExecutionSdkError`；
- `workspace_revision`：兼容期的 revision job 提交、观察和取消 client protocol；
- `submit_workload`：只接受 parsed `ExecutionWorkloadSpec` 与 exact
  `ExecutionRouteIdentity` 的目标协议。

AOX 领域计算已迁入 `enzymedesign_aox_executor` subordinate Driver；
`enzymedesign_aox` Product Plugin 继续拥有 workflow 与 scientific file contracts：

- `aox_reference`：选择 HMM/coordinate reference 并组装 scoring input；
- `aox_hmmer`：解析和过滤 HMMER CSV；
- `aox_sequence_join`：以 accession identity 连接候选 sequence/length；
- `aox_motif`：reference-coordinate motif scoring；
- `aox_similarity`：candidate similarity graph；
- `aox_candidate`：候选集合确定性校验；
- `aox_finalization`：向 Host 提交 exact published-file deliverable finalization。

旧 `openzyme-pipeline` wheel 已从 workspace、锁文件、Host dependency 和 active source tree 删除。
仓内通用 sandbox 调用方必须使用 `openzyme_execution_sdk`；AOX calculation 调用方使用
`enzymedesign_aox_executor.aox_*`。纯计算函数只读取调用方提供的 bytes/text 并返回确定性结果；
Host-bound function 通过 execution SDK 发出 typed operation。SDK 不发现 ambient
credential/path，也不提供旧 catalog、registration、materialization 或 staging helper。

## Revision job 兼容协议

```python
from openzyme_execution_sdk import workspace_revision

job = workspace_revision.submit(
    operation=operation,
    execution_request=execution_request,
    clean_observation=clean_observation,
)
state = job.observe()
```

这是迁移期现有 Host admission protocol。三个对象必须来自同一 Host admission flow，并精确绑定
source revision、commit/tree、LFS closure、workspace generation、lease、
command/resource/environment 和 target policy。不要手工合成或从 filename 推断 identity。

`observe()` 只观察同一 execution/operation/request。`cancel(reason_code=...)` 创建 cancel intent；
返回不等于 backend 已取消。未知 dispatch 不能用新的 submit 代替。

## Closed workload 协议

新 Plugin/Driver 应构造 closed `ExecutionWorkloadSpec`，由 capability resolver 返回
exact route identity，再调用 `submit_workload`。workload schema 只允许 root-relative cwd、
argv/entry point、revision inputs、resource/environment policy digest、result contract 与
capability requirements；Host/remote path、credential、raw scheduler ID、implicit staging 和
`expected_outputs` 均被 closed parser 拒绝。

## Scientific finalization

AOX finalization request 传递 published revision/path entries、producer adoptions、format contract 和 bundle
identity。Host 从 immutable Git/LFS source fresh-read actual bytes 后验证。local 文件存在、job success 或
17 个 path 齐全都不自动形成 accepted deliverable。

typed empty 只允许 installed calculation 的 exact zero receipt；missing/failed input 不得当作 empty。
