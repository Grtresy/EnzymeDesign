# V3 Target Architecture

## 目标形态

```text
User / CLI / Web UI
        |
        v
Host API: authentication, media contract, command admission
        |
        v
Canonical control plane: repositories + durable events + projections
        |
        +--> Resident agent runtime: signals, leases, bounded turns
        +--> Git workspace/publication: private refs, revisions, Git LFS
        +--> Capability engines: research, controlled operations
        +--> Revision-bound execution: executor workspace -> HPC runner
```

Host 是组合根，不是所有长流程的同步执行线程。SQLite 是 control-plane persistence；项目 Git
仓库是文件内容和修订真相；runner/provider 是外部 effect boundary。

## 权威 owner

| 事实 | 唯一 owner |
|---|---|
| session、task、lane、approval | 对应 core repository/service |
| delegation/inbox | `ProtocolService` |
| agent wakeup/turn | `AgentRuntimeSignal` + session lease |
| agent file edits | owner-scoped workspace generation |
| shared files | `PublishedRevision` + `RevisionPathRef` |
| large bytes | Git LFS closure/pin/read receipt |
| provider/runner effect | `ControlledOperationExecution` 或 revision job owner |
| scientific deliverable | selection adoption + published file + validation receipt |
| task terminal | `task.finish` / task finish repository |
| public state | `FileWorkspaceProjectionBuilder` 从 typed repositories 投影 |

一个 owner 的状态不能通过另一个 owner 的事件间接猜测。

## Repository 与 workspace

project repository binding 是版本化、不可变的连接和 policy identity。session 固定一个 version。
agent workspace 绑定 member、generation、private namespace 和 capability lease。checkpoint 是私有
修订；publication 是显式共享边界。published revision 不受之后私有 dirty state 影响。

Git LFS object 与 ordinary blob 都属于 exact tree。发布前必须验证 actual bytes；shared revision
出现后必须有 immutable closure、verification 和 pins。GC 只能依据不可达证明和删除 receipt。

## Capability engine

引擎通过 `ToolSpec` 与 Host context 使用 canonical service，不直接写顶层状态。局部 graph、
provider adapter 或 process runner 可以在 engine 内部存在。engine error 不允许自动换 backend、
改参数、完成 task 或合成文件。

## Executor 与 HPC

executor 使用独立远端 workspace 并持 login/file credential。scheduler credential 只由一次已准入
revision job occurrence 发行。runner 接收 exact source manifest、command/resource/environment digest，
返回 opaque handle 和 bounded observation。结果以 result receipt/revision link 表达，不返回 Host path。

## Public projection

`file_workspace_public@1` 是唯一 current workspace media contract。共享 view 不含 credential、
private ref、host/remote path、raw scheduler id 或 backend log。owner locator 只在 subject/member/lease/
generation 全部匹配的专用 executor view 中出现。

## Deployment

fresh install 直接创建 final schema。旧部署不能在 Host startup 中自动升级，只能按离线两阶段
operator 流程迁移。partial removal 会阻止 normal startup。历史 Git/LFS ref 可被 standalone
verifier 读取，但永远不可被 current workflow 采用。
