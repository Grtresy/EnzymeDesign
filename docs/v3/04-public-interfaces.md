# V3 Public Interfaces

## Media contract

当前 workspace contract：

```text
file_workspace_public@1
application/vnd.openzyme.file-workspace+json;version=1
```

Host、CLI、UI、SDK、event/restore schema 和 tool catalog 作为一个 digest-bound release bundle。
任何混合版本、旧 media、旧 catalog 或 stale continuation 都 fail closed，不做 dual serialization。

## Host API

主要接口：

- `POST /v3/sessions`：创建 session 并固定 project repository binding；
- `POST /v3/sessions/{id}/messages`：写消息和 wakeup signal，不同步 drain；
- `POST /v3/sessions/{id}/runtime/drain`：创建 durable bounded command，返回 `202`；
- `GET /v3/sessions/{id}/runtime/commands/{command_id}`：查询 command outcome；
- `GET /v3/sessions/{id}/workspace`：读取 file-first public projection；
- `GET /v3/sessions/{id}/workspace/changed-paths`：有界 changed-path projection；
- `POST /v3/sessions/{id}/workspace-revision-executions`：准入 exact revision job；
- scientific attempt/authorization、task、lane、approval 和 event 接口。

request authentication、session access、owner/member、capability lease、generation 和 media version
在路由层先验证，核心 mutation 下沉 service/repository。

共享部署中的 executor owner view 只接受身份为 `agent-member:<member_id>` 且角色精确为
`agent` 的 principal；该 principal 只可调用自己的 `GET .../workspace`，并由 Host 重新读取
session membership、lease 与 generation。调用方不能通过 query/body 声明 subject。普通 user、
operator、admin 和浏览器 UI 使用 general catalog，agent principal 使用独立 executor catalog；
二者都必须与同一 release bundle 精确匹配。

## Workspace projection

共享 projection 只输出：

- workspace status、private revision fact、published revisions；
- reports、scientific deliverables；
- external jobs/results、capability leases；
- conversation、task/lane boards、agents、pending approvals；
- activity feed 和 failure observations。

禁止输出 credential/token、private ref、Host path、remote directory、raw runner/Slurm handle、backend log、
storage locator、materialization/staging state。owning executor locator 是独立 subject-scoped view。

## Tool catalog

当前文件/修订工具族包括：

- `workspace.status`、`workspace.exec`、checkpoint verify；
- `workspace.publish` 与 publication identity/audit/path-ref/handoff/research-index；
- `hpc.workspace.request/inspect/verify/sync_source`；
- `workspace_revision_job.submit/observe/cancel`；
- `scientific.deliverables.finalize`；
- task、protocol、lane、report、docs、research 和 scientific lifecycle 工具。

旧 tool name 返回 removed-tool/stale-catalog error，并保留安全的 requested name 和 expected catalog
identity；不得调用替代 operation。

general 与 executor catalog 具有不同 digest。executor catalog 只增加 owner-scoped locator 读取，
不扩大 mutation tool、runner、SSH 或其他 agent workspace 的可见范围。

## CLI 与 UI

CLI 是薄 HTTP client，不读取 SQLite 或 repository root。UI reducer 只接受 versioned file workspace
sections；未知 key 不恢复旧 state。UI 不显示 private locator 或 raw external handle。CLI/UI error
rendering 使用 Host safe error，不展开 secret 或内部路径。

## Restore

continuation snapshot 绑定 session、agent/task/lane/tool call、process epoch、delivery generation、public
schema 和 tool catalog digest。restore 只重建 typed refs。旧 schema/catalog context 被标记 unsupported，
不 replay、rename 或重新解释请求。

## Error semantics

- validation/authorization：请求未被接受，无 effect；
- `no_effect`：可证明外部请求未发生；
- `dispatch_in_doubt`：可能发生，只能 reconcile；
- stale lease/fence/generation：迟到 writer 无 canonical write authority；
- old/incomplete database：mutation 前 `legacy_schema_unsupported` 或 `legacy_removal_incomplete`。

error envelope 不将 unknown 伪装成 not-found 或 retryable。
