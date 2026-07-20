# Session 09：Sandbox File / Command Runtime

## 目标

为 executor 提供可审计的 sandbox 文件 CRUD 与唯一执行入口 `sandbox.exec`。agent 可以在自己的 persistent sandbox workspace 内写脚本、运行 Python/bash、检查中间文件和修复错误；代码运行中触发的受控 SDK 外部能力必须只能通过 Host supervisor RPC transport 进入后续受控路径，不能绕过 Host 直接访问 provider、local tool 或 HPC runner。完整 approval 阻塞/恢复语义由 Session 10 实现和验收。

## 当前缺口

- 一次性 pipeline 模型下，agent 只能提交整段代码，难以逐步检查中间文件。
- 只开放 `sandbox.exec` 会诱导 LLM 用 shell heredoc 或重定向写文件，审计差且容易出错。
- 如果命令输出、退出码、日志和文件变化不被结构化记录，persistent sandbox workspace 会变成隐藏状态。
- 如果 `sandbox.exec` 运行中的代码可以绕过 Host approval 直接访问 provider、local tool 或 HPC runner，就会重新引入隐藏高风险执行。

## 实施范围

- 新增 executor-facing tool surface：
  - `sandbox.file.list(path="/workspace", recursive=false)`
  - `sandbox.file.read(path, offset=0, limit=65536)`
  - `sandbox.file.write(path, content, create_dirs=false, expected_digest=None)`
  - `sandbox.file.patch(path, base_digest, patch)`
  - `sandbox.file.delete(path, expected_digest=None)`
  - `sandbox.exec(argv, cwd="/workspace", timeout_seconds=120, env=None)`
