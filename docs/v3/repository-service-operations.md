# Project repository service 运维合同

本文描述 C1 `establish-project-repository-bindings` 已落地的 Host-owned repository
service，以及 C2 `establish-agent-capability-leases` 对 production credential 与
revocation seam 的收口。它们是后续独立 agent Git workspace、发布/同步和 Git LFS
工作产物的基础，但 **C1/C2 仍不创建 clone/worktree/capsule、不发布 revision、不访问
upstream，也不实现真实 remote-HPC credential/workspace/job**。C2 中的 general/executor
capability names 只是 policy declaration，不是这些后继产品能力已可用的证明。

## 1. 进程与 authority 边界

repository transport 是与普通 V3 Host API 分离的 HTTPS FastAPI app：

- V3 Host 继续监听 `http://127.0.0.1:8000`，负责 session、task、approval 与 workspace
  projection；
- `openzyme-repository serve` 默认从
  `OPENZYME_REPOSITORY_HTTPS_ORIGIN` 解析端口，本地开发监听
  `https://localhost:8443`；
- Git/LFS route 只接受 repository-scoped Bearer credential，不继承 `local-dev`
  principal 免认证，也不要求 `/v3` mutation 的 `Idempotency-Key`；
- internal remote 与 upstream 是两份独立 identity。internal transport 不读取 upstream
  credential、不在本地失败时切换到 upstream，也不执行 push、PR、release 或 deletion。

Host repository process 需要 `git`、同一安装的 `git-http-backend` 和已固定的
`git-lfs` executable。后续 C3/C8 在 Podman 或 HPC login workspace 内使用 native client
时，相应镜像/登录环境也需要 Git 与 Git LFS client；仅运行计算 payload 的 HPC compute
node 不因为 C1 自动获得 repository service 或 credential。不要把 Host signing key、TLS key
或 Host home mount 进 agent workspace。

## 2. 显式配置

`.env.example` 列出完整 `OPENZYME_REPOSITORY_*` block。整个 block 为空表示 service
未配置；只配置一部分会在 settings load 时直接失败。所有路径必须是绝对路径：

- `OPENZYME_REPOSITORY_BARE_ROOT`：Host-owned bare repositories；
- `OPENZYME_REPOSITORY_LFS_ROOT`：repository-scoped content-addressed LFS objects；
- `OPENZYME_REPOSITORY_BACKUP_ROOT`：restore rehearsal/backup destination；
- `OPENZYME_REPOSITORY_CREDENTIAL_SIGNING_KEY_FILE`：至少 32 bytes、owner-only `0600`；
- `OPENZYME_REPOSITORY_TLS_CERTIFICATE_FILE` / `TLS_PRIVATE_KEY_FILE`：证书必须覆盖
  HTTPS origin hostname，private key 必须是 owner-only `0600`；
- `OPENZYME_REPOSITORY_BINDING_INVENTORY_FILE`：active binding 的 canonical inventory；
- `OPENZYME_REPOSITORY_GIT_EXECUTABLE`、`GIT_LFS_EXECUTABLE`、
  `GIT_HTTP_BACKEND`：固定 executable identity；
- `OPENZYME_REPOSITORY_CREDENTIAL_TTL_SECONDS`：短期 bearer 上限。

本地开发验收使用的已批准布局是：

```text
control plane  /home/grtresy/.local/state/openzyme/control-plane.sqlite3
bare Git       /home/grtresy/.local/share/openzyme/repository-service/git
LFS objects    /home/grtresy/.local/share/openzyme/repository-service/lfs
backup         /home/grtresy/.local/state/openzyme/backups
inventory      /home/grtresy/.local/state/openzyme/repository-bindings.json
signing key    /home/grtresy/.local/state/openzyme/secrets/repository-token.key
TLS            /home/grtresy/.local/state/openzyme/tls/localhost.{crt,key}
HTTPS origin   https://localhost:8443
```

三个 durable roots 必须预先存在、由 Host uid 持有且不向 group/other 开放。它们必须彼此
独立，且不能位于 `/tmp`、`/var/tmp`、当前 Host checkout 或 process cwd 内。startup
preflight 会真实创建、fsync、删除一个 probe 证明可写，不用 mode/owner 静态信息替代
writable proof。control-plane SQLite 文件也必须是 Host uid 持有的普通非 symlink 文件且
mode 精确为 `0600`；新库以 `0600` 创建，已有库权限漂移会直接使 preflight 失败，启动路径
不会代替 operator 静默 chmod。

