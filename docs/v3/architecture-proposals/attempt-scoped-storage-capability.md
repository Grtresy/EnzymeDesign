# Deferred: typed attempt-scoped storage capability

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 Goal 只实施已被真实 campaign 证明必要的局部纠正：`sandbox.workspace.status`、file/exec、source snapshot 与 Podman bind 使用同一个 Host-injected `sandbox_workspace_root`；source snapshot 显式使用同一 attempt 的 `artifact_blob_root`；首次 workspace leaf 必须不存在，已有 canonical workspace 缺目录或出现 symlink 时 fail closed；raw command log 在注入 workspace root 的 attempt 内派生、以 private mode 保存。

这些修复不改变 `session + task board + artifact + run + approval` 的顶层真状态，也不新增 storage service。但它们仍依赖每个调用点正确传递多个独立的 `Path | None`。把这些路径收敛成不可拆分、可验证的 typed capability 会改变 Host composition、core/runtime/engine 构造接口、测试 fixture 和部署配置，属于跨包大架构调整；本 Goal 只记录，不实施。

## Current evidence

1. `SessionRuntimeContext` 分别持有可空 `sandbox_workspace_root` 与 `artifact_blob_root`；workspace status 曾因漏传前者而回落到共享 `/tmp/openzyme-sandbox-workspaces`，file/exec 则使用 attempt root，形成同一 workspace identity 的 split-brain。
2. `SandboxRuntimeService._snapshot_source()` 曾只传 workspace root，漏传 artifact blob root；source snapshot 因而可写入共享默认 Blob root，而同一 run 的结果 artifact 使用 attempt root。
3. workspace、artifact boundary、ExecutionEngine 与 command-log service 各自拥有默认 `/tmp` fallback。调用点漏传仍能通过类型检查和大量 fixture 测试，直到 blank-world live 才暴露。
4. 当前 cutover composition 会注入独立 SQLite、sandbox、artifact/blob 与 HPC workspace roots，但这项完整性只存在于 orchestration 约定和 config digest；下游 service 无法证明自己拿到的是同一个 attempt 的 root set。
5. 公开 evidence 不能携带真实 root path，因此仅靠最终 bundle 扫描无法区分“正确 root 的安全摘要”和“共享 fallback 恰好未泄漏路径”。

## Impact on agent autonomy

- agent 应把 turn 与 token 用在科学策略、证据核对和失败恢复，不应尝试修复 Host-owned `input/manifest`，也不应猜测 artifact snapshot 落在哪一个本地 root。
- harness 应把 storage scope mismatch、missing capability、layout corruption 和 quarantine 状态结构化呈现；不能先报告 READY，再让底层 Podman 以 `statfs` path error 失败。
- 同一次 attempt 内，workspace bytes、source snapshot、registered output、private command log 与 HPC staging 必须属于一个可验证 scope。scope 缺失时 fail closed，不能选择“能跑”的共享默认目录。
- agent 仍保留决定脚本、工具顺序、重试与科学分支的自由；typed storage capability 只约束 Host 世界事实，不接管策略。

## Non-goals

- 不把 filesystem tree 变成新的产品真状态；canonical truth 仍是 repository rows、artifact catalog、run/operation 与 sealed evidence。
- 不让 agent、SDK 或 caller 提交 Host path、root handle、storage profile 或 cleanup authority。
- 不在本提案中替换 SQLite、引入多进程数据库或远程 object store；近期 profile 仍可保持单进程 SQLite。
- 不自动修复 orphan workspace、缺失目录、Blob 冲突或 quarantine 项；repair/cleanup 必须是显式 operator action。
- 不把 HPC remote workspace 与 local sandbox 描述成同一 filesystem；scope 只绑定它们的 attempt identity 与 staging authority。

## Target invariants

1. cutover/eval/live profile 的 Host composition 必须创建一个非空 `AttemptStorageCapability`；各 service 不再分别接收可空 root，也不能在该 profile 使用默认 `/tmp`。
2. capability 至少绑定 `scope_id`、profile、SQLite repository scope、sandbox volume authority、artifact Blob authority、private command-log authority、HPC placement namespace 与 lifecycle epoch。
3. capability 内各 authority 必须由同一次 constructor transaction 产生并携带同一 scope identity；不能把来自两个 attempt 的合法 handle 拼接使用。
4. service 只消费满足其最小权限的子 capability，例如 workspace service 不能打开 credential store，artifact boundary 不能创建 HPC workspace。
5. 新 workspace leaf 必须以 exclusive create 建立；无 canonical row但 leaf 已存在时进入 `orphan_volume_detected`/quarantine，不接管也不修改 bytes。
6. 已有 canonical workspace 只验证，不补建；root/六目录缺失、非目录、symlink 或 ownership/mode 异常返回稳定 corruption code。
7. source snapshot、materialize/register、provider artifactization、HPC fetch 与 command log 都必须记录 private scope binding；跨 scope artifact read 只能通过 catalog authorization 与显式 staging。
8. public projection只暴露 opaque `storage_scope_digest`、profile、empty/preflight outcome 和稳定 error code，不暴露 path、UID、mode、mount 或 locator。
9. capability creation、seal、lease 与 teardown 都要有 fencing；旧 attempt handle 不能在新 attempt 中复活。
10. capability unavailable、scope mismatch 或 downstream service拒绝 capability时不得 fallback；campaign保持 NO-GO。

## Proposed model

