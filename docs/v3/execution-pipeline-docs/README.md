# Execution Pipeline SDK Docs

本目录是 executor 可通过 `docs.search` / `docs.read` 检索的 current 文档集。当前执行模型是
native agent/executor workspace + immutable Git revision + revision-bound external job；不存在通用
artifact catalog、自动 materialize/register/stage/fetch 或 Host path 输入。

建议阅读：

- [sandbox-rules.md](sandbox-rules.md)：进程、文件和 authority 安全边界；
- [sdk-overview.md](sdk-overview.md)：通用 `openzyme_execution_sdk` 与领域计算包边界；
- [workspace-revision-jobs.md](workspace-revision-jobs.md)：revision job submit/observe/cancel；
- [runner-opaque-run-id.md](runner-opaque-run-id.md)：Host/runner 生命周期；
- [aox-hmm-live.md](aox-hmm-live.md)：当前 AOX/HMM file-first scientific workflow；
- [aox-motif-rule-score-v1.md](aox-motif-rule-score-v1.md)：motif calculation；
- [aox-sequence-similarity-v1.md](aox-sequence-similarity-v1.md)：similarity graph calculation。

固定边界：

- executor 在自己的 workspace 中原生读写文件和使用 Git；
- 共享输入必须是 clean private checkpoint 或 immutable publication 的 exact revision identity；
- scheduler submit 需要 Host 发放的一次 occurrence credential，login credential 不具备该权限；
- compute payload 不携带 `.git`、Git/LFS credential、endpoint、Host path 或 object locator；
- runner TOML 只含 transport/workspace/scheduler 与有界资源策略，不接受领域 `[adapters.*]`
  catalog；软件可用性由 Plugin/Driver requirement 与已采用 target inventory 证明；
- SDK call pending 时由 durable continuation 恢复同一 operation，调用方不得自行 replay；
- remote workspace 的 SSH/SFTP/rsync 由 target-scoped Adapter 执行，公开请求只含 opaque workspace binding；
  lost response 必须 reconcile 同一 occurrence，不能重发或换 target；
- job terminal、scientific deliverable、report、task finish 和 master response 是独立事实；
- historical import 不能被 current workflow 采用。

已删除 API 的旧文档不再注册。请求旧 doc id 或旧 SDK module 应显式失败，不能给出兼容示例。