- 文件工具只允许操作 `/workspace/src`、`/workspace/work`、`/workspace/output` 和必要的 `/workspace/logs`；默认不允许写 `/workspace/input`。
- `sandbox.exec` 是 executor-facing 唯一执行工具，支持 `bash`、`python` 和预装实用工具，但仍运行在 sandbox 网络、用户、CPU/memory/time 限制内。
- `sandbox.exec` 允许代码导入并调用 `openzyme_pipeline` SDK；任何 provider、local tool、HPC runner、高 quota 或长耗时 operation 都必须经 Host supervisor RPC transport 拦截，不能在 sandbox 内直接执行。
- 本 session 验收 s07 base image 的交互能力：`bash` 可执行、`python` 可执行、`openzyme_pipeline` 可 import、SDK supervisor RPC transport 能连到 Host 并返回 bounded structured response。base image 的 image ref/digest 归属和版本锁定仍属于 s07。
- 实施本 session 前必须由 operator 明确 sandbox lightweight dependency allowlist。Session 06 的 sandbox image recommendations 只是候选输入，不自动成为默认依赖。该 allowlist 只覆盖 sandbox 内 Python/bash 派生处理、解析、过滤、评分、CSV/FASTA/HMM/JSON 轻量读写所需依赖；不能包含 MAFFT、CD-HIT、HMMER、Apptainer、SSH/Slurm client、runner config、provider credential、database mount 或任何领域 backend packaging。若 operator 未确认，默认只验收标准库、`bash`、`python` 和 `openzyme_pipeline`，不自动安装额外 Python 包。
- 已确认 allowlist 必须写入 S07 sandbox image manifest，至少记录依赖名、版本或 lock digest、用途边界和 import smoke；manifest 缺失、版本不匹配或依赖能力不兼容时按 S07 image compatibility fail-closed，不能 runtime auto install、自动换镜像或 fallback 到旧 pipeline runner。
- S09 的 SDK supervisor RPC smoke 只证明 transport、身份绑定、path/secret 隔离和结构化错误返回；generic operation digest、approval request、`waiting_approval`、pause/resume、route freezing 和 recovery 由 S10 实现。
- S09 control socket 使用一连接一帧的 JSON-RPC 2.0 NDJSON：request/response payload 最大 `4 MiB`（不含终止 newline），receiver 跨 `64 KiB` `recv` chunk 聚合直到 newline，不能把 chunk size 解释为 frame cap。非 null request id 只允许 UTF-8 编码 `<=256` bytes 的 string 或 signed int64（bool 非法）；request 其他 semantic validation 失败时 error 回显已提取的 safe id，id 自身超限/非法或无法提取时返回 `id=null`。EOF 前没有 newline、畸形 UTF-8/JSON、duplicate object key、`NaN`/`Infinity`、非 object request/response、response id/schema 漂移和任一方向超限均返回或抛出 bounded structured transport error，不 dispatch 畸形 request，也不 fallback/replay；SDK request与Host response serializer也固定`allow_nan=false`。硬保证是每个 connection 最多执行一个 request：若receiver在首个newline后已经观察到非whitespace trailing bytes，则在dispatch前结构化拒绝；若第二帧只在首帧已接受后才晚到，它只能遇到connection关闭，协议不保证为第二帧再返回一个error，但绝不能执行第二个method。Host/compat request receiver、SDK connect/send 与首个response byte之后的SDK read均有固定5秒I/O timeout；等待首个response byte由外层sandbox run及approval/controlled-operation生命周期约束，因为同一RPC可合法暂停等待人工approval或同步provider/HPC完成。首字节到达后peer仍不结束newline的partial response稳定返回non-retryable `sandbox_transport_response_timeout`。单连接 read/decode/send/client-disconnect 失败必须与 accept worker 隔离；Host response 超限时返回小型结构化错误，SDK 在发送前检查 request size 并以同一上限读取 response。该小修沿用既有 protocol/image version，不新增 durable state。
- artifact metadata sidecar是SDK在组装frame前的serialization策略，不改变上述4 MiB hard cap。logical path固定为`/workspace/work/.openzyme/artifact-metadata/<digest>.json`；local backend由harness在合并user env后强制覆盖`OPENZYME_SANDBOX_WORK_ROOT`到当前physical work root，container固定`/workspace/work`，agent不能重定向到Host path。Host以fd-anchored/no-follow read在effect前验证，失败不触发replay/fallback。core与active兼容Podman control server都跨64 KiB chunk读取到newline；兼容server同样在dispatch前验证JSON-RPC、safe id和object params，以bounded I/O timeout回收partial frame，并对替换后的oversized-response error再次实施cap。兼容runner只能返回`pipeline_provisional_registration_response@1(canonical=false)`，不能冒充durable `artifact_registration_response@2`。该correction改变pipeline SDK digest，但不升级sandbox protocol/image version。
- Host 必须在每次 `sandbox.exec` 启动命令前调用 S08 source snapshot service，自动创建或绑定覆盖整个 `/workspace/src` 的 CODE artifact；snapshot 失败时命令不启动，不能映射成普通非零退出。
- 在 source snapshot、`SandboxRun` 创建和 container process invocation 之前，Host 必须验证 configured workspace root 下 `src/input/work/output/logs/manifest` 六个 bind source 都是已存在的真实非 symlink 目录；任一缺失或类型异常返回 `sandbox_volume_corrupt`，不得在 exec 路径补空目录、创建 snapshot/run 或把底层 Host `statfs` 路径交给 agent。
- executor 不创建 approval、不调用 resume、不判断敏感性；在 S09 中它只处理命令成功、结构化 transport error 或非零退出后的普通编程结果。
- 命令执行结果返回 bounded stdout/stderr、exit code、duration、changed file summary、log artifact ref（超限时）和 structured error。
- `sandbox.exec` 不允许直接传 Host path、SSH/Slurm command、container runtime command、provider credential、runner config 或任意外部 secret。
- 文件写/patch/delete 必须记录 audit entry：actor、task、`sandbox_workspace_id`、path、old/new digest、timestamp。
- 大文件读取必须分页；二进制文件只能返回 digest、size、mime/format summary。
- 同一 `sandbox_workspace_id` 同时只允许一个 active `sandbox.exec`。`list/read` 可并发；agent-facing `write/patch/delete` 在 active exec 期间默认返回 conflict，避免与运行中进程产生不可审计的竞态。

## V1 Tool API Defaults

S09 的 tool API 仍固定为 v1 机械默认值，不能留给实现者临场选择；具体资源策略通过独立的 `exec_policy_version` 演进，因此 `s09.exec_policy.v2` 不表示 tool API 升版：