## 3. Binding bootstrap 与 session pin

binding JSON 是 immutable `project_repository_binding@1`。它同时绑定 project、repository
service id、internal Git/LFS endpoint、upstream identity、object format、default base ref、
exact base commit、namespace policy 与 policy digest。endpoint 必须精确等于：

```text
${OPENZYME_REPOSITORY_HTTPS_ORIGIN}/repositories/{repository_id}.git
${OPENZYME_REPOSITORY_HTTPS_ORIGIN}/repositories/{repository_id}.git/info/lfs
```

用一个已经存在的本地 source repository 导入 exact commit，不会访问 upstream：

```sh
uv run openzyme-repository initialize-binding \
  --database-path /home/grtresy/.local/state/openzyme/control-plane.sqlite3 \
  --binding-file /absolute/path/to/binding.json \
  --source-repository /absolute/path/to/source-checkout \
  --source-commit <exact-commit> \
  --operator-ref operator:local \
  --activated-at <UTC-timestamp>
```

命令创建/验证 bare repository、导入 exact object、把 bare `HEAD` 指向 binding 的
`default_base_ref`，随后在一个 control-plane transaction 内登记并激活 binding。一个
`repository_id` 只能归属一个 project；同一 project 可有多个 immutable binding version。

配置化 Host 创建新 session 时，必须先解析唯一 active version并验证 exact base object，
随后在同一 transaction 写 session 与
`session_repository_binding_pins`。没有 active binding、base 不可读或 Host 未配置 service
均返回稳定 `repository_binding_required`/相关 typed error；不会创建 unpinned session 或
使用 ambient checkout。既有 session 只有通过显式 mapping command 才能从
`repository_binding_required` 变为 `pinned`：

```sh
uv run openzyme-repository map-session \
  --database-path /home/grtresy/.local/state/openzyme/control-plane.sqlite3 \
  --session-id <session-id> \
  --binding-id <binding-id> \
  --binding-version <version> \
  --exact-base-commit <commit> \
  --operator-ref operator:local \
  --mapping-reason '<reason>' \
  --mapped-at <UTC-timestamp> \
  --receipt-id <unique-receipt-id>
```

active version rollover 只影响之后创建的 session；旧 session 永远从自己的 pin 恢复。
session restore、agent workspace、publication、HPC workspace 和 historical migration
prerequisite 共用这一 exact-pin resolver，不能改读 project latest。

## 4. Transport 与 credential 合同

启动前先运行：

```sh
uv run openzyme-repository preflight \
  --database-path /home/grtresy/.local/state/openzyme/control-plane.sqlite3

uv run openzyme-repository serve \
  --database-path /home/grtresy/.local/state/openzyme/control-plane.sqlite3 \
  --bind-host 127.0.0.1
```

preflight 核对 durable roots、inventory、TLS hostname/SAN、signing key、Git/Git LFS/backend
binary digest、active binding、bare repository、object format、exact base、symbolic `HEAD` 与
pre-receive hook digest。任一 drift 都阻止 service startup；没有临时 repository、HTTP、
local-directory 或 upstream fallback。

service 启动后，operator/监控系统还必须经同一 TLS listener读取独立 transport health：

```sh
curl --cacert /home/grtresy/.local/state/openzyme/tls/localhost.crt \
  https://localhost:8443/health
```

该 route 每次重新运行完整 preflight，而不是返回 startup 时缓存的绿色结果。成功响应只包含
`repository_transport_health@1`、Git protocol v2、LFS Batch v2/basic、active binding count、
inventory digest 与 pre-receive hook digest；root、private endpoint、binary/key/certificate path
和 credential 均不投影。preflight 领域识别出的 storage/identity/inventory/configuration drift
返回稳定 `503 repository_service_preflight_failed`；未被领域层归一的 OS、subprocess 或 SSL
fault 继续显式成为 `500`，不会被 transport catch-all 改写。普通 V3
`GET /v3/runtime/health` 只表示 control-plane 对 repository component 的安全投影，不能代替
这个真实 HTTPS transport health。动态 health 证明当前 listener 与 preflight identity；正式
native-client acceptance 另行实际执行 Git v2 与 LFS Batch/basic，health route 不在每次探测时
上传测试对象。

