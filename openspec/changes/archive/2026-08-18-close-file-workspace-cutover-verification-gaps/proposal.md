## Why

十四个 file/revision cutover changes 的任务计数虽然已经全部勾选，但当前实现仍存在不可执行的 HPC cancellation receipt、未验证 removal receipt 的启动 gate、丢失异常因果的宽泛捕获，以及与实际测试和当前 source identity 不相符的验收声明。继续沿用这些完成状态或旧 release receipts 会把未闭合的产品缺陷误记为已验收，因此必须在归档和 fresh-install 重建前建立一个可执行、可诊断、source-bound 的统一收口。

## What Changes

- **BREAKING**：确认 file/revision/publication/job 是唯一当前产品合同；从当前规范和文档中删除 generic artifact catalog、runner staging、`expected_outputs` 及其兼容性暗示，同时保留 authority、approval、lease/fencing、effect certainty、idempotency、provenance、secret/path 与 HPC supervisor 边界。
- 建立统一的结构化诊断合同。所有边界失败都携带稳定错误码、阶段、关联 identity、effect certainty、重试或 reconcile 规则、是否已经发生 mutation、是否使用 fallback、脱敏 cause chain 和 diagnostic identity；内部诊断保留完整异常链与操作证据。静默异常、模糊 catch-all、隐藏 fallback 和未经合同允许的自动重试均不合法。
- 修复 workspace-revision HPC lifecycle：runner、Host 和 domain 消费同一个可执行 cancellation wire contract；closed cancellation receipt 必须包含并绑定 `receipt_id`，重复调用和 restart replay 必须重新验证 exact handle，response loss 不得授权 replacement cancellation 或 submission。
- 修复 agent Git workspace recovery、workspace publication 和 revision-path handoff 的异常分类与 cleanup 语义。未知基础设施或程序错误不得伪装成 Git corruption，外部效果不确定不得丢失原始 cause，cleanup residue 不得静默忽略。
- 新增带类型的 deployment proof。fresh install 使用确定性的 bootstrap receipt，并证明未创建任何 legacy schema/storage；offline removal 继续要求唯一完整 ledger。正常启动只读验证 exact generation、manifest、receipt digest 和相应 proof closure，任何不一致都详细失败且不修改部署。
- 将本设备上的 OpenZyme 部署重建为 fresh install：在已验证 quiescence 后，仅删除精确解析且证明归属于 OpenZyme 的旧数据库、运行记录、legacy storage、旧 receipts、缓存和备份；不删除 Git/OpenSpec 历史、源码、repository Git/LFS current truth 或任何非 OpenZyme 数据。
- 恢复行为级验收：覆盖 HPC dispatch/observe/cancel/replay/restart/response-loss/tamper，scientific adoption/finalization/AOX finalizer，Web UI state/view/controller，以及 production composition、authority、fencing、restart、reconciliation 和外部 effect uncertainty。验收不得以枚举、名称扫描或过时测试路径替代真实行为证明。
- 纠正十四个目标 changes 中已被反证的任务标记和证据引用。旧 receipts 保留为 superseded history；只有最终 clean HEAD、fresh-install state、完整 mainline 与逐 change evidence map 可以签发当前 release receipts 并授权归档。

## Capabilities

### New Capabilities
- `structured-operation-diagnostics`: 定义跨 Host、runner、runtime 和 workspace service 的详细、脱敏、effect-aware 错误合同，以及内部完整 cause/trace 证据要求。
- `file-workspace-deployment-proof`: 定义 fresh-install bootstrap receipt、offline-removal ledger、启动时只读 fail-closed 验证和本机 OpenZyme 旧数据精确删除边界。
- `file-workspace-cutover-assurance`: 定义十四个 cutover changes 的真实完成状态、行为级 qualification、source-bound evidence、receipt supersession 与归档门槛。

### Modified Capabilities
- `controlled-operation-execution`: 要求外部效果失败保留具体 cause、阶段和 effect certainty，并以 exact workspace job/revision identity 完成 cancellation、reconciliation 与 restart recovery。
- `mcp-hpc-runner`: 统一 revision-bound lifecycle wire contract，验证 cancellation receipt 与 replay handle，并正式移除 staging/fetch/`expected_outputs` 合同。
- `sandbox-host-authority`: 将 engine-facing mutation 和外部效果边界统一为 file/revision/publication/job 语义，不再暴露或暗示 artifact-era gateway。

## Impact

影响 `AGENTS.md`、`docs/OpenZyme架构设计.md`、相关 `docs/v3/` 稳定文档，V3 domain/core/runtime/execution seams、Host API、MCP HPC runner、workspace publication/recovery/handoff、scientific finalization、Web UI、SQLite bootstrap/startup verifier、architecture qualification registry/tests、十四个 active OpenSpec changes 及本机 OpenZyme deployment state。数据删除是有界但不可逆的本机维护操作，必须在代码与 proof verifier 完成、目标 identity 清单和 quiescence 均通过后执行；不包含 live provider、真实 HPC、push 或 PR。