- `sandbox.file.patch.patch` 只接受 unified diff 文本，path 必须与 tool 参数 `path` 指向同一文件；不接受 arbitrary Python patcher、shell command、JSON patch 或多文件 patch。
- `sandbox.file.write.content` 只接受 UTF-8 文本，单次写入上限 `256KiB`；二进制和更大内容必须走 artifact materialize/register/upload 或 sandbox 内生成文件。
- `sandbox.file.read.limit` 默认 `64KiB`，最大 `256KiB`；超过范围返回 `sandbox_read_limit_exceeded`，二进制只返回 digest、size、mime/format summary。
- `sandbox.file.list` 默认非递归；递归结果最多 `1000` 项，超出时返回 truncated summary 和 `sandbox_listing_truncated` warning。
- `sandbox.exec.timeout_seconds` 默认 `120`，`s09.exec_policy.v2` 的有限上限为 `3600`；CPU 默认 `2`、memory 默认 `2GiB`、pids 默认 `256`，超过 Host policy 返回 `sandbox_resource_exceeded`。上限扩大只为容纳 Host-supervised、可能等待真实长 provider 的命令；它不改变单 workspace 单 active exec、container retirement、无网络或资源隔离，也不授权 agent 无目的延长普通命令。
- `sandbox.exec.env` 只能包含 allowlist key：`PYTHONPATH`、`OPENZYME_*` sandbox-safe SDK vars 和 task-scoped non-secret variables；任何 credential-like key、PATH override、LD_PRELOAD、SSH/Slurm/provider secret 都返回 `sandbox_env_forbidden`。
- stdout/stderr inline summary 各最多 `32KiB`；超过时写 `CommandLogArtifact`，result 只返回截断摘要、digest、size 和 log artifact ref。
- bounded stdout/stderr 与 exception summary 在写 run/workspace/tool result 前先经过 public diagnostic sanitizer：精确 workspace/control-socket Host location 只在 schema-declared field 中映射为逻辑 sandbox path，随后对已测试的 high-risk Unix/HPC、Windows、UNC、file URI、private URL/locator 与 credential corpus递归脱敏；不声称识别任意自由文本中的所有 private path。进程 stdio 以 binary capture，public summary 使用 UTF-8 replacement decode 后再脱敏；raw digest/size按捕获的原始 bytes计算，完整超限 payload仅写 attempt-local Host-private log。

## File / Command Semantics

- `sandbox.file.write` 使用 Host-managed atomic temp-write + rename；`create_dirs=false` 时父目录不存在返回结构化错误，`create_dirs=true` 也只能在允许 root 下创建目录。`expected_digest` 非空且不匹配时返回 `sandbox_digest_conflict`，不写成功 audit。
- `sandbox.file.patch` 只能修改 tool 参数 `path` 指向的单个普通文件。unified diff 中的 old/new path 必须规范化后与参数 path 相同；不允许多文件 patch、创建/删除其它文件、修改 symlink、执行外部 patch command 或使用 JSON/Python patcher。
- `sandbox.file.delete` 只删除允许 root 下的普通文件；不允许删除 workspace 根、`/workspace/src|work|output|logs` 目录根、`/workspace/input`、symlink escape 或目录树。需要删除目录树时必须由后续单独设计定义。
- `sandbox.file.list/read/write/patch/delete` 的 path 先做 public `/workspace` 规范化，再解析到 Host-owned workspace volume；任一 `..`、Host absolute path、sandbox host path、symlink traversal 或 `/openzyme/*` 长期路径都返回结构化错误。旧 `/openzyme/*` 只能作为实现兼容视图，不能进入 S09 agent-facing contract。
- active `sandbox.exec` 期间，agent-facing `write/patch/delete` 返回 `sandbox_run_conflict`；`read/list` 可并发，但只返回安全摘要或分页内容，不更新 workspace manifest、audit success entry 或 run state。
- `sandbox.exec` 的 `argv` 必须是非空数组；`cwd` 必须在 `/workspace` 下并默认 `/workspace`。需要 shell 时只能显式传 `["bash", "-lc", "..."]`，Host policy 仍需拒绝 Host path、credential、SSH/Slurm/container runtime command、network escape 和 provider secret。
- Host 在命令前记录 run pre-state digest summary，命令后扫描 bounded changed file summary。命令产生的文件变化归档到 `SandboxRun`，不伪造成 agent file tool audit entry；正式共享输出仍必须通过 S08 `artifacts.register(...)` 登记。

## 接口变化