transport 实现标准 Git smart HTTP v2 over HTTPS 与 Git LFS Batch API v2/basic transfer。
Git request 会把 `Git-Protocol` 转成 `HTTP_GIT_PROTOCOL` 交给 `git-http-backend`。agent
credential 只可看见 publication refs 与自己的 private generation；其他 private/historical
refs 由 `uploadpack.hideRefs` 隐藏。pre-receive hook 每次 push 只接受一个 ref，并只允许在
exact `session + agent_member + workspace_generation` namespace create/fast-forward；delete、
non-fast-forward、blob/tree/tag target、cross-agent、publication 和 historical write 均拒绝，
因此 ref 与 terminal retirement receipt 中标记为 commit 的 OID 必须真实解析为 commit object。
Host publication 与
migration historical writer 使用独立内部 owner，不复用 agent bearer；它们分别只允许
publication create 与 historical create/fast-forward，并通过 bare repository 原子 exact-old/new
CAS 更新。C1 只提供该内部 primitive，不提供 C4 publication workflow 或历史迁移编排。

C4 source implementation 现在消费该 primitive：Host 只对 frozen intent 预分配的 exact
publication ref执行 create-if-absent，并在 I/O 前持久化 canonical execution dispatch intent。
response loss只查询同一ref；confirmed/superseded publication ref没有delete或force-update route。
read-only namespace audit只比较canonical `PublishedRevision` 与publication prefix，不扫描或提升
private/historical refs。该源码仍受 `workspace_publication_source_only_dependency_gate@1` 限制，
不改变 C1/C2 receipt 的历史范围，也不授权production remote I/O或live。

C5 source implementation 在同一 endpoint/object root 上加入 immutable binding-scoped LFS policy、
quota reservation/upload session、workspace-generation object links、authoritative read receipts、
stable closure manifest、fresh verification、publication pins 与 receipt-driven GC；没有第二个 LFS
server、custom pointer、generic CAS 或 alternate object source。operator 初始化 binding 时必须同时
提供 closed-schema `--lfs-policy-file`，其 endpoint/version/digest 与 binding 不完全相同则不注册或
激活。preflight 每次重读 exact policy，并只公开阈值、quota、retention 等安全 facts。

Batch upload 先 reserve quota，再由 action header 携带 exact upload-session id；streaming PUT 重算
size/SHA-256、fsync incoming file、no-replace promote，之后才提交 metadata与workspace link。
download 重验 repository-scoped metadata 和实际 bytes 后写 read receipt，不公开 physical path。
published closure 全量 pin；private GC 必须先完成 whole-generation retirement 与 LFS reachability
receipt，再 dry-run、提交 exact candidate digest并整体重验。当前 C5 仍受
`git_lfs_work_product_source_only_dependency_gate@1` 约束：不得把 source snapshot 当成 credential、
upload/publication/GC authority，真实 native Podman/HPC-login、focused/mainline 与最终 receipt 均延后到
14 个 change 的统一验收。

`RepositoryCredentialBroker` 的 production path 不接受 caller 构造的
`ActiveCapabilityLeaseAssertion`。调用方只提交 lease id 与 expected
session/member/generation/service/target/protocol facts，broker 通过 canonical
`ActiveAgentCapabilityLeaseValidator` 或等价 typed port 在同一 `BEGIN IMMEDIATE`
transaction 中重读 active lease、immutable session pin、private namespace/hold，并写
credential issuance record。任一 identity/profile/target/policy/retirement request/final record
漂移整体 rollback；
只有 transaction commit 后才可把 bearer 返回调用进程。

credential 绑定 binding id/version、repository、session、agent member、workspace
generation、lease id、audience/protocol 和 ref classes。C2 中 token 只在签发响应中短暂
存在，数据库仅保存 digest/claims；不得写入 persistent workspace/volume、Git repository
config、public projection、logs 或 Host home。C2 冻结 process-scoped derivation 的 typed
audience/claims seam，但不声称已经实现由 C3 拥有的真实 capsule process injection。Git/LFS
read 与 write authentication 每次都重读 canonical active lease。write scope 还要求 exact private
namespace 为 `open`，并存在 owner ref 等于 lease id 的未释放
`active_capability_lease` hold。

