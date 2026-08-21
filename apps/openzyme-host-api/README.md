# openzyme-host-api

OpenZyme 的通用 HTTP delivery Adapter。当前源码的公开入口是 exact
`file_workspace_public@2`；没有 `@1` 在线兼容、产品能力自动发现或按 Session 选择旧 Host 的模式。

```sh
pip install openzyme-host-api
pip install 'openzyme-host-api[server]'
```

Host wheel 不再提供 `legacy` extra。历史读取、迁移验证与删除审计使用独立的 offline operator
入口，不能通过安装 Host 可选依赖恢复旧在线组合。

## 组合边界

包根 `openzyme_host_api` 只导出：

- `create_v2_app()` 与 closed Host DTO；
- `FileWorkspaceV2HostSurface`；
- Host 认证策略；
- manifest-mounted Plugin GET route 的通用交付协议。

导入包根不会加载旧 mixed runtime、Research、Science、Compute/HPC、runner 或 EnzymeDesign。Host 不选择
SQLite、Git/LFS、模型、Podman、Provider、HPC target 或科学策略；Distribution 必须注入：

1. 已通过 deployment startup proof 的 exact release；
2. `KernelPublicWorkspaceProjectionService`；
3. 已由 `mount_extension_surfaces()` exact-match 的 projection/HTTP runtime；
4. 把 HTTP command 翻译为 Kernel application command 的窄网关；
5. 本 Distribution 明确开放的 Kernel mutation route closure。

Plugin query runtime 的 owner、method、normalized path 与 contract digest 必须和 manifest 一致。当前 query
SPI 只允许 GET；Plugin mutation 必须经过 Kernel application service，不能直接访问 Core repository、SQLite
连接或 Host 私有 service。

## `file_workspace_public@2`

Session 创建前只有 release/public-contract identity：

```text
POST /v3/sessions
Accept: application/vnd.openzyme.file-workspace+json;version=2
OpenZyme-Workspace-Contract: file_workspace_public@2
OpenZyme-Release-Digest: sha256:...
OpenZyme-Public-Contract-Digest: sha256:...
Idempotency-Key: caller-stable-intent
```

Session 建立后，inspection 返回六个相互校验的响应 identity：workspace contract、release、public contract、
projection、capability binding 与 affordance snapshot。每个 mutation 必须回传全部六项和调用者选择的
`Idempotency-Key`。任何 identity 漂移都在业务 handler 前失败，`mutation_applied=false`、
`fallback_performed=false`；如果 gateway 已越过 effect boundary 后失去结果，则保留
`effect_certainty=dispatch_in_doubt`，不自动重发或换 route。

```text
GET /v3/sessions/{session_id}/workspace
POST /v3/sessions/{session_id}/messages
POST /v3/sessions/{session_id}/tasks
POST /v3/sessions/{session_id}/tasks/{task_id}/finish
POST /v3/sessions/{session_id}/runtime/drain
```

上述只是通用 route contract 的示例；实际可用集合由 Distribution 注入，缺少 application/runtime 的 route
必须不存在或 fail closed。消息入口只记录 user-source conversation、root-Agent admission、inbox 与 durable
runtime signal，不同步 drain，也不完成 Task。

响应正文形状：

```json
{
  "schema_version": "file_workspace_public@2",
  "release": {"schema_version": "openzyme_layered_release_identity@1"},
  "core": {
    "session": {},
    "tasks": [],
    "lanes": [],
    "agents": [],
    "protocol": {},
    "conversation": {},
    "approvals": [],
    "authority_leases": [],
    "capability_binding": {},
    "runtime": {},
    "workspace": {},
    "publications": [],
    "operations": {},
    "failures": {},
    "tool_reflection": {}
  },
  "extensions": {},
  "projection_digest": "sha256:..."
}
```

Reporting、Research、Science、Compute/HPC 与 EnzymeDesign 状态只能出现在 exact namespaced extension
section，不能成为 Core 字段。Host 不调用旧 projection builder、不在线翻译事件/continuation，也不因缺少
Plugin 而返回空成功替代物。

## 当前实现与部署事实

OpenZyme Standard 已有真实 SQLite → Kernel application → generic Host 的 Plugin-free non-live composition，
覆盖 Session bootstrap、inspection、Task/Lane/Agent/Protocol/Approval/Authority、message admission、local
workspace CRUD/exec、checkpoint/publication/handoff 与 bounded runtime turn。EnzymeDesign exact component
graph、Plugin/Driver contributions、namespaced projection 和 dynamic affordance 已在三 profile non-live
qualification 中完成显式 mount；这仍不是设备上的 deployment activation 或任何 live Provider/HPC proof。

本仓库没有执行真实 offline cutover、Provider、SSH/Slurm/HPC 或设备删除。旧 mixed app、在线 `@1`
projection、runtime implementation wiring、Science/HPC service 与 repository transport 已从 Host wheel 删除；
Git 历史和独立 offline verifier 保留历史证据，但不存在可导入的在线兼容入口或自动 translation/fallback。

## 验证

```sh
uv run pytest apps/openzyme-host-api/tests/test_v2_app.py
uv run pytest packages/openzyme-standard/tests/test_standard_v2_host.py
uv run pytest apps/openzyme-host-api/tests/architecture_qualification/scenarios/test_composition_profiles.py
```

完整架构资格通过 `scripts/check-v3-architecture-qualification.sh` 运行，并禁止 live credential、IP network、
skip/xfail 与未声明外部效果。资格通过不等于真实 cutover 已授权或已执行。