- `sandbox.exec` 的输入固定为 argv 数组，不接受 raw shell string；需要 shell 时显式 `argv=["bash", "-lc", "..."]`，并经过 policy 检查。
- `sandbox.file.write` 支持小文本内容；大型内容应由 materialize、register、upload 或 generated file 流程处理。
- `sandbox.exec` result 增加 Host-supervised execution metadata：`sandbox_run_id`、`sandbox_workspace_id`、`source_snapshot_artifact_id`、`source_tree_digest`、`sdk_transport_call_ids`、`status`、`error_code`。如果 `/workspace/src` 为空、不可读或 snapshot commit 失败，命令 fail-closed，不启动进程，并返回 S08 source snapshot 错误码。
- `waiting_approval` 不是 S09 的验收对象；approval resolve 后恢复同一个等待中的 SDK operation 的语义由 S10 锁定。
- workspace projection 可展示最近命令摘要和文件变化摘要，但不展示完整 stdout/stderr 或大文件内容。最小字段为 `sandbox_run_id`、`status`、`argv_digest`、`cwd`、`started_at`、`ended_at`、`duration_ms`、`exit_code`、`error_code`、`source_snapshot_artifact_id`、`changed_files_summary`、`stdout_summary`、`stderr_summary` 和 `log_artifact_ref`；projection 不暴露 Host path、sandbox host path、control socket path、private storage URI 或完整日志。
- projection 必须对 workspace/run 的全部字符串与嵌套 diagnostic payload 再次递归脱敏，以保护 sanitizer 落地前形成的历史 SQLite 行；该读取侧防御不能替代写入边界，也不能削弱 verifier 对 public Host path 的拒绝。
- S09 transport smoke 使用 Host-internal fake supervised transport call，不新增或锁定 public SDK module/function 名称。smoke request/response 只需包含 `sandbox_workspace_id`、`sandbox_run_id`、`source_snapshot_artifact_id`、artifact read summary、call identity、bounded result 或 structured error。

## Resource Identity / Lifecycle

本 session 锁定三类 Host-owned 资源对象：`SandboxRun`、`FileAuditEntry` 和 `CommandLogArtifact`。

- `SandboxRun`
  - identity：`sandbox_run_id` 由 Host 创建，绑定 `sandbox_workspace_id`、agent id、task/lane focus、argv digest、cwd、env digest、source snapshot id 和 source tree digest。
  - owner：Host sandbox runtime service 创建、claim、更新状态和结束；executor 只能请求 `sandbox.exec`。
  - lifecycle：`queued -> running -> completed|failed|timeout|resource_exceeded|cancelled`；同一 workspace 单活执行，active run 未结束时新 exec 返回 `sandbox_run_conflict`。
  - persistence：run record、bounded stdout/stderr summary、exit code、duration、changed file summary、log refs 和 error code 持久化；container process id 不是 canonical state。
  - timeout：Host 必须终止进程树；已产生或残留的 changed files 进入 failed run summary，不自动 rollback。
  - recovery：Host 重启、worker lease 过期、container/process 状态丢失或 active lock stale 时采用 fail-closed；若无法安全证明原命令仍由同一 run 可审计地继续，就把 run 标记为 `failed`，错误为 `sandbox_run_recovery_failed`，释放 active lock，保留日志/诊断摘要，并唤醒 executor 读取失败后重新运行。
  - cancel：`cancelled` 只能由 Host-owned explicit cancel 或 recovery cleanup 写入；cancel 必须终止进程树、记录 actor/reason/timestamp 和 changed file summary。executor 不能通过普通 file/exec tool 伪造 cancel state。
  - compatibility/versioning：run 绑定 S07 image digest、sandbox protocol version、workspace manifest version、S08 source snapshot schema 和 S09 exec policy version；任一不兼容时命令不启动，返回结构化 compatibility error。
  - fallback policy：禁止因 image、snapshot、policy、resource、transport 或 command failure 自动 fallback 到 `execution.pipeline.start`、Host local runner、网络 provider、HPC runner、旧 `/openzyme/*` pipeline path 或 synthetic/fixture substitution。
- `FileAuditEntry`
  - identity：Host append-only audit id，记录 actor、task/lane focus、`sandbox_workspace_id`、operation、path、old digest、new digest、timestamp。
  - owner：Host file tool service 写入；sandbox 进程自身产生的文件变化由 run changed-file scan 归档，不伪造成 agent file tool call。
  - lifecycle：write/patch/delete 成功后持久化；digest conflict、path forbidden 或 active exec conflict 不写成功 audit，只写失败 event。
  - persistence：audit entry 是 append-only canonical record；后续 workspace cleanup 不删除已持久化 audit，public projection 只展示 bounded summary。