durable `AgentRetirementRequest` commit 后，同一 exact member 即使 lease row 尚为 `active`，
broker issuance、Git/LFS authentication-time lease validation与新的 capability hold也必须失败；
raw SQL trigger 同样拒绝新 issuance/hold。request前既有 credential/hold由最终 member-wide revoke
transaction统一撤销/释放，不能靠 TTL 或调用方缓存继续授权。

lease revoke transaction 必须在同一笔写入中停止新 issuance、撤销可撤销的 derived
credentials、释放 matching holds、写 lease 终态与 lifecycle event。提交后，旧 bearer
即使 TTL 未过也必须在 read/write authentication 失败。credential TTL 只结束该
credential，不结束 lease；后续显式动作可在同一 active lease 下重签一枚新的短期
credential，但 Host 不自动续签、重放失败命令、换 endpoint 或换 binding。

C1 的 `operator/run_local_protocol_acceptance.py` 仅用于一次性历史验收：它用
显式 `c1_acceptance_only` lease assertion与临时 active-lease hold完成 native client 测试，
随后立即撤销 credential并释放 hold，并在 receipt 中写明
`production_capability_lease_issuance_proven=false`。这些 row/receipt 只保留为不可升级的
audit fact，不是产品发证 CLI，不能借它们跳过 C2 canonical validator。

## 5. Audit、activation、retirement 与恢复

read-only audit 使用 SQLite `mode=ro` 和 `PRAGMA query_only=ON`，不会触发 migration：

```sh
uv run openzyme-repository audit \
  --database-path /home/grtresy/.local/state/openzyme/control-plane.sqlite3 \
  --binding-id <binding-id>
```

新增 version 先由受控 bootstrap/import 登记，再通过 `activate-binding` 切换 active pointer。
`retire-binding` 只接受不再是 active、且没有 session pin、mapping receipt、credential record
或 private namespace reference 的 version；先生成 immutable reference-audit receipt，再写
retired lifecycle event。被引用的旧 version、Git refs 与 LFS objects 必须保留。

`rehearse-restore` 用 SQLite backup API 和 regular-file-only tree copy创建 snapshot，再从副本
构造全新的 provider/root manager，重跑 preflight，并要求 binding、bare refs、LFS objects、
session pins、credential/ACL identity 与 retention rows 的 canonical state完全相等：

```sh
uv run openzyme-repository rehearse-restore \
  --database-path /home/grtresy/.local/state/openzyme/control-plane.sqlite3 \
  --receipt-id <unique-receipt-id> \
  --created-at <UTC-timestamp> \
  --operator-ref operator:local
```

本地 C1 演练中 Git、LFS、backup 的 `st_dev` 均为 `65024`，因此 receipt 明确记录
`failure_domain_separated=false` 与 `production_disaster_recovery_proven=false`。该证据只证明
process/provider reconstruction 和同文件系统逻辑恢复；生产部署仍须把备份放到独立 failure
domain，并另行验证 RPO/RTO、host/filesystem loss 与 offsite restore。

## 6. 当前 C1/C2 验收边界

C1 已证明 binding persistence、new-session exact pin、native HTTPS Git v2、private ref ACL、
Git LFS upload/download、credential revoke、process restart 和本地 logical restore。它没有：

- 创建 Podman/HPC agent worktree（C3/C8）；
- 建立 publish/sync revision（C4）；
- 把 large work product policy切到 Git LFS（C5）；
- 独立证明 C2 canonical production capability lease issuance；
- 访问或改变 GitHub upstream；
- 证明跨 filesystem/host 的 production disaster recovery。

这些缺口必须保持可见，不能用临时目录、ambient checkout、测试 credential 或成功的本地
rehearsal伪装为后继 change 已完成。

C2 的独立 acceptance 只能证明 exact-generation lease lifecycle、canonical repository
credential issuance/authentication/revocation seam 与相应 non-runnable admission gate。C2 需要显式记录下列
false claims：

- production independent Git workspace/capsule 未证明；
- native toolchain、ordinary network（C3 deployment 不使用 Host destination allowlist）与
  upload/download execution 未证明；
- publication/shared revision 未证明；
- remote HPC credential/workspace CRUD、approval-free ordinary job 与 one-occurrence `sbatch`
  未证明。

C2 不改变旧 Host-supervised execution/AOX sandbox 的无网络语义，也不能在 lease
missing/pending/revoked 时使用该执行面作为 fallback。C3 readiness 未出现前，正确的
production 状态是 `provisioning_required` 与 non-runnable。
