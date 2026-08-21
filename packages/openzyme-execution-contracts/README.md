# openzyme-execution-contracts

本包是 Compute/HPC 与独立 runner 之间闭合、实现无关的 execution wire contract owner，当前拥有：

- typed `ExecutionWorkloadSpec`、revision path inputs、result contract 与 capability requirements；
- exact route/inventory/qualification identity 与安全 failure envelope；
- opaque runner handle、observation、cancellation 和 reconciliation 的 closed parser/serializer。

`mcp-hpc-runner` 与 runner adapter 只依赖该 wheel；runner 不再依赖整个
`openzyme-domain`。formal admission、source manifest、qualification、dispatch/result lifecycle
由 `openzyme-compute` 拥有，旧 `openzyme_domain.workspace_job_wire` 兼容模块与顶层别名已经删除。

这些 DTO 不接受 Host/remote path、credential、raw scheduler ID、implicit staging 或
`expected_outputs`，也不赋予 scheduler、SSH、workspace 或 Task authority。Plugin/Adapter/Host
仍须用 exact route、inventory generation、generation/fence 与 ControlledOperation lifecycle 执行。

```bash
uv run pytest packages/openzyme-execution-contracts/tests
```