- `CommandLogArtifact`
  - identity：stdout/stderr 的 public summary 超限时由 Host 创建 private log metadata 与 `sandbox-log://...` opaque ref；它不是 artifact catalog 中可下载的 Artifact，该 ref 不授予读取 authority。
  - owner：Host runtime/log service在 attempt-local private command-log root中保留完整 raw bytes；per-run directory以 no-replace `0700` 创建，stream file以 no-follow/exclusive `0600` 创建并 fsync。public result只返回 sanitized bounded summary、raw-byte digest/size、truncation marker与opaque ref。
  - lifecycle：随 `SandboxRun` 保留；retention 由 Host workspace/log policy 管理，不能把完整日志塞进 RPC 或 projection。cleanup 只能清理超过 policy 的 private raw payload，不能删除 run record 中的 digest、size、truncation marker 或 opaque ref。

固定错误码：

- `sandbox_run_conflict`
- `sandbox_run_recovery_failed`
- `sandbox_exec_cancelled`
- `sandbox_exec_timeout`
- `sandbox_exec_nonzero`
- `sandbox_resource_exceeded`
- `sandbox_path_forbidden`
- `sandbox_digest_conflict`
- `sandbox_patch_failed`
- `sandbox_log_truncated`
- `sandbox_read_limit_exceeded`
- `sandbox_listing_truncated`
- `sandbox_env_forbidden`
- `sandbox_transport_unavailable`
- `sandbox_transport_request_timeout`
- `sandbox_transport_request_invalid`
- `sandbox_transport_request_too_large`
- `sandbox_transport_response_invalid`
- `sandbox_transport_response_timeout`
- `sandbox_transport_response_too_large`
- `sandbox_transport_method_forbidden`
- `sandbox_workspace_not_found`
- `sandbox_workspace_forbidden`
- `sandbox_image_missing`
- `sandbox_image_incompatible`
- `source_snapshot_empty`
- `source_snapshot_required`
- `source_snapshot_failed`
- `source_snapshot_unavailable`

## 建议实施顺序

1. Schema / repository foundation
   - 增加 `SandboxRun`、`FileAuditEntry`、`CommandLogArtifact` 和 per-`sandbox_workspace_id` active run lock 的持久化模型；run lock 必须能在 Host 重启后按 fail-closed recovery 释放或归档。
   - run record 必须能保存 source snapshot id、source tree digest、argv/env digest、resource policy、bounded stdout/stderr、log refs、changed file summary、status 和 error code。
2. File service
   - 先实现 shared path normalization、symlink escape 检查、digest helpers、atomic write、single-file unified diff patch 和 delete guard。
   - 成功 write/patch/delete 后写 append-only audit；失败只写事件或 tool error，不写成功 audit。
3. Exec service
   - 在启动进程前检查 context-root continuity、六目录非 symlink 完整布局、workspace/image compatibility、active run lock、argv/env/cwd/resource policy；布局失败先于 S08 source snapshot、run record 与 process invocation。
   - 启动后由 Host-owned sandbox runtime service 管理 process tree、timeout、resource limit、stdout/stderr capture、log artifactization、changed file scan 和 fail-closed recovery。
4. Tool / projection integration
   - 将 `sandbox.file.*` 与 `sandbox.exec` 注册为 executor-facing tools；handler 只做参数转发和结构化错误包装，不能在 handler 内重复 path/security/run-state 逻辑。
   - workspace projection 只消费 canonical run/audit/log records，返回 bounded summaries 和 artifact refs。
5. Smoke and docs follow-up
   - 增加 S09 fake supervised transport smoke，验证 control socket/RPC、identity binding、source snapshot binding、artifact read summary 和 structured error；同时用跨多个 `recv` chunk、但小于 `4 MiB` 的真实 Unix-socket request/response 验证完整 frame，并证明 malformed/incomplete/oversized connection 不杀死下一连接，不提前创建 S10 `ControlledOperation` 或 approval。
   - 本次计划不直接修改 `docs/v3/execution-pipeline-docs/`。后续实现若改变 user-facing SDK docs、sandbox rules 或 examples，应在实现 PR 中同步对应 execution-pipeline docs。

## 测试/验收