```text
AttemptStorageCapability (Host-private, immutable)
  schema_id / scope_id / profile / epoch
  repository_scope_handle
  sandbox_volume_authority
  artifact_blob_authority
  command_log_authority
  hpc_namespace_authority
  capability_digest / created_at / teardown_policy

SandboxVolumeAuthority
  scope_id / root_handle / ownership policy
  required layout contract / quota policy / orphan policy

ArtifactBlobAuthority
  scope_id / blob-store handle / seal policy
  quarantine ledger handle / content-addressing contract

PrivateLogAuthority
  scope_id / root handle / 0700-0600 policy
  retention / digest policy / no-public-read capability

StorageScopeProjection
  schema_id / opaque scope digest / profile
  preflight status / emptiness digest / failure code
```

真实 path/FD、UID、mount 与 backend credential 只存在 Host-private authority。`StorageScopeProjection` 不是 authority，不能用于打开文件。

## Ownership and flow

1. Host composition 在创建 attempt roots 后执行 no-symlink、exclusive leaf、ownership/mode、空目录和 filesystem capability preflight。
2. composition 一次性组装 capability 并计算 digest；repository provider、harness context、engine registry 和 runner adapters只接收所需的 narrowed view。
3. workspace create/status/file/exec 从同一 `SandboxVolumeAuthority` 解析 identity；source snapshot 与 result registration从同一 `ArtifactBlobAuthority` seal bytes。
4. command log 只能通过 `PrivateLogAuthority` 写 raw bytes；public run record只持有 digest、size、truncation 与 opaque log ref。
5. HPC namespace authority只签发 logical workspace/staging handle；runner-private remote path不回传。
6. attempt结束后 capability进入 sealed/failed 状态；保留 evidence 所需 bytes，按显式 policy清理 transient。teardown失败不允许新 attempt复用旧 handle。

## Alternatives considered

- **继续传多个 `Path | None` 并补测试：** 改动最小，但每新增调用面都可能再次漏传，类型系统无法证明 root-set 完整性，不作为长期方案。
- **使用全局环境变量：** 隐式依赖更难审计，测试/并发 attempt 易串线，不采用。
- **把所有文件放进一个目录字符串：** 降低漏传但没有 authority narrowing、epoch/fencing、ownership 与 lifecycle，不足以防 stale scope。
- **立即引入 object-store/storage microservice：** 超出近期单进程 SQLite/trusted Host需求；typed local capability可以先落地，并为未来 backend 留 adapter seam。

## Migration plan

1. 盘点所有 workspace/blob/log/HPC root 构造点与默认 fallback，建立 read-only scope graph 和 contract tests。
2. 定义 `AttemptStorageCapability@1` 与 narrowed authority protocols；先在 local/live composition shadow 构造，同时保留旧参数并逐字段比较。
3. 先迁移 cutover/eval profile，设 `require_explicit_storage_scope=true`；任何旧 fallback 被调用即测试失败并输出稳定 code。
4. 迁移 core workspace/file/exec 与 runtime artifact boundary，删除同一 service 上的独立可空 root 参数。
5. 迁移 ExecutionEngine/provider/HPC fetch 与 command log；增加跨 scope、orphan、symlink、stale epoch 和 teardown fault tests。
6. 将 scope digest绑定到 launch/effective config、run/source snapshot/artifact provenance，但 public projection仍只保留 opaque digest。
7. 审计所有外部调用方；确认没有调用旧 constructors 后，退役 cutover profile 的默认 `/tmp`。non-cutover local-dev fallback若保留，必须显式 profile/version且永不计入 GO。

## Compatibility and rollback

- 迁移期旧 constructor 与新 capability不能在同一 cutover run 混用；shadow只比较，不产生第二套权威 provenance。
- 历史 artifact/run按原 schema读取，不补造 scope identity；它们可用于历史复核，但不是新 blank-world证据。
- 回滚只能把新 campaign保持 NO-GO并恢复显式 legacy non-cutover profile，不能在 capability failure 后静默切回共享 root。
- orphan/quarantine台账与 sealed bytes不因回滚删除；cleanup始终是operator动作。

## Risks

- capability对象过大变成 service locator：用 narrowed protocols 和静态 dependency tests限制每个组件权限。
- local tests变复杂：提供 exclusive temp-scope fixture，但 fixture必须真实创建隔离 roots，不能用内存假 digest冒充。
- lifecycle/fencing实现错误导致空间泄漏：宁可保留 orphan/quarantine，也不能误删 active/sealed bytes。
- public scope digest成为路径 oracle：digest只对 canonical safe preimage计算，不包含path、UID或mount细节。

## Acceptance criteria

- cutover profile 中任一 workspace/blob/log/HPC service 无法在 capability 缺失时构造或运行；静态/运行测试证明没有共享 `/tmp` fallback。
- 两个并发 attempt 的所有 local/remote storage identities、bytes 与 logs 完全隔离；交换任一子 authority均在副作用前 `storage_scope_mismatch`。
- 无 DB row + 预存在 leaf、已有 row + 缺目录/symlink、stale epoch、quarantine conflict 均 fail closed且不修改现场。
- source snapshot、registered result、provider artifact、HPC fetch 与 raw log都可回链同一 private scope；public bundle只含 opaque digest并通过 path/secret扫描。
- agent只收到稳定状态/error/hint，不需要猜测或修复Host storage；有效科学策略在新旧实现下不被额外限制。
