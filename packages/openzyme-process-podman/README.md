# openzyme-process-podman

`openzyme-process-podman` 是本地隔离进程与 Workspace Process/Filesystem/Transfer Port 的目标 Adapter。它实现
Kernel 已定义的 workspace/process 语义，不增加领域工具或 Task/Science/Compute 语义。

## 当前迁移状态

本包是 `sandbox_*` 物理表所对应 image/workspace/run 状态 DTO 与 Podman mechanism 的唯一代码 owner。
旧 Domain/Runtime compatibility modules 和顶层别名已经删除；Standard 仅通过显式 Adapter factory/Ports
选择本包。

Adapter 当前为 `target_implemented_not_cutover`，本包已经实现可独立资格验证的 `ProcessIsolationPort` 与
`WorkspaceProcessPort` 以及本地 `WorkspaceObservationPort`/`WorkspaceFilesystemPort`/
`WorkspaceTransferPort`：exact mount/image
identity、Podman named-volume command、foreground argv、bounded
stdin/stdout/stderr、process-group timeout cleanup、epoch/fence retirement、content-bound result 与 typed
effect certainty 都由本包负责。结构化文件 helper 固定 source digest，在无网络容器中再次验证 root-relative
path，拒绝 glob、symlink/hardlink escape 和 CAS drift，并实现 status/stat/list/read/hash 与
write/mkdir/move/copy/remove/unified-diff apply-patch。Transfer Adapter 只接受 manifest-bound opaque
`transfer_ref`，把第二个 exact Podman named volume 挂到固定容器路径，以 create-only、原子、内容校验的方式
执行 upload/download 或物化 immutable revision tree；模型和 Kernel 看不到 volume、staging path、Host path
或 URL。revision sync 不执行 checkout/merge，不创建 checkpoint/publication，也不删除 workspace root。

本包同时提供首个真实 `openzyme.extensions` locator 和包内
`manifests/adapter.json`。locator 只返回 `ExtensionManifestLocator`，manifest 的 canonical digest 为
`sha256:42fbd21f02f1c5c374cbfcf0dea6c129d474010485bb80ef5e821d86e80816b0`，并绑定 Observation、
Filesystem、Workspace Process、Transfer 与 Process Isolation 五个 implementation-free Port contract。
这只证明 manifest/resource/entry-point 供应链闭合；是否启用仍由 exact Distribution、deployment epoch、
Session pin 和 operational Adapter selection 决定。安装 wheel 不会 ambient activate；真实 Podman 调用还必须
通过 authority、workspace generation 与 controlled-operation admission。

这些记录是 Adapter-private mechanism state，不是新的顶层业务 entity 或 Agent tool。Agent-facing
`workspace.exec/fs.*` 仍由 Kernel contract、authority 与 ControlledOperation 治理；Adapter 只接收 exact
workspace generation、root-relative path/argv、authority generation/fence、process epoch 和 deadline，返回
content-bound bounded receipt。当前基础本地桥不接受 SSH/HPC credential 或 remote locator。禁止
absolute/parent/symlink escape、交互/后台/无界进程、未知 effect 自动重试以及从
process/transfer success 推导 publication、formal Compute、Science adoption 或 Task completion。

Standard/EnzymeDesign manifest 可以把该 Adapter 标为 `selected`，application root 也可以在 non-live 图中核对其
`runtime_mounted` identity；二者都不表示本机 Podman 已 `qualified`、真实部署已 `cutover` 或某次容器调用已
`live` 执行。产品级 HMMER/Vina non-live 场景不会调用 Podman。

Session 固定 process Adapter bundle 与 workspace generation。替换 Adapter 或 image contract 不热切换既有
Session；stale generation/fence、image mismatch、lost process response 或 cleanup uncertainty 必须显式失败或
reconcile，不能静默回退到 native process。

本包同时拥有 Podman container lease、exact run/root label 绑定、CID 防替换读取和 fail-stop retirement。
旧 `openzyme_runtime.podman_lifecycle` compatibility path 已删除；canonical implementation 与测试均位于
本包。locator import 不加载 lifecycle/process 模块，实际 Podman 命令只有在 Distribution 显式选择本
Adapter 后才可执行。

Agent Git workspace 的 named-volume mechanism 也由本包唯一实现：volume name、Session/member/generation
owner labels、inspect/create 与冲突拒绝均是 Adapter-private facts。provider-neutral volume fact、identity error
与 backend Port 由 `openzyme-contracts` 定义，Git/LFS recovery mechanism 只消费该 Port，不 import Podman。旧
`openzyme_core.agent_workspace_volumes` 已删除，Core 和 Host 不再导出该 Podman 实现；上层 workspace
lifecycle 只能通过注入的 volume backend/allocator 使用它。创建或复用 volume 只证明物理承载 identity，
不能创建 Session、签发 authority、激活 workspace、发布 revision 或完成 Task。

Agent capsule 的 versioned manifest、Containerfile、qualification probe、digest-pinned build/qualification
command、subprocess executor、exact-volume process runner 与 bounded control-socket server 也由本包唯一拥有。Host
直接从本 Adapter 取得 runner/executor，Core 只消费结构化 runner Port 与
`AgentCapsuleImageQualification` 这一 Adapter receipt 来校验 exact image/manifest identity；旧
`openzyme_core.agent_capsule_image`、旧 Core `PodmanAgentCapsuleProcessRunner`、Core 顶层导出和
`openzyme_core.agent_capsule_assets` 已删除。镜像构建或
qualification 成功不创建 workspace、authority、runtime command、publication 或 Task terminal；mutable base、
mutable output tag、Host mount 和 credential persistence 一律拒绝。

Filesystem、Process 与 Transfer Adapter 现在都要求注入 `WorkspaceOperationLedgerPort`。首次 effect 前必须以
`provider_id + operation_id + intent_digest + session/workspace generation/state_version` 在 Store 中原子 reserve；
只有 reserve 成功的调用可以 dispatch。terminal、`no_effect` 或 `dispatch_in_doubt` receipt 随后写回同一
occurrence。Host/Adapter 重启后，重复 execute/mutate/transfer 只返回 ledger 中的 exact receipt；reserved 或
uncertain occurrence 只能走 `reconcile(original_request)`，不能重新调用 filesystem/transfer helper、启动替代
Podman process，或利用 content-compatible mutation 冒充原 effect。Standard 与 EnzymeDesign composition root
都绑定同一 target SQLite ledger，单元回归覆盖 filesystem、process、transfer 的跨 Adapter epoch terminal recovery。

Observation 只执行 read-only helper，不创建 canonical ControlledOperation；filesystem mutation 与 transfer
由 Kernel 在调用本 Adapter 前完成 durable admission。Transfer request 同时绑定 authority、workspace
generation、opaque ref、transfer manifest、byte budget 和 deadline；source volume 对 download/revision sync
只读，upload 只写预留 object path，且普通传输不能冒充 publication、Git working-tree cleanup 或 workspace
lifecycle cleanup。Helper process 的成功只证明 private workspace 内该次操作有 terminal receipt，不会自动
checkpoint、publish、handoff 或完成 Task。大文件必须走 Transfer Port，不能借 structured CRUD 绕过
publication/LFS/retention 边界。Transfer volume 的 reservation/provision、Git/LFS revision tree preparation
与 durable Store resolver 由 Git/LFS/Store owners 提供；Standard 只在 exact operational selection 和
deployment gate 都通过后挂载本 Adapter。