- executor 能通过 file tools 创建脚本、patch 脚本、运行 `python`、读取输出摘要。
- `sandbox.file.write` atomic write、`create_dirs`、UTF-8 上限和 `expected_digest` conflict 均有覆盖；失败不产生成功 audit。
- `sandbox.file.patch` 拒绝多文件 patch、path 不匹配、symlink、digest mismatch 和不能干净应用的 diff。
- `sandbox.file.delete` 拒绝 workspace 根、目录根、`/workspace/input`、symlink escape、目录树删除和 digest mismatch。
- executor sandbox base image 中的 `bash`、`python` 和 `openzyme_pipeline` import 与 Host supervisor RPC transport smoke 通过；失败返回结构化 command/runtime 错误，不能回退到 `execution.pipeline.start`。
- 若 operator 在实施前确认了 sandbox lightweight dependency allowlist，base image manifest 必须记录依赖名、版本/lock digest 和用途边界，并补充 import smoke；未确认 allowlist 时，不得把未声明依赖作为验收前提。
- 执行代码触发 fake supervised SDK transport smoke 时，Host 能识别 `sandbox_workspace_id`、`sandbox_run_id`、source snapshot artifact id / digest、artifact read summary 和 call identity，并返回 bounded structured response；真实 approval card、operation digest、`waiting_approval`、approve/reject continuation 和 route freezing 由 S10 测试。
- 大于 `64 KiB` 但不超过 `4 MiB` 的合法 request/response 必须跨 chunk 完整往返；恰好超出 `4 MiB`、缺 newline、partial response保持连接至timeout、畸形 JSON、已观察到的newline后非空trailing bytes或 response identity 不匹配必须以对应稳定 transport error fail closed，且随后新连接仍可成功。late second-frame test只要求同一connection绝不执行第二个request，允许client只观察到connection close而没有第二个error。focused tests 还必须覆盖 256-byte string/id64 边界、safe id 在其他 invalid semantics 下回显、oversized/invalid id 返回 null。SDK oversized request 必须在 connect/send 前拒绝，Host oversized response 必须缩减为结构化 error。
- 真实Unix socket还必须覆盖：64–256 KiB inline metadata跨chunk完整到达；超过4 MiB、`<=32 MiB`的logical metadata通过descriptor使physical request仍低于4 MiB，Host保存完整object且direct response有界；tampered sidecar在Artifact seal/row前失败。local与compat Podman路径均需覆盖，后者response保持provisional/noncanonical，并证明missing JSON-RPC、unsafe id和partial-frame timeout在effect前失败且下一连接仍可服务。
- source snapshot 为空、不可读、digest 失败或 commit 失败时，`sandbox.exec` 不启动进程，返回 `source_snapshot_empty`、`source_snapshot_required`、`source_snapshot_failed` 或 `source_snapshot_unavailable`。
- `sandbox.exec` 超时、非零退出、stdout/stderr 超限、资源超限都返回结构化错误并保留日志 ref。
- Host 重启、stale active run lock、worker lease conflict 或 process state 丢失时，普通 `sandbox.exec` fail-closed 为 `sandbox_run_recovery_failed`，释放 active lock，保留诊断，并允许 executor 显式重新运行。
- Host explicit cancel 终止进程树并返回 `sandbox_exec_cancelled`；cancel 不能被 executor 普通 tool call 伪造。
- file patch 只接受 unified diff；digest 不匹配、多文件 patch、路径逃逸或 patch 不能干净应用时返回结构化错误，且不写成功 audit。
- read/list/write/exec 的 size、timeout、resource 和 env 默认值按 V1 Tool API Defaults 验收，不能依赖实现者自选 cap。
- 文件工具拒绝路径逃逸、symlink escape、写 input、删除 workspace 根目录、覆盖 digest 不匹配文件。
- 同一 workspace active exec 期间第二个 exec 和 agent-facing write/patch/delete 返回 `sandbox_run_conflict`；read/list 不改变 workspace 状态且可并发。
- 命令不能直接访问网络、Host repo、`.ssh`、runner config 或 provider secret；外部访问只能通过 Host-supervised SDK operation。
- audit log 能回链到 task、agent、workspace、命令和 source snapshot。
- workspace projection 只展示 bounded command/file summaries、log artifact ref、source snapshot id 和 error code；不暴露完整 stdout/stderr、Host path、sandbox host path、control socket path、runner path 或 private storage URI。

## 明确不做什么

- 不暴露 agent-facing `execution.pipeline.start`、`execution.plan.create` 或 `execution.run.start`。
- 不让 `sandbox.exec` 直接调用 SSH、Slurm、Host local Apptainer、runner config 或 provider credential；HPC/local/provider 能力只能通过 Host-supervised SDK operation。
- 不在未获 operator 明确确认时预装或依赖 `biopython`、`pandas`、`numpy` 等额外 Python 包；这些只能作为实施前确认的 lightweight dependency allowlist 进入 sandbox image contract。
- 不把命令成功当作 task completed。
- 不通过后台 scheduler 自动重跑失败命令或自动改写执行策略。
