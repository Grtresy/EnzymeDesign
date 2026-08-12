## ADDED Requirements

### Requirement: Machine-verifiable blank-world roots
Each cutover attempt SHALL create unique empty SQLite, artifact/blob, sandbox workspace, and HPC workspace roots and SHALL prove that no scientific output, prior session state, or provider cache payload was accepted as current live evidence. Immutable code, configured image/toolchain, credential availability without credential values, workflow pack, and user-supplied accession inputs SHALL be recorded as allowed prerequisites.

#### Scenario: Start a clean attempt
- **WHEN** a campaign launches a positive or fault-injection attempt
- **THEN** it records unique root identities, verifies their pre-run emptiness, enables cache bypass for evidence-bearing provider calls, and seals a configuration snapshot

#### Scenario: Detect preloaded scientific data
- **WHEN** an attempt root already contains an AOX FASTA, HMM, hit table, report, artifact record, or prior evidence digest
- **THEN** the attempt fails blank-world validation before invoking a provider or runner

#### Scenario: Keep one attempt-scoped sandbox root and fail closed on layout drift
- **WHEN** workspace status, explicit or implicit workspace lookup, file/exec, source snapshot, and container bind resolve a cutover workspace; a workspace has no canonical row but its derived leaf already exists; or an existing workspace is missing any required `src/input/work/output/logs/manifest` real directory
- **THEN** every component uses the same Host-injected attempt root and enforces current executor ownership; a new leaf is created only with no-replace/exclusive semantics, while any preexisting directory/file/symlink, incomplete layout, non-directory, or symlinked required entry returns `sandbox_volume_corrupt` before snapshot, run creation, process, provider, or runner activity and is never adopted, modified, or silently repaired as an empty READY workspace

#### Scenario: Keep public failure evidence path-safe
- **WHEN** sandbox, adapter, provider, scheduler, or harness diagnostics contain embedded private paths, locators, or credentials
- **THEN** durable/public summaries map only exact context-provided sandbox/control-socket locations to logical paths, sanitize the documented and tested high-risk Unix/HPC-root, Windows-drive, UNC, file-URI, private/special-use URL, locator, and credential corpus in schema-declared diagnostic fields before public or canonical persistence, project historical structured locators/diagnostics again, and retain the independent strict offline rejection of any surviving absolute Host path/private locator; the producer sanitizer does not claim to recognize every arbitrary private path in free text and does not rewrite user/scientific/report content
- **AND** process stdout/stderr is captured as bytes; complete over-limit stdio MAY persist only in the attempt-scoped Host-private command-log boundary, whose run directory and stream file use no-replace/no-follow private `0700`/`0600` creation, while public records retain only a sanitized summary, raw-byte digest/size, truncation marker, and opaque ref without read authority

### Requirement: Canonical launch and prerequisite identity
The retained preflight and authority-consumption shell SHALL resolve a canonical clean launch snapshot before a separately approved public Codex conductor creates any attempt root. The launch identity MUST be the exact seven-field closed object `git_commit`, `config_digest`, `workflow_ref`, `scoring_contract_digest`, `scoring_implementation_digest`, `image_digest`, and `sdk_digest`; each value MUST be derived from the actual clean canonical checkout, digest-pinned workflow/scoring implementation, sandbox runtime preflight, and Pipeline SDK source tree rather than trusted from caller declarations. No retained shell SHALL construct or automatically drive an attempt runner or campaign.

Every initial identity resolution and inter-attempt launch guard SHALL execute `aox_sandbox_scientific_backend_probe@2` before pin runner attestation, attempt-root creation, or any MICU/provider/runner effect. The probe MUST copy the exact Pipeline SDK to a temporary tree, normalize directory/file modes to `0755`/`0644`, recompute and match its source-tree digest, and mount it read-only into the selected immutable image under no-pull, no-network, bounded CPU/memory/pids execution. It MUST run the real `biopython_trace_guarded_numpy_gotoh@1` import, exact Biopython `1.87` and NumPy `2.4.4` checks, Gotoh configuration, IEEE-754 binary64 verification, frozen numeric examples, and the closed installed `aox_exact_calculation_manifest@1`, returning only the exact canonical closed `aox_sandbox_scientific_backend_probe@2` projection. Missing dependencies, nonzero exit, timeout, image/SDK mismatch, version/algorithm/numeric/manifest drift, or malformed/open/noncanonical projection MUST fail launch without runtime installation, Host-package substitution, or alternate backend. This gate MUST NOT expand the exact-seven identity or exact-nine prerequisite object and MUST NOT be represented as a reproducible dependency manifest, SBOM, or supply-chain attestation.

`config_digest` MUST be the canonical digest of a sealed safe `aox_blank_world_runtime_config@5` preimage covering the effective trusted-Host/single-process-SQLite profile, HPC runner-config digest, runner-owned manifest bytes digest, the closed exact-AOX tool-to-adapter/template/runner-contract expectation map, provider limits, MICU model/policy/bounds, research/tracing/test opt-ins, the complete reliability projection that determines controlled-operation ownership/durable route admission/command drain/generic mutation closure, and the exact active `aox_blank_world_selected_chain@2` schema/contract/workflow/digest identity. Current `@5` MUST NOT contain a `conductor` or `driver` policy object, public-command/receipt/supervision claims, or any `automatic_*` orchestration flag; those operator, source, evidence, authority and MICU-ledger facts MUST remain in their owning launch, preflight, public-receipt, supervision and budget evidence. The absence of automatic orchestration MUST be proved by production reachability and static qualification rather than sealed booleans. The selected-chain digest MUST cover the complete formal/fault/probe role-to-SDK-operation-signature mapping used by admission, inspection/readiness, validation, and the bundle verifier. The reliability projection MUST prove `durable_async_v1` ownership for every AOX provider/HPC route, `command_v1`, and `generic_v1` before pin contacts the runner or a public conductor creates an attempt root. Frozen `aox_blank_world_runtime_config@1`, `aox_blank_world_runtime_config@2`, `aox_blank_world_runtime_config@3`, and `aox_blank_world_runtime_config@4` evidence MAY remain readable only for historical offline verification; none MAY be emitted or admitted for a new launch, silently promoted, or used to restore driver/conductor shadow truth. Summary, reservation and campaign startup MUST NOT reinterpret a stored ceiling. An explicit operator migration MAY change only the exact legacy fixed 100M policy to 500M transactionally; it MUST preserve all prior usage, be idempotent at 500M, reject any other stored limit, and never reset the ledger. The preimage MUST NOT expose credentials, NCBI email, Host/runner/ledger paths or conductor-owned state. Binding the runner map and selected-chain identity MUST NOT add a tenth prerequisite field.

Blank-world live against MICU or another OpenAI-compatible endpoint MUST explicitly configure `context_window_tokens` no greater than `200000`; it MUST NOT infer a larger window from a model name when the endpoint has not proved that capability.

Allowed prerequisites MUST contain exactly `git_commit`, `config_digest`, `workflow_ref`, `image_digest`, `sdk_digest`, `toolchain_image_digests`, `credential_slots`, `ncbi_identity`, and `prompt_accessions`. The first five MUST equal the launch identity. `toolchain_image_digests` MUST contain exactly `mafft_7.525.hpc_apptainer_sif:v1`, `hmmer_3.4.hmmbuild.hpc_apptainer_sif:v1`, `hmmer_3.4.hmmalign.hpc_apptainer_sif:v1`, and `cdhit_4.8.1.hpc_apptainer_sif:v1`, with hmmbuild and hmmalign bound to identical HMMER SIF bytes. `credential_slots` MUST contain only boolean `llm`, `ncbi`, `semantic_scholar`, and `tavily` availability, with LLM and NCBI ready; `ncbi_identity` MUST be opaque; and `prompt_accessions` MUST equal the formal exact-14 plus fixed probe NCBI/UniProt sets.

`pin` SHALL be the canonical supported operator bootstrap for one reviewable authority declaration transaction. It MUST use the production compiler and trusted Host's forced-SSH runner to execute deterministic non-scientific MAFFT, CD-HIT, hmmbuild, and chained hmmalign payloads, deriving all four toolchain image digests only from runner-issued same-shell runtime identities. Its writer MUST publish the exact-seven identity, exact-nine prerequisites, and one closed credential-free `aox_cutover_launch_profile@1` with mode `0600` in one existing real transaction directory outside the checkout whose three payload targets and fixed marker target do not yet exist, fsync all payloads, and last-publish one exact closed `aox_cutover_pin_commit@3` marker binding all three basenames and digests. The profile MUST contain the complete non-sensitive effective settings and ledger identity used by `pin`, MUST persist open LLM extra-body content only as a digest, and MUST exclude API keys, emails, tokens, Host principals, credentials and credential-bearing URLs. Current `aox_live_attempt_authority_plan@4`, `aox_live_attempt_authority_consumption@5`, and `aox_attempt_preflight@5` MUST bind the same profile digest. Authority consumption MUST validate the committed transaction before producing its receipt; a pre-marker crash MAY leave orphan payloads, but those payloads MUST NOT be consumable. Because the marker is unsigned, its acceptance proves only transaction integrity and consistency, not producer provenance, directory-wide freshness, or consumer-time file mode; trusted operation, an explicit preflight before any root, and runner-issued identities on later live operations remain mandatory.

For authority consumption and preflight, the normal public command path MUST derive the exact `<plan-name>.consumed.json` sibling from the canonical resolved authority-plan path, preserving the plan's complete basename regardless of suffix or embedded dots. The retained `--attempt-authority-consumption` option MAY serve only as an exact compatibility assertion against that owner-derived path; it MUST NOT rebind the receipt, search for an alternative, strip a suffix, or enable a fallback. A mismatching assertion MUST fail before receipt publication, slot claim, root creation, or any Host, runtime, MICU, provider, runner, HPC, or browser effect.

Preflight and the supervised Host MUST reconstruct all non-sensitive launch settings from that pinned profile instead of re-resolving an ambient launch profile. Ambient state MAY supply only credentials that the profile deliberately excludes; ambient non-sensitive launch variables MUST be ignored and MUST NOT override the pinned values. A changed LLM extra-body digest, a shared Host principal, a credential-bearing URL, a legacy controlled-operation owner inside the profile, or any profile/config digest drift MUST fail closed. No hidden default, ambient fallback or profile rewrite is permitted.

Every trusted-operator `pin` or formal `preflight` command that transitively invokes the actual rootless Podman resolver MUST use the documented `uv --project apps/openzyme-host-api run openzyme-aox-cutover ...` public entry in an executor with the rootless runtime directory writable. Codex MUST attach `sandbox_permissions=require_escalated` to that exact tool invocation and MUST NOT directly run `.venv/bin/openzyme-aox-cutover ...` inside a default filesystem sandbox that remounts the runtime directory read-only. A direct Host `podman info` success MUST NOT be treated as proof that a different outer launcher can execute Podman.

Before consuming one-use formal authority, the operator MUST establish that the exact preflight launcher has this platform capability. If the platform cannot grant it before consumption, the workflow MUST stop with unconsumed authority and zero product execution as an operator-environment blocker; it MUST NOT launch a sandboxed preflight to probe permission, create a product failure receipt, or attribute the outer mount restriction to the OpenZyme product or Podman installation. Platform execution permission MUST NOT expand the separately approved plan, budget, effects, target, operation, or scientific strategy.

#### Scenario: Pin and resolve the actual clean launch
- **WHEN** an operator invokes `pin`, authorizes an exact plan, consumes it through the matching policy-free command, and a separately approved conductor performs preflight under the exact same effective settings
- **THEN** pin obtains the four runner-issued direct-SSH toolchain identities, publishes identity/prerequisites/profile plus the marker as one consumer-visible transaction, and preflight reconstructs the exact pinned non-sensitive settings, independently computes the exact-seven actual identity and safe effective-config preimage before root creation, requires field-for-field equality, and makes that same config preimage/digest available for later attempt launch evidence without starting an attempt

#### Scenario: Reject an uncommitted or drifted pin transaction
- **WHEN** the three declarations are cross-directory, symlinked, missing their fixed marker, have an open or malformed marker, or no longer match its bound basenames/digests
- **THEN** authority consumption or preflight fails before constructing launch/session state or creating an attempt root; an orphan payload from a pre-marker crash is never reinterpreted as committed input

#### Scenario: Derive the authority-consumption sibling at its owner boundary
- **WHEN** the public `consume-authority` or `preflight` command receives a canonical authority plan whose basename is default, suffixless, dotted, or otherwise non-default, with no compatibility assertion
- **THEN** it derives exactly `<complete-plan-basename>.consumed.json` in the same real parent directory and never requires the operator to reconstruct that deterministic target
- **AND** when a retained `--attempt-authority-consumption` assertion differs from that derived path, the command returns a typed failure with no consumption receipt, slot claim, attempt root, or external effect

#### Scenario: Seal a consumed-authority configuration failure before slot claim
- **WHEN** one current formal authority plan has been consumed, its exact slot is still unclaimed, its campaign attempt root is absent or empty, and reconstruction of the bound launch profile or current effective configuration fails with a safe public launch error
- **THEN** preflight atomically seals one source-bound `aox_formal_preflight_failure@1` sibling that embeds and revalidates the identity, prerequisites, qualification, launch profile, authority plan and consumption bytes; it proves no slot claim, attempt root, Host, session, scientific attempt, MICU, provider, runner, HPC or browser effect, and the original preflight command still returns the typed failure
- **AND** pure `verify-preflight-failure` plus `decide --preflight-failure` MAY append one `aox_blank_world_campaign_preflight_failure_decision@1` canonical `NO-GO` with empty attempt ids/digests, but MUST NOT invent a `launch_id`, scientific attempt bundle or campaign success
- **AND** a historical failure lacking these source-bound current-schema bytes MUST remain its original blocked/noncanonical evidence and MUST NOT be retroactively backfilled

#### Scenario: Reject launch or inter-attempt drift
- **WHEN** the checkout is dirty, a declared field is missing/extra/malformed, or checkout/workflow/scoring/image/SDK/effective configuration differs initially or before a later attempt
- **THEN** preflight or the conductor's explicit per-attempt admission check fails before creating that attempt root or contacting a model, provider, or runner; no automatic driver continues or emits a substitute campaign state

#### Scenario: Revalidate the actual sandbox launch before claiming a slot
- **WHEN** consumed authority and a pinned profile are structurally valid but the actual Podman binary, rootless runtime, immutable image, Pipeline SDK tree, scientific backend probe or declared launch identity is unavailable or drifted
- **THEN** preflight reruns the full actual launch resolver and its unchanged guard immediately before slot claim, rejects a config-only comparison as insufficient, and seals only the current pre-claim failure path without creating the claim or attempt root

#### Scenario: Run a Podman-transitive command in the eligible outer executor
- **WHEN** an approved `pin` or formal `preflight` will transitively invoke the actual rootless Podman resolver
- **THEN** Codex uses the documented `uv --project ... openzyme-aox-cutover` public entry with `sandbox_permissions=require_escalated`, keeps the rootless runtime directory writable for the child Podman process, and does not substitute a direct Host-only Podman probe or a default-sandbox `.venv/bin` invocation

#### Scenario: Stop before authority consumption when Podman executor permission is unavailable
- **WHEN** an exact formal plan is otherwise ready but the platform cannot grant the required outer-executor capability for its future preflight before authority consumption
- **THEN** the operator reports an operator-environment blocker with the authority unconsumed and zero product execution, and does not create a preflight-failure receipt, slot claim, attempt root, Host, session, MICU, provider, runner, HPC or browser effect

#### Scenario: Reject an immutable image without the frozen AOX backend
- **WHEN** the selected immutable image is present but lacks Biopython, exposes a wrong Biopython/NumPy/algorithm/numeric behavior, or its canonical capability receipt or copied SDK identity drifts
- **THEN** pin or preflight fails before runner attestation, attempt-root creation, and MICU/provider/runner effects; the shell does not install packages, use Host imports, or continue with a fallback backend

#### Scenario: Reject an open prerequisite object
- **WHEN** prerequisites omit an exact-nine field, include an unknown/private/scientific field, disagree with the launch identity, use the wrong toolchain-key set or HMMER digests, or expose a credential value
- **THEN** blank-world launch fails closed before any attempt root is accepted

#### Scenario: Reject runner contract drift
- **WHEN** the runner manifest lacks an exact AOX tool or changes its tool id, adapter id, command template id, or canonical runner-contract digest
- **THEN** launch fails before root creation, and a formal/probe receipt carrying a different runner expectation is rejected offline

#### Scenario: Reject implicit or oversized third-party context
- **WHEN** blank-world live omits `context_window_tokens` or resolves it above `200000`
- **THEN** launch fails before constructing the campaign or making a MICU call

#### Scenario: Reject an unpinned or ineligible reliability configuration
- **WHEN** the effective owner policy leaves any AOX provider/HPC route on legacy ownership, runtime drain is not `command_v1`, mutation closure is not `generic_v1`, or any of those fields drift between pin, consumption and preflight
- **THEN** pin fails before forced-SSH attestation, or consumption/preflight fails before session/attempt-root creation, and the reliability preimage participates in the canonical config digest

### Requirement: 完整 qualification 绑定具备本地 IPC 的单次执行环境
获准的 current full qualification SHALL 通过唯一公开 repository script 执行，并且其第一次实际调用
MUST 位于允许 Starlette `TestClient`、AnyIO 与 asyncio 本地跨线程 `socketpair` 唤醒的执行环境。
Codex preparation approval SHALL 只把该命令所需的本地 IPC、正常包 cache 与 non-live process
supervision 纳入窄范围 sandbox 外权限，不得据此取得网络、live、MICU、provider、runner、HPC 或
Chrome 权限。升级调用 MUST 只包含公开 script、`admission` 与已生成的字面量 output path，不得内联
environment、管道、重定向、命令串联或持久 prefix approval。命令前 MUST 只读确认 canonical
checkout、clean source、fresh checkout 外 output 与 single-flight，并确认 script 仍固定 non-live
环境、清除 live credentials 且拒绝未声明外部端口；命令启动后 MUST 继续服从 source-bound receipt、bounded execution、no-replace
publication 与 pure verification。

Codex MUST NOT 先在普通 command sandbox 运行 full qualification，不得以替代 `UV_CACHE_DIR`、
raw/focused pytest、本地 IPC 探针、另一个 output 或 terminal 后的等价重发作为恢复。平台若在进程
启动前拒绝所需执行能力，操作员 MUST 以 `qualification_execution_count=0` 停止，不得生成或猜测
qualification failure code、report、product defect 或 canonical NO-GO。

#### Scenario: 第一次且仅一次在正确执行环境运行 qualification
- **WHEN** 用户已批准一次 current full qualification，且 canonical checkout、clean source、fresh output 与 single-flight 均已闭合
- **THEN** Codex 对 `check-v3-architecture-qualification.sh admission` 的第一次实际调用直接使用只覆盖本地 IPC、包 cache 与 non-live 子进程监督的 sandbox 外权限，并且不先发出 sandboxed qualification、raw pytest 或 IPC 探针

#### Scenario: 执行能力在进程启动前不可用
- **WHEN** 平台拒绝 sandbox 外权限，或不能在命令启动前保证本地跨线程 IPC
- **THEN** Codex 以零次 qualification execution 停止并报告 operator-environment blocker，不创建 report、不改换 output、不重发等价命令，也不把环境限制归因于 OpenZyme 产品

#### Scenario: 保持 qualification、check-config 与 pin 的权限分离
- **WHEN** full qualification 已在正确本地环境中完成
- **THEN** 该权限不自动授权 `check-config` 之外的配置动作或 forced-SSH `pin`；`check-config` 仍为普通 sandbox 内无副作用解析，`pin` 仍要求其独立 preparation external-effect 授权

### Requirement: 可验证且脱敏的启动配置与失败因果
`openzyme-aox-cutover check-config` SHALL 是无持久化和无外部副作用的公开配置预检。它 MUST 使用与 `pin` 相同的 production settings resolver、ledger identity resolution、effective-config builder 与 closed normalizer，并且成功时只返回闭合 `aox_cutover_config_check@1`：`schema_id`、`status=valid`、`effective_config_schema_id` 与 `config_digest`。它 MUST NOT 接收或生成 qualification、identity、prerequisite、authority 或 state，不得实例化 runner、连接 SSH、执行 fixture 或接触 provider/MICU/Chrome。该 receipt 只证明本次本地配置解析；`pin` MUST 重新计算配置，且该 receipt 不得冒充 admission、pin、runner availability 或 external-effect 证明。测试操作员不得直接 import private settings/builder/service 来替代该公开命令。

fresh preparation MUST 在首次 `check-config` 之前，从 current closed schema 与 operator contract 解析并原子装配完整 command-scoped launch profile。未经装配的 ambient environment 不得冒充该 profile；若普通 Host 默认值已由当前合同证明不合格，测试操作员不得先执行无 profile 的 public check 来试探。批准 fresh `pin` 的 preparation SHALL 覆盖把合同明确要求的非敏感值临时应用到首次 `check-config` 与随后 `pin`；两者 MUST 使用相同的环境映射、ledger identity 与 source identity。完整 profile 的首次 public check 失败后 MUST fail closed，不得逐字段补值或 corrected retry。当前 schema 变化时，测试操作员 MUST 在首次命令前重新推导 profile，不得机械复用历史取值。

当前 `openzyme-aox-cutover` 启动命令 SHALL 以闭合的 `aox_cutover_launch_failure@3` 公开失败。该对象 MUST 包含 `schema_id`、`status` 与 `failure_code`；只有失败源明确标记为可公开时，才 MAY 增加 closed tagged-union `failure_details`。schema branch MUST 使用 `kind=schema_field`，并只保留逻辑字段标识 `identity` 以及可选的 `missing`、`unexpected`。runner branch MUST 使用 `kind=runner_attestation`，并只保留 AOX contract `tool_id`、可选安全 `runner_run_id`、可选 `runner_attempt_receipt_digest`、`stage=runner_call|runner_result`、closed effect certainty 与可选的安全 machine `runner_error_code`；code 只能是全大写执行码或全小写 source-causal code，不接受混合大小写或自由文本。sandbox runtime branch MUST 使用 exact `kind=sandbox_runtime` 与一个 `failure_code`，且后者只能是 `pipeline_sdk_source_unavailable`、`podman_binary_unavailable`、`podman_rootless_preflight_failed`、`sandbox_image_identity_invalid`、`sandbox_image_unavailable` 或 `sandbox_runtime_identity_drift`。它不得包含配置值、Host/runner 路径、凭据、原始消息、stderr/stdout、异常表示或异常链。内部 `details` 不得因存在而自动升级为公开证据。历史 `aox_cutover_launch_failure@1/@2` 只可作为冻结记录读取，不得冒充当前失败 receipt。

AOX 有效配置中的 `research.mcp_enabled=true` SHALL 来自 Host 的权威能力投影，不得从无产品消费者的 `OPENZYME_RESEARCH_MCP_ENABLED` 环境开关或 `ResearchSettings` 影子字段推导。Codex 测试操作员 MUST 区分封存观测、依据当前源码形成的推论与尚未证实的假设；没有公开内部事实时必须保留 `exact_identity_unproven`，不得仅凭假设请求或执行纠正后重试（corrected retry）、授权消费（authority consumption）或其他状态变更。

#### Scenario: 保留字段级原因而不泄露配置值
- **WHEN** 有效配置违反闭合 schema，且 schema 校验器给出安全的逻辑字段标识
- **THEN** `check-config` 或 `pin` 在解析实际身份、创建 attempt root 或产生 MICU/provider/runner effect 之前返回 `aox_cutover_launch_failure@3`，以 `failure_code=aox_launch_effective_config_schema_invalid` 保留外层原因，并只在 `failure_details.kind=schema_field` 中投影获准的字段标识

#### Scenario: 公开预检不通过私有实现自证
- **WHEN** Codex 准备一次 fresh pin 并需要证明当前启动配置可被 AOX 闭集接受
- **THEN** 它调用 public `check-config` 并保存脱敏 receipt；不得 import 或执行 `openzyme_host_api.aox_cutover_launch`、private foundation/service 或 settings builder，且预检不产生 runner、provider、MICU、authority 或 repository effect

#### Scenario: 首次公开预检使用完整启动配置
- **WHEN** current AOX closed schema 要求的非敏感 reliability policy 与普通 Host 默认值不同，且用户已经批准包含 fresh `pin` 的 preparation
- **THEN** Codex 在发出任何检查命令前从 current contract 装配完整 command-scoped profile，只执行一次携带该 profile 的 public `check-config`，并把完全相同的 profile 用于随后 `pin`；它不得先运行无 profile 的检查来制造已知失败，也不得在 terminal failure 后补值重试

#### Scenario: 保留 runner 最早类型化原因
- **WHEN** forced-SSH toolchain pin 返回 terminal runner result，且其中有安全 `error_code` 与 effect certainty
- **THEN** CLI 返回 `aox_cutover_launch_failure@3`，保留外层 `aox_launch_toolchain_pin_execution_failed`，并在 `failure_details.kind=runner_attestation` 中投影 exact tool、可用的 run/receipt identity、result stage、effect certainty 与同一 source-bound `runner_error_code`；不得把它压平为只有 digest 或 generic wrapper

#### Scenario: 保留 actual sandbox runtime 原因
- **WHEN** preflight 的 full actual launch resolver在slot claim前发现Podman binary/rootless/image、Pipeline SDK或pinned runtime identity不可用或漂移
- **THEN** CLI保留外层 `aox_launch_sandbox_preflight_failed`，并只在 `failure_details.kind=sandbox_runtime` 投影allowlisted `failure_code`；不得公开command、路径、stdout/stderr或异常链，且不得创建claim/root

#### Scenario: runner 调用异常保持 effect 未证明
- **WHEN** runner boundary 在返回闭合 result 前抛出异常
- **THEN** CLI 只公开 exact tool、`stage=runner_call` 与 `effect_certainty=unproven`，仅在异常本身携带符合安全 machine-code schema 的 code 时公开该 code，且不输出异常类型、消息、路径或 chain

#### Scenario: 内部详情不自动成为公开证据
- **WHEN** 启动错误内部 `details` 含有私有值、路径、凭据或任意异常文本，但错误源没有明确提供 `public_details`
- **THEN** CLI 只公开稳定的 `failure_code`，不输出 `failure_details`，也不泄露异常链

#### Scenario: 未证明的假设不得授权纠正后重试
- **WHEN** 冻结的公开失败只有外层 wrapper，源码检查只能缩小可能原因而不能证明精确身份
- **THEN** 测试操作员报告已证明事实与不确定性并停在现有权限边界，不注入猜测的配置，不重试 `pin`，也不消费 authority

#### Scenario: 区分一次命令与多次阻塞审计
- **WHEN** 一次 `pin` terminal failure 后，持久 goal 为满足状态协议执行后续只读 blocked audit
- **THEN** 报告分别给出 `pin_execution_count` 与 `blocked_audit_count`；只读 audit 不得被描述为另一轮 pin failure，也不得重新执行等价命令

### Requirement: One-message canonical product path
A positive attempt SHALL begin with one user message through `POST /v3/sessions/{session_id}/messages` and SHALL progress only through resident master/teammate turns, durable signals, canonical delegation, approvals, persistent sandbox execution, Host-supervised providers/HPC, artifact registration, task business exits, and `report.publish`.

The collector SHALL reconstruct exactly one durable delegation request for each researcher, executor, and reporter task. The executor request MUST bind exactly the campaign workflow ref and its complete manifest snapshot; researcher and reporter MUST bind no workflow ref. The bundle SHALL carry a closed public projection of each durable request, including task/role/agent identity, an instructions digest, and the selected workflow fields but not raw instructions. The offline verifier SHALL recompute each request-projection digest and workflow manifest content/core digest and bind the projected agent to the task's assigned ref. `world.inspect(sections=["capabilities"], task_id=..., limit=...)` SHALL bind a teammate to its current task while preserving the existing master session-wide authority. It SHALL return newest-first facts capped at 20 invocations, eight refs per related kind, and 64 KiB serialized facts; it MUST NOT inline document content, output payloads, evidence bodies, source bodies, or gaps bodies.

#### Scenario: Complete the AOX/HMM product path
- **WHEN** required prerequisites and real operations succeed
- **THEN** the workspace proves researcher, executor, and reporter participation; required literature; every operation required by the artifact-derived formal branch plus isolated full-capability probe coverage; explicit task finishes; normalized sealed artifacts; a published report; and a final master response

#### Scenario: Bind the primary literature receipt to the product path
- **WHEN** the researcher completes after bounded iterative PubMed searches
- **THEN** the primary PubMed provider receipt is selected only by exactly one PubMed artifact in researcher `task.finish.evidence_refs`, the report cites a PMID/source from it, and collector plus offline verifier close its task/invocation/artifact/source lineage without requiring a non-null lane

#### Scenario: Reject seeded success
- **WHEN** a test manually seeds tasks, approvals, runs, artifacts, reports, deterministic adapters, notebook output, or fixture scientific records
- **THEN** the attempt is marked fixture/non-cutover and cannot count toward the campaign

#### Scenario: Reject leaked or drifted workflow binding
- **WHEN** researcher/reporter inherit the AOX workflow, executor omits or changes it, a delegation request is missing/ambiguous, or its manifest snapshot/digest drifts
- **THEN** collection or offline verification fails and the attempt is not cutover eligible

#### Scenario: Reject a noncanonical formal task mutation before effect
- **WHEN** the authority-bound formal session calls `task.create` without an explicit canonical id, with a suffixed/replacement id, or with a canonical id carrying the wrong research/execution/reporting kind
- **THEN** the Router precondition returns an LLM-readable validation result with `precondition_rejected=true`, `effect_certainty=no_effect`, and `retry_eligibility=same_phase_safe`; it does not dispatch the task handler, while probe and unrelated sessions retain ordinary task semantics

#### Scenario: Keep an ordinary no-effect failure inside the bounded turn
- **WHEN** an internal signal turn receives `invalid_tool_arguments`, `task_blocked`, or another ordinary effect-known rejection
- **THEN** Harness records one ToolResult and FailureObservation, feeds it back to the model, and does not create a recovery obligation, exact-settlement requirement, response veto, or boundary-fatal result merely because the agent next reads, retries, replans, or responds with prose
- **AND** task, approval, scientific, and external-operation state remain unchanged unless a later canonical command actually changes them

#### Scenario: Keep dependency wait in the canonical task graph
- **WHEN** `task.delegate` observes that the canonical target still has open `Task.blocked_by` dependencies
- **THEN** it returns LLM-readable no-effect facts without delegating, rewriting dependencies, recording a failure-recovery disposition, or enqueuing `RECOVERY_REQUIRED`
- **AND** only a real user/task/protocol/approval/engine/continuation event can create later runtime work; Harness does not require the agent to persist a particular waiting strategy

#### Scenario: Reject premature scientific-attempt closure
- **WHEN** the canonical scientific task assignee requests `scientific.attempt.close` before selection, operation, authority, provenance, writer, or quiescence controls are ready
- **THEN** Core rejects the request without closing the attempt, returns the typed blocking facts, and never chooses an operation, task outcome, scientific branch, report state, response, or replacement plan for the agent

#### Scenario: Retire the requesting turn after successful closure intent
- **WHEN** the canonical scientific task assignee calls `scientific.attempt.close`, passes Core controls, and records the immutable closure request while later tool calls remain in the same provider response
- **THEN** the close result is a successful terminal action, the harness retires the requesting turn without another model step, and settles every later call as `tool_call_batch_interrupted` with `effect_certainty=no_effect` and `retry_eligibility=verify_then_retry`; Host finalization remains post-turn and does not complete a business task or persist companion response state

#### Scenario: Do not reinterpret a close-ready assistant-only response as closure
- **WHEN** an agent emits an assistant-only response while one active attempt still has no closure request
- **THEN** the assistant message may persist under ordinary conversation semantics, but no closure request, task transition, reporter handoff, or acceptance eligibility is inferred from it

#### Scenario: Keep response delivery independent from closure
- **WHEN** the canonical assignee calls `scientific.attempt.close` with empty, non-empty, or absent assistant response text
- **THEN** closure authorization depends only on canonical scientific and mutation controls; the runtime creates no closure-bound message, document, digest, or response binding

#### Scenario: Accept the canonical successful report publication states
- **WHEN** the canonical reporting task has exactly one non-empty published draft linked to exactly one report whose domain status is `ready` or `published`
- **THEN** the shared report-publication predicate treats the link as one successful publication in policy, workspace projection, live collection, and offline verification; no consumer may independently narrow the accepted report state or normalize away the persisted enum

#### Scenario: Commit only immutable closure intent
- **WHEN** a successful `scientific.attempt.close` records its immutable intent
- **THEN** Core persists the closure request without creating conversation records; same-fact replay returns the existing request and conflicting request identity fails closed

#### Scenario: Expose canonical task-finish evidence references
- **WHEN** an agent prepares or submits `task.finish.evidence_refs`
- **THEN** the tool schema and every invalid-reference result expose the exact `<kind>:<id>` format and closed supported kinds, session repositories still resolve every supplied reference, and the runtime neither guesses a kind from an opaque id nor adds a prefix or substitutes a closure request for a finalized scientific closure

#### Scenario: Require owner-authored formal task exits
- **WHEN** final AOX evidence collection evaluates the canonical researcher, executor, and reporter tasks
- **THEN** each task has exactly one status-matching `task.finish` receipt whose `finished_by` equals that task's canonical `assigned_ref`; a master-authored proxy finish may remain valid generic V3 state but cannot satisfy AOX formal readiness or cutover evidence

#### Scenario: Preserve a canonically ready positive execution handoff
- **WHEN** the assigned positive executor's current scientific selection evaluates `closure_request_ready=true`
- **THEN** that executor may request immutable closure; after Host finalization, the ordinary source-bound wake lets the same assignee explicitly call `task.finish(status=completed)`, while closure itself never mutates the task

#### Scenario: Preserve explicit blockers after post-seal readiness drift
- **WHEN** the current selection remains sealed but canonical evaluation reports `closure_request_ready=false` because the operation universe, authority, process, continuation, disposition, adoption, materialization, workflow contract, or evidence closure no longer matches the sealed selection
- **THEN** closure fails closed, explicit `blocked`, `failed`, or `cancelled` task exit remains available under ordinary task semantics, and the harness requires a new current selection or other agent-authored repair rather than treating stale seal state as scientific success

#### Scenario: Separate closure intent from writer-gated finalization
- **WHEN** a sealed current selection is otherwise complete and the requesting assignee turn is the only reason inspection reports `selection_active_writers`
- **THEN** inspection reports `closure_request_ready=true` and `closure_finalization_ready=false`, retains the legacy `closure_ready` field as Host-finalization readiness, permits the assignee to persist agent-authored closure intent in that turn, and requires Host finalization to wait until the requesting writer retires

#### Scenario: Keep capability inspection bounded
- **WHEN** a capability invocation owns megabyte-scale documents, outputs, evidence, source, or gaps
- **THEN** teammate inspection returns only its current-task bounded fact index (20 invocations, eight refs per kind, 64 KiB serialized facts), cross-task filters fail with a typed error, and no owned body bytes enter the agent context

### Requirement: Bounded tool-call fanout closes the provider transcript
Master and teammate conversation drivers SHALL preserve the top-level limit of three dispatched tool calls per provider response. They SHALL project every returned tool call into the public LLM trace, mark only the first three as dispatch-eligible in response order, and convert every excess call into a structured `ToolResult` with `ok=false`, `status=rejected`, `error_code=parallel_tool_call_limit_exceeded`, `effect_certainty=no_effect`, `retry_eligibility=same_phase_safe`, and an LLM-readable retry hint. Before dispatching an eligible call, the harness SHALL durably record the known no-effect observation for every overflow call, while retaining original call order in public results and events. It SHALL emit `tool.rejected` plus `tool.completed` without emitting `tool.invoked` or dispatching the rejected call.

One provider response SHALL be settled as one ordered tool-call batch. If an eligible call causes runtime suspension, a pending approval, a successful terminal action, or a boundary-fatal dispatch failure, every later eligible call that was not dispatched SHALL receive a structured `ToolResult` with `ok=false`, `status=rejected`, `error_code=tool_call_batch_interrupted`, `effect_certainty=no_effect`, `retry_eligibility=verify_then_retry`, the causal call/boundary facts, one persisted failure observation, and `tool.rejected` plus `tool.completed` without `tool.invoked`. A boundary-fatal call that was dispatched SHALL receive a failed `ToolResult` carrying its existing failure observation and exact effect/retry classification; `dispatch_in_doubt` MUST NOT be rewritten as `no_effect`. The harness MUST settle every returned call exactly once before returning from the turn, even when approval, terminal action, or failure means there will be no next provider invocation. It MUST NOT execute interrupted calls automatically after approval or in another turn.

Pre-persisting overflow observations MUST NOT pre-resolve or pre-validate eligible calls against the state that existed before the batch. Each eligible call SHALL resolve task/lane references immediately before its own dispatch against durable state committed by earlier calls in response order. Never-dispatched overflow or interrupted calls SHALL retain their returned references in the ToolResult and observation facts without requiring a future task or lane to exist; relational observation fields SHALL bind only existing current-step authority and MUST NOT make an undispatched target authoritative.

Before any next provider invocation for the same conversation, the conversation SHALL contain one matching `ToolMessage` for every returned call id, in original call order, including rejected overflow and interrupted calls. These dispositions expose constraints and facts only; they MUST NOT choose which work the agent retries.

#### Scenario: Reject a fourth tool call without leaving an open transcript
- **WHEN** a master or teammate provider response returns four tool calls
- **THEN** only the first three calls are dispatched, the fourth creates no business or external effect, all four calls remain visible in the trace, all four receive ordered tool observations before the next provider request, and the provider transcript does not fail because an overflow call lacks output

#### Scenario: Settle a batch before an approval or terminal return
- **WHEN** one of the first three calls suspends for approval, creates a pending approval, or successfully terminates the current turn while later eligible and overflow calls remain
- **THEN** only calls reached before that boundary are invoked, every later eligible call is rejected as `tool_call_batch_interrupted/no_effect/verify_then_retry`, every overflow call retains its `parallel_tool_call_limit_exceeded/no_effect/same_phase_safe` result, and all returned call ids have one ordered durable disposition before the harness returns

#### Scenario: Preserve an uncertain dispatched failure while settling later calls
- **WHEN** one dispatch-eligible call crosses a boundary-fatal failure with `dispatch_in_doubt`
- **THEN** that call's failed ToolResult retains `dispatch_in_doubt` and reconciliation-required semantics, every later never-dispatched call is separately settled as no-effect, and the harness neither retries nor executes another call from the batch

#### Scenario: Preserve an in-batch create-then-bind dependency
- **WHEN** one eligible call creates a task and a later eligible call in the same provider response binds that new task to a lane
- **THEN** the later call resolves its references only after the create result is durable and dispatches normally, while overflow pre-persistence does not reject the batch against stale pre-response state

### Requirement: Host-owned lifecycle facts without an AOX runtime observer
The product runtime MUST NOT expose an AOX runtime observer, a generic
runtime-barrier/observer-writer service, or an AOX-specific projection that derives
business completion, failure, idleness, recovery authority, or the next runtime
command. Host-finalized mutation-scope transitions SHALL remain atomic and Host
repositories SHALL remain the canonical authority for tasks, attempts, reports,
approvals, leases, fencing, effect certainty, continuations and isolation. Public
workspace, event, pending-approval and runtime-command reads SHALL expose bounded
canonical facts without creating an observer writer or excluding another writer
from safety checks.

#### Scenario: Observe state only through public facts
- **WHEN** a Codex test conductor needs to decide whether to issue the next explicit runtime drain, perform a public read, resolve an approved operation, or stop after the canonical entry
- **THEN** it reads the public Host API/CLI projections and makes that test decision outside product runtime; no AOX service registers an observer writer, polls until terminal, or writes a business state on the conductor's behalf

#### Scenario: Preserve atomic attempt scope transitions
- **WHEN** Host admits or closes a scientific attempt while another public read occurs
- **THEN** the transition remains atomic under Host mutation authority, the read observes a canonical before-or-after state, and neither missing wakeups nor runtime idleness is converted into task completion

### Requirement: Exact scientific callable and artifact-selection map
The formal executor SHALL use the installed versioned callables `openzyme_pipeline.aox_reference.select_hmm_reference_set`, `select_scoring_reference`, `assemble_scoring_input`, `openzyme_pipeline.aox_hmmer.parse_and_filter_csv`, `openzyme_pipeline.aox_sequence_join.join_score_filtered_accessions`, `openzyme_pipeline.aox_motif.score_aligned_fasta`, and `openzyme_pipeline.aox_similarity.build_similarity_graph` with their canonical serializers. It MUST NOT approximate or locally reimplement a pinned calculation.

For `build_similarity_graph`, the first input SHALL be the exact full post-motif,
pre-CD-HIT `aox_hmm/AOX_candidates.fasta` bytes and the second input SHALL be
the complete one-row-per-member
`aox_hmm/AOX_candidates_cdhit85.clusters.csv` bytes for that same set. The
representative-only `aox_hmm/AOX_candidates_cdhit85.fasta` SHALL remain a
required deliverable but MUST NOT be used as the graph candidate input.

The pinned agent-facing signature table SHALL disclose the exact Python return type of every canonical result accessor. For the current SDK, primary FASTA/CSV/JSON accessors and `metadata_json()` return `str`, while `metadata()` returns `dict[str, object]`. Executor source SHALL encode canonical payload text exactly once as UTF-8 before a bytes-only boundary and SHALL NOT pass `str` to `Path.write_bytes`, hand-reimplement a serializer, or guess a coercion after annotation drift. Missing or drifted type facts SHALL fail closed as a workflow/SDK mismatch without prescribing source layout, batching, or operation order.

`score_aligned_fasta` SHALL enforce `hmmer_afa_alignment_canonicalization@1`: exact raw-byte digest, LF-only segmentation with at most one CR removed only from an LF-terminated segment, raw-column-zero headers, exact empty-line semantics, raw ASCII `^[A-Za-z.-]+$` validation before uppercase, then `.` to `-` canonicalization. `build_similarity_graph` SHALL enforce raw-ASCII gap-free candidate FASTA and the exact mixed-radix recurrence `score_half_units * R^2 + exact_matches * R + aligned_residue_pairs`, `R=max(m,n)+1`, preserving tuple lexical semantics. It SHALL require `biopython_trace_guarded_numpy_gotoh@1`, Biopython `1.87`, cutover NumPy `2.4.4`, strict `<2^53` binary64 integer bounds, first-optimal-trace validation, and `numpy_three_state_gap_switch_correction@1` when an adjacent opposite gap-state switch is observed; no import/version/algorithm/numeric/trace/correction failure may select an alternate backend or fallback. The reference recurrence state order is tie provenance only: graph artifacts do not promise or publish an alignment path, and any future coordinates/path output MUST use a new calculation id and an explicit trace contract. Its lexical pair map SHALL use serial execution below `128` pairs; at or above `128`, worker count SHALL be the minimum of pair count, `16`, affinity (or `cpu_count` only when affinity is unavailable), and all available cgroup v2/v1 quota/period ceilings. Available but unreadable, incomplete, or malformed cgroup limits MUST fail closed. Worker count `1` SHALL select serial before execution and only a larger count SHALL start ordered process execution with `chunksize=64`. Failures after the process path begins MUST be `scientific_prerequisite_missing:similarity_parallel_execution_failed` and MUST NOT fall back to serial execution. Reference NumPy `2.4.6` and cutover NumPy `2.4.4` MUST remain distinct exact environments with no patch fallback. Final diagnostic qualification SHALL use two independent exact-cutover-`2.4.4` full-set runs whose raw outputs match and whose pin-only-normalized outputs match frozen pure-v3 bytes; it MUST NOT be described as a direct full-set patch A/B or as live evidence.

Provider outputs SHALL be selected from the unique transcript-manifest entry ending in `/provider_parsed/proteins.fasta`, `/provider_parsed/parsed_hits.csv`, `/provider_parsed/sequences.fasta`, or `/provider_parsed/metadata.json` as appropriate. Runner outputs SHALL use only the canonical MAFFT/hmmbuild/CD-HIT/HMMalign declared paths and SHALL be selected from the unique `fetch_refs` item whose `declared_output_path` exactly matches. HMMER search SHALL bind the exact fetched hmmbuild artifact id and content digest.

The sandbox SDK SHALL expose strict direct-field selectors for provider files, artifact registration results, and fetched outputs. A selector SHALL read only its documented canonical field, require one canonical artifact id/digest, and reject missing, duplicated, malformed, or nested-only data without recursive fallback or external I/O. A completed controlled-operation response SHALL be reusable from attempt-local sandbox working state after a local source/parser error; such a local error SHALL NOT authorize another controlled operation for the same reached SDK method.

The sandbox process SHALL treat `/workspace/input` as a Host-managed read-only mount. Caller source SHALL NOT create, write, copy, or pre-create a materialization target or its parents there; `artifacts.materialize()` SHALL create and authorize the requested target and missing parents through the Host boundary, after which source may read only the returned path. Mutable scratch SHALL use `/workspace/work` and registerable output SHALL use `/workspace/output`. `EROFS`, target drift, or a local input mutation attempt SHALL fail closed without remount, alternate-path fallback, or duplicate controlled operation.

#### Scenario: Execute through the installed calculation map
- **WHEN** the formal executor derives reference sets, HMMER filters, identity joins, scoring input, motif scores, or the similarity graph
- **THEN** each output is reproducible from the named callable/serializer, exact sealed inputs, and versioned contract/implementation digest

#### Scenario: Cross the canonical text-to-bytes boundary
- **WHEN** executor source persists a canonical FASTA, CSV, or JSON accessor result through a bytes-only writer
- **THEN** the selected workflow facts identify the result as `str`, the executor encodes it exactly once as UTF-8, and annotation drift or an incompatible value fails closed instead of triggering best-effort coercion

#### Scenario: Reject approximation or positional artifact guessing
- **WHEN** agent source substitutes an approximate calculation, copies a score, guesses an artifact by list position, declares a custom runner path, or binds HMMER to a workspace guess
- **THEN** execution or offline verification fails closed and the attempt is not cutover eligible

#### Scenario: Select a rich response without counting nested provenance twice
- **WHEN** one provider or fetched artifact appears once in its canonical direct list and again in a nested provenance projection
- **THEN** the strict SDK selector returns the one canonical id/digest pair without walking the nested copy or replaying the completed operation

#### Scenario: Materialize into the Host-managed input tree
- **WHEN** executor source requests a nested `/workspace/input/...` materialization target
- **THEN** it does not pre-create the target or parents, the Host materialization boundary creates them, and the sandbox consumes only the returned read-only path

#### Scenario: Stop a duplicate operation before external dispatch
- **WHEN** a local parser/source failure is followed by a second approval request for an SDK method already reached in that cutover session, or any prior controlled operation is terminal failed
- **THEN** the campaign rejects the new approval before provider/runner dispatch, preserves the exact operation history, and requires a fresh attempt rather than selecting a successful subset

### Requirement: Durable provider reconciliation preserves the sealed wire result
A durable provider operation whose external effect and complete artifact transcript are persisted but whose callback is lost SHALL materialize only from the same execution handle's Host-sealed `provider_request.json` and terminal `provider_observation.json`. Recovery MUST read each control document as an fd-anchored no-follow regular file, verify actual bytes against equal exact content/sealed SHA-256 digests, require strict UTF-8 JSON with unique keys and finite values, and enforce exact closed top-level schemas, operation/request/route/provider/config/runtime/output identities, canonical output containment, and every selected artifact's Host provider metadata and digest. It SHALL reconstruct the original provider summary, transcript manifest, validation results, warnings, safe diagnostic ref, and complete S12 result envelope; it MUST NOT substitute a generic recovered/artifact-count summary, replay the provider, select another route, or trust agent-provided recovery data. Each control document MUST be no larger than `8 MiB`; the complete canonical immutable result envelope MUST be no larger than the core `256 KiB` bound, and its inline `bounded_summary` MUST fit inside that same complete-envelope budget. Bulk scientific identities MUST remain in digest-bound artifacts. EBI HMMER candidate identities SHALL be authoritative only in `provider_parsed/parsed_hits.csv`; the inline summary MUST NOT duplicate the complete `candidate_accessions` list.

#### Scenario: Recover a provider effect after callback loss
- **WHEN** a provider has persisted its request, all result artifacts, and terminal success observation for the exact durable operation/request, but the callback is lost before canonical result commit
- **THEN** reconciliation performs no external call, verifies the sealed transcript and artifact identities, and materializes the same provider summary and `result_summary.transcript_manifest` shape that a direct callback would have returned

#### Scenario: Reject an incomplete or drifted recovery transcript
- **WHEN** a required control document is absent, unreadable, oversized, non-canonical, digest-tampered, schema-drifted, identity-drifted, outside the frozen output directory, inconsistent with artifact metadata, or would produce an oversized inline summary or complete result envelope
- **THEN** the execution becomes a terminal-known `recovery_failed` result with no materialized success result, provider replay, alternate route, fallback summary, repeated claim/reconcile loop, report, or cutover eligibility

### Requirement: Durable HMMER dispatch and polling use one immutable external handle
A `durable_async_v1` `bio.hmmer_search` operation SHALL remain owned by its single
`ControlledOperationExecution`; it MUST NOT create an AOX-specific observer, driver,
retry owner, successor, or second business state machine. Its dispatch phase SHALL
submit EBI HMMER at most once. After the provider returns one job id, Host SHALL
immediately persist one Host-private immutable dispatch receipt bound to the exact
execution, operation, session, dispatch generation, frozen `provider_request_id`,
provider id, external job id, HMM/request digests, effective page/max parameters,
poll interval, accepted timestamp, and one absolute deadline. The deadline SHALL be
derived once from acceptance and MUST NOT be reset by worker reclaim, Host restart,
reconcile, polling, or materialization.

Every later poll/reconcile phase SHALL read only that receipt's job id, perform at
most one exact provider observation per bounded worker slice, and append one
Host-private immutable observation receipt with a contiguous index and exact response
bytes/digest. `RETRY`, `PENDING`, `RUNNING`, `STARTED`, `SUBMITTED`, and `QUEUED`
SHALL remain nonterminal for the same job and MUST NOT authorize another submit.
Observation history SHALL be bounded by the frozen deadline/interval. Terminal
success SHALL enter the existing result materialization path without resubmit;
terminal failure or a still-nonterminal job at the frozen deadline SHALL produce a
typed terminal handoff, with deadline expiry preserving `provider_timeout`.

The dispatch and observation receipts SHALL be canonical SQLite records covered by
owner checks, immutable update/delete guards, mutation authority, schema validation,
and exact envelope size/digest checks. They MUST NOT be projected into workspace,
agent trace, events, or public API. If provider acceptance may have occurred but the
callback is lost before the exact job receipt is canonically committed, the execution
SHALL remain `dispatch_in_doubt`; without a provider idempotency/query contract the
system MUST NOT resubmit, infer a job id, adopt another job, or reset the deadline.
The in-process synchronous HMMER loop MAY remain only for explicit `legacy_sync`
compatibility and MUST NOT be selected as durable recovery fallback.

#### Scenario: Resume a nonterminal HMMER job after restart
- **WHEN** submit has produced one immutable dispatch receipt, one or more observations report `RETRY`, and the execution worker is reclaimed or the Host restarts before the frozen deadline
- **THEN** the next bounded slice reads the same external job id and original deadline, appends only the next exact observation, performs no POST, and remains `effect_known` until a terminal observation or deadline

#### Scenario: Materialize one terminal HMMER success without resubmit
- **WHEN** the append-only observation chain ends in terminal success for the receipt-bound job
- **THEN** result pages are materialized through the existing strict page/count/digest path, the raw transcript includes the original submit plus ordered polls and result pages, and no replacement job or deadline is created

#### Scenario: Terminalize a durable HMMER timeout
- **WHEN** the absolute receipt deadline is reached while the latest exact observation remains nonterminal
- **THEN** the operation emits a terminal-known `provider_timeout` handoff, preserves the exact job/receipt history for private diagnosis, and does not remain indefinitely `dispatching`

#### Scenario: Preserve the accepted-submit receipt gap
- **WHEN** EBI may have accepted submit but the Host has no canonically committed exact job receipt
- **THEN** reconcile returns `dispatch_in_doubt`, issues no POST or speculative GET, and requires separately authorized changed state before any new operation

### Requirement: Bounded sandbox control framing
The Host control socket and `openzyme_pipeline` client SHALL exchange exactly one JSON-RPC 2.0 request and one response as newline-delimited frames per Unix-socket connection. Request and response payloads SHALL each have a hard maximum of `4 * 1024 * 1024` bytes excluding the terminating newline. Receivers MUST aggregate across arbitrary `recv` chunks until the newline; a `64 KiB` chunk MUST NOT be interpreted as the frame limit. Host/compat request reads, SDK connect/send, and SDK response reads after the first response byte MUST use a fixed 5-second I/O timeout. Waiting for the first SDK response byte MUST instead remain governed by the outer sandbox run and approval/controlled-operation lifecycle because one request may legitimately pause for human approval or synchronous provider/HPC completion. Once any response byte has arrived, a partial response whose peer keeps the connection open MUST fail non-retryably as `sandbox_transport_response_timeout`. The SDK SHALL reject an oversized request before sending it and SHALL bound response assembly by the same limit. The Host SHALL replace an oversized response with a smaller structured error.

A non-null request `id` MUST be either a string whose UTF-8 encoding is no more than `256` bytes or an integer in the signed 64-bit range; boolean MUST NOT count as an integer id. If the frame is decoded and the id is safe but another JSON-RPC/request semantic is invalid, the error response MUST preserve that safe id. If the id itself is oversized/invalid or cannot be safely extracted, the error response MUST use `id=null`. A successful or method-level response MUST still match the request identity exactly.

EOF before the newline, invalid UTF-8/JSON, duplicate object keys, non-finite JSON numbers, a non-object envelope, invalid JSON-RPC or response identity, and either direction exceeding the limit MUST fail closed with a bounded safe transport error. SDK request and Host response serialization MUST reject non-finite numbers rather than emitting JavaScript-only JSON constants. If the receiver has already observed non-whitespace bytes after the first newline, it MUST reject before dispatch. The hard invariant is at most one executed request per connection: a second frame arriving only after the first was accepted MAY encounter connection close without receiving a second structured error, but MUST NOT dispatch another method or create another controlled operation. An invalid or disconnected connection MUST NOT terminate the accept worker, dispatch a partial method, authorize replay/fallback, or affect the next connection. This local correction SHALL NOT create canonical product state or require a sandbox protocol/image version bump.

#### Scenario: Carry a legitimate multi-chunk scientific envelope
- **WHEN** an artifact-registration or controlled-operation request and its response each exceed one `64 KiB` read chunk but remain within `4 MiB`
- **THEN** Host and SDK assemble the complete newline-delimited frames, validate request/response identity, and execute or return exactly one canonical call without truncation or duplication

#### Scenario: Isolate a malformed or oversized connection
- **WHEN** a client sends an incomplete, malformed, over-`4 MiB` request, or trailing non-whitespace bytes that the receiver observes with the first frame, or the Host would return an over-`4 MiB` response
- **THEN** that call fails with the corresponding structured transport error before partial dispatch or result acceptance, the Host emits only a bounded error response when possible, and a subsequent valid connection remains serviceable

#### Scenario: Never execute a late second frame
- **WHEN** a client sends a valid first frame and only later sends a second frame on the same connection after the first was accepted
- **THEN** the first request may complete and the second may observe only connection close without another error response, but the Host executes at most one request and creates at most one controlled operation on that connection

#### Scenario: Enforce the SDK boundary symmetrically
- **WHEN** the SDK serializes an over-`4 MiB` request or receives an incomplete, partial-and-held-open, malformed, identity-drifted, observed-trailing-data, or oversized response
- **THEN** it raises a non-retryable structured `PipelineSdkError` without hidden batching, operation replay, or backend fallback

#### Scenario: Bound error response identity
- **WHEN** a decoded request has a safe string/int64 id but invalid params or other request semantics, or instead carries an oversized/invalid id
- **THEN** the first error preserves the safe id, the second uses `id=null`, neither request dispatches a partial operation, and the next connection remains serviceable

### Requirement: Source-bearing sandbox execution is explicit
Every otherwise-valid `sandbox.exec` invocation that reaches source preflight SHALL bind an immutable snapshot of the entire non-empty `/workspace/src` tree before `SandboxRun` creation or process invocation. Earlier request, workspace, layout, and runtime validation MAY fail before source preflight. The snapshot requirement includes `python -c`, package/signature inspection, and diagnostic commands; none of them SHALL be represented as a read-only environment-inspection shortcut. The agent-facing tool descriptor, executor contract, controlled execution docs, and AOX live prompts MUST expose this constraint and the factual recovery path without prescribing a scientific strategy. Controlled docs SHALL remain the read-only source for installed API facts. If runtime introspection is still necessary, the executor MUST first author an explicit inspection source under `/workspace/src`.

An empty tree MUST fail as `source_snapshot_empty` with a factual hint that at least one explicit source file is required and that no `SandboxRun` or process was created. The Host MUST NOT generate placeholder source, silently rewrite `python -c` into a source artifact, add an untracked inspection fallback, or weaken source-provenance closure.

#### Scenario: Reject source-free Python inspection before a run
- **WHEN** an executor requests `sandbox.exec` for `python -c`, package/signature inspection, or diagnostics while `/workspace/src` contains no explicit file
- **THEN** it receives `source_snapshot_empty` before `SandboxRun`, process, controlled operation, provider, or runner activity; no CODE Artifact is committed, and the hint directs it to controlled docs or an explicitly authored inspection source without choosing its scientific plan

#### Scenario: Preserve strategy freedom with source-bearing introspection
- **WHEN** controlled docs do not settle a runtime fact and the executor decides introspection is necessary
- **THEN** it may author and execute an explicit inspection source under `/workspace/src`, which receives the same whole-tree snapshot and ordinary failure semantics as every other command

### Requirement: Preserve typed adapter failure diagnostics across the sandbox boundary
When a Host adapter raises a structured failure, the sandbox control response and dependency-free pipeline SDK SHALL preserve the sanitized `error_code`, `hint`, and safe `details` together with top-level `stage` and `retryable`. A non-null stage MUST be a safe public machine identifier. Retryability MUST be a boolean or degrade to unknown; string or numeric truthiness MUST NOT be interpreted as retryability. For `hpc_staging_failed`, the SDK-visible contract MUST carry `stage="hpc_staging"` and the closed Host-trusted `details.runner_failure` projection while excluding SSH target, argv, stderr, credential, Host/remote path, and locator fields. Existing `details.stage` and `details.retryable` MAY remain as compatibility copies, but they MUST NOT be the only representation consumed by the SDK.

This transport is diagnostic only. `retryable=true` MUST NOT cause or authorize automatic replay, reconnect, approval reopening, backend fallback, additional operation dispatch, or adoption of an earlier effect inside the failed attempt.

#### Scenario: Observe a retryable staging failure without replay
- **WHEN** an approved adapter operation or explicit HPC output fetch terminates with typed `hpc_staging_failed`, safe runner phase evidence, and `retryable=true`
- **THEN** sandbox code receives one `PipelineSdkError` with `error_code=hpc_staging_failed`, `stage=hpc_staging`, `retryable=true`, the sanitized hint and closed runner manifest, the adapter/fetch executor is called exactly once, and no private locator crosses the control socket

### Requirement: Bounded canonical artifact-registration metadata transport
The public SDK SHALL continue to accept one logical metadata object through `artifacts.register(..., metadata=...)` without asking the agent to choose a wire placement. The SDK MUST encode that object as ASCII-safe canonical JSON with sorted keys, compact separators and no non-finite values. A payload of at most `256 * 1024` bytes SHALL remain inline. A payload larger than `256 KiB` and no larger than `32 * 1024 * 1024` bytes SHALL be written under the attempt-local logical path `/workspace/work/.openzyme/artifact-metadata/<sha256>.json`, while the request carries only the exact closed `artifact_registration_metadata_sidecar@1` fields `schema_id`, `path`, `content_digest`, and `size_bytes`. A larger payload MUST fail before control-socket connect as `artifact_registration_metadata_too_large`. A raw inline caller MUST provide an object satisfying the same canonical rules and `256 KiB` limit.

The Host MUST resolve the exact digest-derived sidecar wire-path spelling inside the current workspace through fd-anchored no-follow directory/file opens; normalized aliases such as an inserted `./` MUST fail. Before validator, Blob seal, or Artifact row mutation, it MUST validate regular-file type, fstat size, bounded read size, SHA-256, strict UTF-8, duplicate-key and non-finite rejection, object root, and exact canonical bytes. The sidecar is attempt-local transport spool, not an Artifact, scientific evidence item, Blob, or canonical metadata store. The immutable Artifact row MUST retain the complete logical metadata object, and idempotency MUST bind its logical digest rather than the temporary path.

A canonical success MUST use `artifact_registration_response@2`; its `artifact` MUST be the exact closed `{artifact_id, metadata}` projection rather than a general public Artifact record, with a Host-generated artifact id bounded to 256 UTF-8 bytes. Artifact metadata and validation MUST use bounded `artifact_registration_metadata_summary@1` and `artifact_registration_validation_summary@1` projections with full-object digests/counts/sizes. Missing large fields in a summary MUST NOT mean the catalog value is missing. Top-level `content_digest`, `sealed_digest`, and `tree_digest` are Host-owned registration identity fields; SDK and raw Host boundaries MUST reject caller-supplied values before effect. `registered_artifact_ref` MUST reject missing/wrong/extra schemas and `pipeline_provisional_registration_response@1(canonical=false)`. The provisional response MUST omit repeated path/context fields and remain below the frame cap for the maximum 128-item batch. `metadata.required_columns` MUST be limited to 4096 non-empty strings, 256 UTF-8 bytes per name, and 64 KiB in aggregate, with only a <=4 KiB list inlined in the response. A `fasta_zero_records@1` `derivation_contract_id` MUST be limited to 256 UTF-8 bytes before validator/effect so an otherwise valid identifier cannot overflow the bounded response. `register_many` MUST accept at most 128 items and 32 MiB of unique logical metadata and MUST resolve every metadata transport before its first item mutation. Its existing per-item commit behavior is not an all-or-nothing transaction; a broader atomic/result-reconcile redesign remains outside this change.

#### Scenario: Register an AOX metadata object larger than the physical frame
- **WHEN** a canonical logical metadata object is larger than `4 MiB` but no larger than `32 MiB`
- **THEN** the SDK sends a descriptor within the unchanged `4 MiB` frame, the Host validates the exact sidecar before effect, the catalog retains the complete object, and the direct response remains bounded and digest-bound

#### Scenario: Reject an unsafe or ambiguous sidecar before effect
- **WHEN** schema, path, size, digest, final or parent symlink, UTF-8, duplicate key, non-finite value, root type, or canonical bytes drift
- **THEN** registration fails before validation/seal/Artifact mutation and no fallback, truncation, alternate path, or transport replay occurs

#### Scenario: Reject metadata above the sidecar limit locally
- **WHEN** the SDK canonical metadata payload exceeds `32 MiB`
- **THEN** it returns non-retryable `artifact_registration_metadata_too_large` before connect and instructs the caller to register oversized evidence separately

#### Scenario: Prevalidate batch metadata without claiming transactionality
- **WHEN** any `register_many` sidecar is invalid, or item/unique-metadata caps are exceeded
- **THEN** no item is committed due to metadata transport; the implementation and evidence MUST still describe later non-metadata item failures as sequential partial-commit risk rather than falsely claiming an atomic batch

### Requirement: Bounded provider sequence Artifact metadata
Host-supervised NCBI and UniProt provider results MUST keep their complete per-sequence identity records in the separate canonical parsed `metadata.json` Artifact. A parsed FASTA Artifact MUST NOT inline the linearly growing accession-to-sequence-digest map. It SHALL replace only that per-sequence component with `sequence_digest_count`, `sequence_digest_index_digest`, and `sequence_digest_index_contract_id=canonical_sequence_digest_index@1`, while retaining the existing fixed-size database, retrieval, release, identity-contract, aggregate-digest, and zero-record validation provenance applicable to that provider result.

`canonical_sequence_digest_index@1` freezes the following exact preimage and key semantics. The index is one JSON object whose keys are the NCBI requested accessions that produced the canonical FASTA records, or the UniProt active primary accessions that produced the canonical FASTA records; typed inactive UniProt identities MUST NOT appear. Every value is that record's canonical `sha256:<lowercase-hex>` sequence digest from parsed `metadata.json`. The Host serializes the object with Python-compatible `sort_keys=true`, `indent=2`, ASCII-safe JSON string escaping and the corresponding default indented separators, appends exactly one LF, encodes the resulting text as UTF-8, and computes SHA-256 over those exact bytes. `sequence_digest_count` MUST equal both the object member count and parsed FASTA record count. This bounded catalog summary is not an independent cutover evidence item or eligibility input. Formal UniProt evidence MUST continue to establish its existing authoritative raw-provider-response to parsed-`metadata.json` to FASTA scientific closure without trusting the summary; NCBI and other paths continue to rely on their existing byte-Artifact and operation contracts rather than treating this summary as proof of raw normalization. Any future eligibility consumer requires a separately versioned evidence contract and verifier.

Before writing any draft in one provider result, the Host MUST preflight every draft path, reject within-result duplicates and conflicts with an existing catalog digest, and resolve every registration metadata transport. This preflight MUST NOT be represented as transactional validation/sealing/catalog commit across the Artifact set.

`bio.uniprot_fetch.batch_size` MUST be either omitted or an exact non-boolean integer. Boolean, floating-point, and numeric-string values MUST fail before provider dispatch and MUST NOT be coerced by `int(...)` or another fallback.

#### Scenario: Register a real-scale UniProt FASTA without linear inline metadata
- **WHEN** one UniProt operation validates tens of thousands of accessions and constructs its parsed FASTA plus canonical parsed metadata
- **THEN** the complete active/inactive identity partition remains in `metadata.json`, only active primary accessions contribute to the bounded FASTA count/index-digest/contract summary, fixed provider provenance remains present, and Artifact registration does not fail merely because the sequence count exceeds the inline metadata budget

#### Scenario: Reject a later provider draft before any partial write
- **WHEN** any later draft has a conflicting path or registration metadata that exceeds the inline Host-provider transport limit
- **THEN** the Host returns the canonical non-retryable conflict or `provider_artifactization_failed` before writing or registering any draft in that provider result, without claiming all later content-validation or sealing failures are transactionally atomic

#### Scenario: Reject coercible UniProt batch-size values
- **WHEN** a controlled or compatibility invocation supplies `true`, `1.5`, or `"1"` as `batch_size`
- **THEN** it fails input validation before calling the provider adapter, while an exact integer within the configured cap remains accepted

### Requirement: Runner-issued toolchain execution identity
Every cutover-eligible MAFFT, hmmbuild, hmmalign, and CD-HIT operation SHALL carry a closed `mcp_hpc_toolchain_runtime_identity@1` issued by the runner execution boundary. The runner-owned manifest SHALL bind the tool, adapter, command template, contract digest, and private SIF locator; callers MUST NOT submit or override the locator, runtime request/identity, or equivalent deployment metadata. The observed image digest MUST equal the exact prerequisite digest for the operation's versioned toolchain id.

A nonzero `remote_execution` command SHALL preserve its classified transport or tool failure because a failed command cannot produce the success-only toolchain identity marker. Only a zero-exit command with a missing or malformed marker SHALL fail as `TOOLCHAIN_IDENTITY_MISSING`. A runner-issued `SSH_CONNECTION_TIMEOUT` SHALL project as retryable `hpc_runner_timeout`, and any other runner-issued `SSH_CONNECTION_FAILED` SHALL project as retryable `hpc_runner_unavailable`; neither SHALL project as a bio-tool `nonzero_exit`. Retryability SHALL remain an agent-visible policy fact only: the harness SHALL NOT automatically replay the controlled operation, reopen approval, change the exact operation budget, or select a Host-local or sandbox fallback. The affected attempt SHALL remain non-eligible unless a fresh execution independently satisfies every positive gate.

#### Scenario: Attest the actual SIF in the payload shell
- **WHEN** the SSH runner executes an AOX toolchain payload
- **THEN** the same SSH login shell first scrubs every inherited `APPTAINER_*` and `SINGULARITY_*` runtime-control variable and verifies none remains, directly executes the resolved runner-owned SIF pathname, computes SHA-256 over that same pathname immediately before and after the payload, requires both digests to be equal, and only after payload success returns the single equal observed image digest with `attestation_scope=same_ssh_login_shell_pre_exec`, `execution_mode=ssh`, exact tool/adapter/template ids, and runner contract digest through the existing closed public projection

#### Scenario: Preserve runner attestation through durable materialization
- **WHEN** a terminal runner result carries `mcp_hpc_toolchain_runtime_identity@1` and the Host materializes the durable operation result
- **THEN** the Host revalidates the exact schema/scope/mode, operation catalog tool id, safe identifiers and SHA-256 digests, strips private/extra runner fields, and preserves the exact safe eight-field identity in the immutable result envelope consumed by the collector

#### Scenario: Terminalize a malformed durable runner attestation
- **WHEN** a terminal runner result contains a malformed, wrong-tool, wrong-mode, or otherwise invalid toolchain runtime identity
- **THEN** the operation terminates with `durable_hpc_toolchain_runtime_identity_invalid` and no materialized success result; the Host MUST NOT repeatedly reconcile it, infer a replacement identity, or downgrade it to a generic artifact-set wait

#### Scenario: Fail closed when the runtime environment cannot be scrubbed
- **WHEN** an inherited Apptainer/Singularity runtime-control variable cannot be removed in the payload login shell
- **THEN** the runner stops before hashing or executing the payload and emits no toolchain runtime identity; ambient trusted-Host configuration is never reinterpreted as caller intent

#### Scenario: Bound the narrow pathname guarantee
- **WHEN** the pre/post hashes are equal and the closed identity is issued
- **THEN** the receipt proves direct execution of one pathname whose bytes did not change across the payload, but does not claim immutable inode or content-addressed snapshot semantics

#### Scenario: Reject caller or identity drift
- **WHEN** a caller injects runtime/deployment identity, the runner attestation is missing or malformed, or its tool/template/contract/image identity differs from the operation and exact-nine prerequisite
- **THEN** the operation cannot contribute a cutover-eligible toolchain receipt

#### Scenario: Reject Slurm as current cutover identity
- **WHEN** an AOX tool operation executes through Slurm without a job-internal same-execution SIF attestation
- **THEN** submit/preflight metadata is not reinterpreted as runtime identity and the operation is non-cutover even though Slurm remains available for general runner workloads

### Requirement: Canonical controlled-operation backend receipt identity
For every completed controlled operation, the live evidence collector SHALL select exactly one backend-native canonical run identity according to `selected_backend`: an HPC operation MUST expose `run_id`, while a `provider_http` operation MUST expose `provider_request_id`. The collector SHALL normalize that value into the evidence field `backend_run_id`. A completed operation with a missing canonical field, a legacy/generic `backend_run_id` source field, a field belonging to the other backend, multiple candidate identity fields, or an unsupported backend SHALL fail closed instead of inferring or adopting an identity.

#### Scenario: Normalize a current durable HPC result
- **WHEN** a completed HPC controlled operation carries its durable result envelope with exactly one non-empty `run_id`
- **THEN** the collector projects that exact value as evidence `backend_run_id`, and downstream probe/toolchain receipts bind the same value

#### Scenario: Reject a noncanonical or ambiguous backend identity
- **WHEN** a completed operation omits its backend-native identity or exposes a legacy/generic/other-backend identity field
- **THEN** collection fails with a typed missing, ambiguous, or unsupported backend-identity error before the operation can satisfy probe or formal attestation

### Requirement: Known-positive and empty-result separation
The campaign SHALL use `aox_known_positive_probe@2` / `probe_id="independent_globin_provider_hpc_probe"` independently from the formal scientific result. The probe SHALL use NCBI `NP_000509.1` and `NP_000549.1`, UniProt `P68871` and `P69905`, and exactly six isolated controlled operations: the two provider fetches plus MAFFT, hmmbuild, protein CD-HIT at identity `1.0`, and HMMalign consuming the real probe HMM and clustered UniProt FASTA. It SHALL select each provider parsed FASTA through the unique transcript-manifest relative-path suffix, fetch all four HPC run handles including terminal HMMalign, and select every fetched artifact through the unique exact declared-output-path ref rather than positional ID order; output fetches SHALL NOT be counted as additional controlled operations. Fixed runner templates SHALL expose and require their canonical output path sets before runner/HPC dispatch; a missing, extra, duplicate, or custom declared path SHALL return an LLM-readable `bio_tool_output_contract_mismatch` and SHALL NOT be silently rewritten or submitted as a predictably failing HPC job. A real no-hit or no-candidate outcome MAY complete as a trustworthy empty-result report but MUST NOT be described as candidate discovery, and probe data MUST NOT be inserted into formal result artifacts.

#### Scenario: Verify the v2 probe
- **WHEN** a positive attempt presents a known-positive attestation
- **THEN** the verifier confirms the exact schema/probe id, raw provider response-body digests, one isolated task/workspace/sandbox/source snapshot, the exact six operation/artifact edges, and complete identity disjointness from the formal graph

#### Scenario: Reject a legacy or polluted probe
- **WHEN** the probe uses the AAB-only `@1` chain, omits a v2 operation, reuses a formal identity, or contributes bytes/claims to the formal result
- **THEN** the attempt is not cutover eligible even if every reached formal artifact validates

#### Scenario: Formal result is empty with healthy dependencies
- **WHEN** the known-positive probe succeeds but the formal current-data workflow yields no candidates
- **THEN** the system may publish an empty-result report with complete negative evidence and keeps discovery status distinct from execution status

#### Scenario: Probe fails
- **WHEN** a required provider or HPC/toolchain known-positive probe fails
- **THEN** the attempt is not cutover eligible even if a formal path happens to produce empty files

### Requirement: Artifact-derived healthy-empty closure
The verifier SHALL derive the reached formal branch from sealed raw/parsed HMMER, score-filter, UniProt join, motif-score, and candidate artifacts. It SHALL require the exact operation set for that branch, reject extra or hidden failed formal operations, and use isolated probe coverage for required capabilities that the formal branch correctly omits. Within one verifier invocation it SHALL recompute the similarity graph exactly once from sealed candidate FASTA and CD-HIT membership, then compare node bytes, edge bytes, and manifest closure against that same invocation-local result. This MUST NOT create cross-invocation or cross-attempt cache authority; recomputation failure remains fail closed.

The live campaign SHALL enforce the same closed operation surface and exact attempt authority before each approval. A known terminal occurrence whose execution proves `no_effect` MAY remain in the same authorized formal attempt when the agent explicitly records a legal `failed`, `superseded`, or `abandoned` disposition; a later same-attempt operation MAY satisfy the same reached role and be selected only through the complete selected-chain contract. Host admission and the offline verifier SHALL NOT treat the mere existence of a second same-method occurrence or a known closed no-effect failure as automatic attempt disqualification. They SHALL reject later external work or eligibility when any prior occurrence has unknown or dispatch-in-doubt effect, an active or reconcile-required execution/process/writer/continuation, missing attempt binding or disposition authority, cross-attempt reuse, or an authority/resource/permission breach. Provider-internal bounded retries that remain inside one durable controlled operation are not additional operations.

#### Scenario: Replace a known no-effect occurrence in the same attempt
- **WHEN** one formal controlled operation terminates with a known no-effect execution and a later operation in the same authorized attempt legally satisfies the same workflow role
- **THEN** both occurrences remain in the complete universe, the agent explicitly dispositions the failed occurrence and atomically adopts the replacement, and the attempt is not disqualified solely because both operations exist

#### Scenario: Block an unresolved or unauthorized replacement
- **WHEN** an earlier occurrence is dispatch-in-doubt, active, reconcile-required, belongs to another attempt/scope, lacks disposition authority, or crossed a resource or permission bound
- **THEN** later dispatch and selection seal fail closed as applicable even if another operation appears to satisfy the same SDK method or workflow role

#### Scenario: HMMER upstream is empty
- **WHEN** the sealed HMMER score-filter calculation yields no accession
- **THEN** formal UniProt, HMMalign, and CD-HIT operations are absent; a strict upstream-empty receipt proves no UniProt I/O; coordinate-reference/scoring-input, canonical empty scoring/candidate/membership/graph artifacts, and an honest published empty report remain required

#### Scenario: Length filter is empty
- **WHEN** UniProt retrieval and the identity-preserving join succeed but no sequence is within inclusive length `650..700`
- **THEN** formal HMMalign and CD-HIT are absent, the reference-only scoring alignment is recomputable, and all downstream empty artifacts validate

#### Scenario: Motif filter is empty
- **WHEN** HMMalign and `aox_motif_rule_score@1` succeed but no target passes
- **THEN** formal CD-HIT is absent and canonical empty membership/graph closure is required without fabricating a representative

#### Scenario: Formal result is non-empty
- **WHEN** at least one target passes the motif rule
- **THEN** the formal closure includes CD-HIT membership and the versioned real-sequence similarity calculation over actual candidate bytes

### Requirement: Typed empty artifacts and sealed source trees
A zero-record FASTA MAY pass artifact registration only when its bytes are exactly empty and the caller supplies `validation_profile=fasta_zero_records@1`, a stable lowercase `empty_result_reason`, and a versioned `derivation_contract_id`. The attempt bundle MUST seal `openzyme_typed_empty_artifact_validation@1` derived from the exact catalog validation result; the offline verifier MUST reconstruct that result digest and bind its reason to the scientific outcome. The generic FASTA validator, an unknown profile, whitespace, a header-only sentinel, placeholder residues, missing typed metadata, missing receipt, or receipt drift MUST fail closed.

A typed pipeline source snapshot directory SHALL retain `kind=code` and be sealed in evidence as canonical `openzyme_sealed_source_tree@1`. Entries MUST use unique sorted safe relative paths and bind file size, content digest, canonical base64 bytes, and a recomputable tree digest. The builder and offline verifier MUST public-safety scan every UTF-8 file after decoding its base64 bytes and MUST reject symlinks, non-regular files, empty trees, kind drift, private decoded source, non-canonical JSON/base64, per-file drift, tree drift, or a directory artifact without the exact source-snapshot semantic type/format.

The public scanner MUST preserve exact declared source bytes and MUST reject secret-like material, private backend locators, private URLs, path escape, digest drift, and explicit private roots including `/home`, `/root`, `/tmp`, `/scratch`, `/cluster`, `/gpfs`, `/lustre`, `/mnt`, `/private`, Windows drives, UNC paths, and their supported encoded forms. It MUST NOT classify every slash-prefixed program token as a Host path: portable shebangs, application route syntax, custom logical selectors, and ordinary language path expressions remain source bytes unless they match a closed unsafe category. Existing logical `/workspace`, `/openzyme/control.sock`, and closed public `/v3/...` route handling remains unchanged.

#### Scenario: Register a derived zero-record FASTA
- **WHEN** a reached scientific branch legitimately derives no sequence records and registers exact-zero FASTA with the complete typed profile metadata
- **THEN** the artifact boundary accepts it and preserves the profile/reason/derivation identity for offline closure

#### Scenario: Reject an empty sentinel
- **WHEN** an agent writes placeholder text, a sentinel header, whitespace, fake residues, or omits the typed zero-record metadata
- **THEN** registration fails and no cutover artifact is created

#### Scenario: Verify a pipeline source snapshot offline
- **WHEN** a bundle contains the executor or probe pipeline source snapshot
- **THEN** the verifier decodes every canonical envelope entry and reproduces all per-file and source-tree digests before accepting source provenance

#### Scenario: Preserve portable source syntax
- **WHEN** a sealed Python source contains `#!/usr/bin/env python3`, application route syntax, a custom logical selector, or a real expression such as `Path("aox_hmm")/p.name`
- **THEN** the scanner preserves those exact bytes without weakening secret, private-root, locator, traversal, or digest verification

#### Scenario: Reject an explicit private root
- **WHEN** public evidence contains traversal, `/home/...`, `/tmp/...`, `/scratch/...`, a private Windows or UNC root, an encoded private root, a private locator, URL, or secret-like material
- **THEN** public-safety verification fails with the applicable typed unsafe category and the attempt is not cutover eligible

#### Scenario: Seal the known-positive probe source without path ambiguity
- **WHEN** the known-positive probe supplies its NCBI and UniProt output directories
- **THEN** declared source bytes remain digest-bound and pass only when no secret, private root, private locator, path escape, or digest mismatch is present

### Requirement: Runtime lease liveness remains independent and fail closed
During a file-backed runtime turn, every session-lease heartbeat and contention retry SHALL open and close a fresh repository connection rather than reuse the coordinator or blocking worker connection. Only SQLite `BUSY` and `LOCKED` MAY be retried, with capped backoff that continues only until success or the currently observed lease expiry. The repository SHALL acquire SQLite writer authority before calculating heartbeat/acquire timestamps; waiting across the old expiry MUST NOT revive a lease. Other exceptions SHALL propagate after scheduler cleanup restores the prior context and releases any releasable row, and confirmed or locally observed lease loss SHALL stop renewal. Any subsequent stale canonical write SHALL remain rejected and SHALL cross sandbox control, Pipeline SDK, and Host API as non-retryable `runtime_write_fenced` with a safe fixed public diagnostic.

#### Scenario: Recover from repeated transient SQLite contention
- **WHEN** repeated heartbeat attempts during a blocking provider turn raise SQLite `database is locked` and a later fresh-scope retry succeeds before lease expiry
- **THEN** the original runtime owner retains authority and a contender cannot reclaim at the original expiry

#### Scenario: Preserve confirmed stale-write fencing
- **WHEN** the lease is no longer active and a sandbox callback attempts a canonical write
- **THEN** the write is not applied and the public error is non-retryable `runtime_write_fenced`, not a generic or retryable transport error

### Requirement: Idempotent durable-event replay closes its SQLite transaction
When a standalone repository connection attempts to append an already stored durable event with the exact same canonical content, the system SHALL return the existing event without allocating another cursor and SHALL close the implicit SQLite transaction opened by the failed duplicate INSERT before returning. When the same replay runs inside an owning Unit of Work, the outer owner SHALL retain commit/rollback authority. A same-content replay MUST NOT leave a transaction that prevents mutation-writer retirement, freeze, or quiescence.

#### Scenario: Retire an event writer after same-content replay
- **WHEN** an event-outbox mutation writer replays an exact existing durable event on a standalone connection and then exits its bounded writer turn
- **THEN** the existing event is returned, the connection has no standalone transaction left open, and the writer reaches a terminal state without a nested `BEGIN`

### Requirement: Closed artifact kinds and fixed AOX deliverable contracts
Artifact registration SHALL accept only the exact nine control-plane kind values `code`, `log`, `sequence`, `structure`, `report`, `research_dossier`, `result`, `cache`, and `other`. The dependency-free SDK and every Host/raw-control registration boundary SHALL reject another value before sealing or external dispatch with non-retryable `artifact_kind_invalid`. `directory` MAY remain an `expected_outputs` shape sentinel but SHALL NOT be stored as an artifact kind.

Every one of the 17 normalized AOX deliverable paths SHALL retain the exact kind/format pair defined by `aox_fixed_deliverable_artifact_contract@1`: FASTA=`sequence/fasta`, HMM=`result/hmm`, CSV=`result/csv`, and JSON=`result/json`. Online copies, cache hits, controlled fault targets, bundles, and the offline verifier SHALL bind the exact path, pair, and contract id. A missing binding, renamed path, duplicate/missing positive deliverable, or kind/format drift SHALL fail closed.

#### Scenario: Reject a semantic label as artifact kind
- **WHEN** an SDK or raw-control caller declares an HMM as `kind=model`
- **THEN** registration returns non-retryable `artifact_kind_invalid` and creates no artifact

#### Scenario: Reject normalized deliverable wire drift
- **WHEN** a positive or fault bundle changes a fixed deliverable path, kind, format, or contract binding
- **THEN** offline verification fails and the evidence cannot contribute to GO

### Requirement: Sealed and offline-verifiable evidence bundle
Each formal acceptance attempt SHALL generate a canonical evidence payload and digest covering the exact-seven launch identity, effective-config preimage, exact-nine prerequisites, provider and runner-attested toolchain identities, clean-root proof, public conductor receipts, approvals, operations, input/output artifact digests, task/report identities, final answer, warnings, degradation, and scientific outcome. An offline verifier SHALL recompute the bundle and all reachable sealed artifact digests without contacting external providers.

#### Scenario: Verify an untampered attempt
- **WHEN** the verifier receives a completed attempt bundle and its authorized artifact root
- **THEN** it reproduces every declared digest, confirms lineage closure and required fields, and returns a structured passed result

#### Scenario: Detect tampering
- **WHEN** an artifact byte, provenance field, operation identity, report content, or bundle field is changed or removed
- **THEN** offline verification fails with the exact mismatched identity and the attempt cannot be cutover eligible

#### Scenario: Preserve provider failure diagnostics without widening success
- **WHEN** a sandbox provider operation fails after its request draft exists
- **THEN** its sealed request/observation/error diagnostic artifacts retain the original canonical failure and safe refs without retry or replay, remain outside the fixed 17 normalized deliverables, and cannot make the attempt or provider operation successful

### Requirement: Diagnostic evidence remains disjoint after automatic runner deletion
Diagnostic and formal authorities, roots and sealed evidence SHALL remain schema- and
identity-disjoint, and every diagnostic decision SHALL remain
`acceptance_eligible=false`. The runtime MUST NOT expose `run-live`,
`run-diagnostic-live`, an AOX automatic runner, a diagnostic authority mint/consume
command, or any command that consumes authority and then drives a session until a
derived terminal state. Formal authority declaration/consumption, pin, preflight,
process supervision and evidence verification MAY remain independent operator shells,
but they MUST NOT choose the next message, drain, approval, retry, task state, attempt
state, report state or campaign decision.

#### Scenario: Reject promotion of diagnostic evidence
- **WHEN** historical diagnostic authority, state, effects, bytes or a diagnostic decision are presented to a formal verifier or reducer
- **THEN** they remain non-cutover and cannot satisfy or weaken any formal slot, even when their content digests match later formal content

#### Scenario: Do not expose an automatic AOX run command
- **WHEN** an operator inspects the AOX cutover CLI after r68
- **THEN** it exposes declaration, authority, exact preflight, policy-free Host supervision, source-bound finalize-and-seal, evidence verification and campaign reduction commands but no command that automatically drives a live AOX session

### Requirement: Authority-bound public conductor production reachability
After an exact plan has been consumed, preflight SHALL first validate the clean
launch identity, committed pin transaction and launch-profile digest, current full architecture qualification,
runtime configuration, exact plan/consumption binding and unused slot. Preflight
MUST require current `aox_live_attempt_authority_plan@4` and
`aox_live_attempt_authority_consumption@5` source bytes. Preflight
MUST rerun the full actual launch resolver and its unchanged guard immediately before slot claim,
including the current checkout/workflow/scoring identity, actual Podman runtime identity,
immutable image, Pipeline SDK digest and `aox_sandbox_scientific_backend_probe@2`.
A config-only digest comparison MUST NOT satisfy this gate. Any typed actual-runtime
failure MUST stop through the pre-claim source-bound failure path without creating a
slot claim or attempt root. Preflight
MUST then atomically publish one mode-private no-replace
`aox_attempt_authority_slot_claim@3` sibling before any root creation. The claim
MUST bind campaign, plan/consumption, exact ordinal, attempt kind, session, root,
campaign-root identity, authority-policy digest and a deterministic source-derived
`launch_id`. It MUST NOT contain or imply a task id, envelope/request identity,
attempt id, lane id or admission idempotency key. Only
after that claim succeeds MAY it
create that slot's one fresh private root, copy the exact claim into its evidence
root, copy the pinned profile, and seal `aox_attempt_preflight@5`; the receipt MUST state that Host was not started and MUST
be rejected when rebound, replayed, symlinked, drifted or reused after any
session/attempt state exists.

Within the session, no operator authority MAY be granted to a speculative task.
The current `aox_public_conductor_execution_contract@2` SHALL bind the exact session
creation request and exactly one raw entry-message request whose `skill_keys` contain
only the preflight-pinned workflow reference. The formal wrapper MUST require those as
the first two successful public actions, reject a missing/different pin and every later
session message before calling Host, and treat historical execution contract `@1` as
read-only and non-admissible for new execution. After the canonical entry, the Codex
conductor SHALL submit one bounded drain, seal both its public admission response and
its one public terminal status response, and then seal a public canonical workspace
read. That read MUST contain exactly one execution task. Only then MAY the operator use
the dedicated late-bound grant command to atomically grant the slot authority to that
actual task using the source-derived campaign and policy binding. Generic formal
`public-host scientific authorize`, a missing or ambiguous execution task, a pre-grant
task id, a second grant, or a grant to any other task MUST create no scientific
authorization or effect.

The assigned executor SHALL create a real lane and bind that canonical execution
task using ordinary lane tools before invoking `attempt.create`. The tool SHALL
accept only the authority envelope and one idempotency key; task focus, lane,
campaign, workflow contract, scope, resources, effect classes and private routes
SHALL be derived from canonical Host state. Both request persistence and Host
finalization MUST revalidate the exact current task assignee. The Host SHALL generate
the admission and attempt identities only at finalization and deliver those
late-bound facts through the canonical owner wake. Wrong actor, reassignment,
absent/foreign lane, ambiguous authority or legacy caller-supplied identity fields
MUST create no attempt and consume no effect.

A runtime command MAY begin before any mutation scope exists and open the session's
first scope during its bounded scheduler batch. After that transition, every later
command lease heartbeat, post-transition projection and terminal settlement MUST use
its own short writer authority bound to the exact command id and MUST retire that writer
immediately after the write. Every heartbeat MUST preserve the exact state version,
lease token and fencing token. SQLite `BUSY` / `LOCKED` and the exact race in which the
scope opens after a writer admission observed no scope MAY be retried only through fresh
repository/writer scopes, a fixed finite delay set and the currently observed lease
expiry. Executor completion MUST cancel a pending contention retry so exact terminal
settlement can fence the row. Token, fence or state drift, any unrelated integrity
failure and retry exhaustion MUST fail closed without replaying the scheduler,
reconstructing an outcome, creating a replacement command or writing business terminal
state.

`serve-attempt` MAY start only the fixed loopback production Host in one local
process group using that exact preflight receipt. It MUST disable background
runtime and MUST NOT send a message, drain runtime, resolve approval, retry,
roll over a scope, inspect business terminal state or derive a campaign result.
Startup and retirement receipts MUST bind the same root/process epoch; local
retirement does not prove remote-effect cancellation or business closure.

Before the supervised child constructs its foundation, opens a listener, emits
child-ready, creates a session, invokes a model/provider or admits an effect, it
MUST use the same injected production sandbox runner that public runtime health
and execution will use to obtain one exact closed identity containing
`configured_image_ref`, `immutable_image_ref`, `image_digest`,
`pipeline_sdk_digest`, `sandbox_protocol_version` and
`runtime_identity_digest`. The Host MUST validate the declared image and SDK
digests from the authority-bound preflight, immutable/image equality and the
recomputed runtime digest. The Podman runtime protocol identity and the Core
workspace-manifest protocol are distinct typed fields and MUST NOT be projected
as one version.

The fresh file-backed SQLite transaction MUST prove that the complete sandbox
image registry, session registry and sandbox-workspace registry are empty,
including non-default image rows. It SHALL atomically write and reread exactly
one digest-pinned, cutover-compatible Core image record and seal one
source-bound sandbox-bootstrap receipt into child-ready, Host startup and the
final source-attestation set. Missing, malformed, mismatched, preexisting,
duplicate, drifting, tampered, write-failed or reread-failed state MUST stop
before ready/session/model/MICU/provider/HPC. The bootstrap MUST NOT pull, build,
install, retag or choose an alternate image, and Codex MUST NOT mutate SQLite to
satisfy it. Ordinary Hosts without this explicit formal bootstrap SHALL retain
the canonical `sandbox_image_missing` result.

If that supervised bootstrap fails before child-ready, the child SHALL emit one
closed failure frame bound to its live PID, process-group id, `/proc` start-time
ticks, process epoch, failure stage and safe typed sandbox subcause. The parent MUST
validate that identity while the child is still alive, retire the exact process
group, and revalidate the fresh attempt root, exact initial evidence set, zero
control-plane rows, zero local mutation writers and empty effect directories before
sealing `aox_supervised_host_pre_ready_failure@1`. This receipt MUST explicitly state
that startup, terminal supervision and public receipt-chain artifacts do not exist;
it MUST NOT fabricate any of them. Unknown process identity, descendant retirement,
SQLite/root freshness, effect certainty or typed cause MUST remain an evidence
blocker and MUST NOT be sealed as this mode.

Current zero-attempt failure output SHALL use the discriminated
`aox_formal_slot_failure@2` union. `closure_mode=public_host` SHALL retain the
post-child-ready retirement-readiness source chain. `closure_mode=pre_child_ready`
SHALL accept only the exact preflight, slot claim,
`aox_supervised_host_pre_ready_failure@1`, and two distinct unchanged MICU ledger
snapshots from the same evidence root; startup/supervision/public receipts or an
attempt bundle MUST make this branch invalid. Historical `aox_formal_slot_failure@1`
MAY remain readable only for its original public-Host frozen evidence and MUST NOT
accept, crossgrade or emit the pre-child-ready branch.

The public Host SHALL export one exact closed attempt and sealed selection through
`GET /v3/sessions/{session_id}/scientific-attempts/{attempt_id}/selections/{selection_id}/evidence`.
Formal positive export MUST revalidate the persisted source-bound 17-deliverable
finalization receipt and read every declared sealed file through the artifact
boundary. Cross-session, open-attempt, wrong-selection, missing receipt, artifact
scope/type/size/digest drift and path substitution MUST fail closed.

The export SHALL be `aox_closed_attempt_evidence@2` and contain one
`aox_public_product_closure@1` derived from canonical repositories plus the complete
ordered durable event replay. It MUST prove exactly the research, execution and
reporting tasks, unique assigned agent identities and exactly one assigned-agent-
authored finish per task. A positive closure MUST prove all three completed, one
source-linked report/draft and the final assistant answer. A fault closure MUST carry
the full `aox_fault_negative_state_closure@1`. Final public workspace/events and the
sealed export MUST reproduce those same facts.

The thin Host CLI SHALL be able to append every public response, including non-2xx
responses, as canonical JSONL `openzyme_public_api_receipt@2`. Each record is the
exact closed object `schema_id`, `sequence`, `method`, `route`, `status_code`,
`request`, `request_digest`, `response_digest`, and
`response_semantic_digest`; message text SHALL be represented only by its digest
plus exact skill/task/lane semantics. The chain MUST be continuous, mode-private,
single-linked, locked, fully written and fsynced. A requested final response MAY
be sealed once as `openzyme_public_host_response@1` only when it reproduces the
same semantic digest.

Formal preflight SHALL publish one source-bound
`aox_public_conductor_execution_contract@2` that derives the exact
Host/project/session binding, exact canonical session/entry requests, one pinned
workflow reference, the dedicated late-bound authority command, public runtime-drain
bounds, and relative receipt/response evidence names from the consumed slot. Formal
drains MAY choose any integer `max_signals` and `max_steps_per_agent` accepted by the
public Host schema (`1..100` for each), but MUST keep
`auto_enqueue_ready_tasks=false`; historical fixed `1/8` cadence is not an evidence
contract. After the exact two-action entry has closed, the formal public command SHALL
inject only the mechanical bindings, reject caller overrides and prohibited entry/
authority commands, and preserve the caller's choice of every otherwise-valid public
Host action, arguments and bounded cadence. It MUST NOT select scientific tools, task
strategy, drain count or business terminal state for the agent.

The receipt chain SHALL attest only actions owned by the Codex conductor: one exact
session creation, one exact pinned entry message, explicit bounded drain and status reads, the sealed
canonical task read, late-bound authority grant,
pending approval reads/resolutions, the exact fault capability and final canonical
reads. It MUST reject any conductor receipt for agent-owned
`scientific-attempt-commands` or Host-owned admission/closure finalization. Agent and
Host transitions SHALL be established only by canonical control, workspace, events
and export. Every bounded drain MUST seal its exact admission response and exactly
one later terminal command-status response before the next drain or final reads.
The terminal response MUST reproduce the same command and equal the unique canonical
`runtime.command.finished` event projection for command id/type, status, completion
time, bounded outcome and safe error/retry fields. A digest-only status receipt,
unsealed GET, synthesized response, extra handoff, or status/event drift MUST fail
closed. CLI JSON handoff MUST be flushed, recursively sanitized on non-2xx, bounded,
and sealed with the same canonical response semantics as a successful request.

Before operator-requested Host retirement, the public conductor shell SHALL recompute
the complete receipt chain and every sealed response, prove one-to-one receipt/response
coverage, validate every bounded drain admission/terminal event handoff, and require
post-mutation final public workspace and event reads. It SHALL seal those immutable
facts as one source-bound retirement-readiness receipt. The supervisor MUST refuse an
operator retirement request and keep the same Host process available when readiness is
missing, stale or invalid; it MUST NOT retry a command, create a task or choose a
business outcome. Child exit and authority expiry remain honest terminal supervision
facts and MUST NOT be concealed by this operator gate.

A recursively sanitized and exactly sealed 4xx/5xx public response MAY remain in the
retirement and formal-slot-failure source chain so that a real failure cannot poison
operator retirement. It MUST remain ineligible for a positive attempt bundle, and its
HTTP status alone MUST NOT become a business or campaign cause; zero-attempt NO-GO still
requires the independent canonical typed-cause and final-state closure.

For the formal fault slot, the public Host SHALL expose only the authority-bound exact
`AOX_ref21.fasta` byte-zero flip capability. It MUST validate the active fault attempt,
exact derived selection contract and sealed bytes, require zero existing consumers,
persist an immutable one-use claim before mutation, flip exactly one bit without size
change, fsync and restore the file mode, and persist a source/authority/idempotency-
bound receipt. A conflicting retry, rebound artifact, prior consumer, stale bytes or
wrong contract MUST fail closed.

One `finalize-and-seal` command SHALL accept one exact retirement-readiness receipt,
revalidate its source digests, and derive rather than accept caller-selected paths for
the identity, preflight, startup/retirement receipts, complete public receipt chain,
sealed final workspace/event/evidence responses, source attestations and MICU
snapshots before creating any output. It SHALL reconstruct one source-bound
`aox_blank_world_attempt_bundle@3` with profile
`aox_public_conductor_bundle@3`, install it atomically without replacement, and
make the sealed source set independently reconstructable by the network-free
verifier. Any missing/extra/non-2xx/discontinuous command, identity drift,
noncanonical business closure, invalid task/report/finalization state, symlink,
source drift or partial output MUST leave no sealed bundle.

`seal-slot-failure` SHALL require exactly one of the post-child-ready
retirement-readiness receipt or the pre-child-ready supervision failure receipt.
It SHALL emit only current `aox_formal_slot_failure@2`, preserve
`acceptance_eligible=false`, `state_reusable=false`, zero attempt identities and an
unchanged MICU ledger for the pre-child-ready branch, and leave campaign decision to
the existing pure offline verifier/reducer.

Executable architecture qualification SHALL prove the retained composition by
constructing the production FastAPI application through the real composition factory,
using a deterministic model/runtime only as the injected agent boundary, calling real
public routes through the thin Host client, and writing/rereading file-backed SQLite
through the production V3 service plus canonical lane/scientific tool handlers. It
SHALL prove the first-message/bounded-drain/public-task-read/late-authority sequence,
the exact fresh-Host sandbox bootstrap and public ready status before session/model,
one assignee-bound late-created attempt, wrong-task and wrong-actor no-effect,
reassignment-before-finalizer rejection, and typed fault/export failure before a
matching closed attempt.
It MUST NOT substitute source inspection for production reachability. Deleted
diagnostic authority mint/consume, public scientific mutation/finalizer routes and
CLI, Core `create_attempt` compatibility, private admission argument projection,
`AttemptRunner`, legacy emitter, test builder, browser helper and automatic driver
surfaces SHALL remain absent. Test fixtures MAY construct evidence only from the tests
package and MUST NOT be a production caller.

#### Scenario: Preflight before Host startup
- **WHEN** one consumed exact slot and every pinned/current qualification input agree
- **THEN** preflight first passes the actual local sandbox launch guard, then creates only that slot's fresh root and immutable receipt, reports `preflight_complete_host_not_started`, and performs no Host, session, attempt, MICU, provider, remote runner, HPC workload or browser action

#### Scenario: Bootstrap one fresh supervised Host image identity
- **WHEN** the exact preflight image and SDK digests match one closed runner identity and the fresh SQLite image/session/workspace registries are completely empty
- **THEN** the same runner instance atomically installs and rereads one immutable cutover-grade Core image record, public `sandbox.workspace.status` is ready before session/model work, and child-ready/startup/bundle bind the exact bootstrap receipt

#### Scenario: Reject ambient or drifting sandbox bootstrap
- **WHEN** runtime identity is missing, malformed, mismatched or changes, any default or non-default image/session/workspace row already exists, receipt bytes drift, or registration/reread fails
- **THEN** supervised Host startup fails before ready/session/model/MICU/provider/HPC with no pull/build/install/tag/fallback and no partial registry commit

#### Scenario: Seal an exact public positive
- **WHEN** a policy-free Host has retired and the public chain proves one canonically closed positive attempt with the exact selected chain, passed 17-deliverable receipt, completed task board, published report, full events and final reads
- **THEN** the single finalizer seals one source-reconstructable `@3` bundle and the offline verifier reproduces it without SQLite, provider, runner or network access

#### Scenario: Preserve a same-turn late-bound lane handoff
- **WHEN** a claimed execution task begins from a source runtime signal with no lane, the assignee creates and binds its canonical lane during that turn, and the bounded turn emits exactly one durable successor
- **THEN** runtime settlement preserves the source signal's empty lane as historical evidence, records the task/agent/successor lane as the monotonic handoff lane, and permits the next explicit bounded drain under the same approved plan; any non-empty source-lane drift or multiple successor identities fails closed

#### Scenario: Keep a late-scope runtime command claim alive without replay
- **WHEN** a claimed command starts before a mutation scope, its executor opens the first attempt scope, and at least one lease heartbeat occurs before the executor returns
- **THEN** each post-transition heartbeat renews the exact claim under a terminal short command writer, the repository translates the exact mutation-guard rejection to a package-internal typed exception before worker classification, raw SQLite error text alone grants no retry, the command emits one matching terminal event without expired-claim recovery or scheduler replay, and transient contention or the typed scope-admission race remains bounded by the current lease while actual fencing still fails closed

#### Scenario: Seal a consumed formal slot before attempt creation
- **WHEN** one approved formal slot has been consumed, the supervised Host has settled, final public workspace/events/handoffs and MICU facts prove zero scientific attempts, and the earliest typed failure is source-bound
- **THEN** the public finalizer seals `aox_formal_slot_failure@2` with `closure_mode=public_host` and the pure offline verifier/reducer emits canonical `NO-GO` without creating or relabelling an attempt bundle

#### Scenario: Seal an actual Host bootstrap failure before child-ready
- **WHEN** the actual pre-claim launch guard passed, the claimed Host child then fails at sandbox bootstrap before registry mutation or child-ready, the parent proves the live process identity and full process-group retirement, the attempt root remains exactly fresh, and MICU before/after are identical
- **THEN** the parent seals `aox_supervised_host_pre_ready_failure@1`, `seal-slot-failure` emits `aox_formal_slot_failure@2` with `closure_mode=pre_child_ready`, and the pure offline verifier/reducer may emit canonical `NO-GO` without startup, supervision, public receipt, session or attempt artifacts

#### Scenario: Preserve an older unsealable pre-child-ready incident
- **WHEN** historical evidence contains only a wrapper failure and lacks the current live PID/PGID/start-time frame, exact fresh-root settlement or pre-ready receipt
- **THEN** it remains blocked and noncanonical; the current receipt, slot-failure or decision MUST NOT be retroactively backfilled or reused

#### Scenario: Reject an unclosed pre-attempt failure
- **WHEN** the final public reads, terminal handoff, supervision receipt, source digest, typed cause or zero-attempt proof is absent, mutable, substituted or inconsistent
- **THEN** no formal failure decision is sealed, the state remains an evidence blocker, and neither prose nor process retirement may manufacture a campaign terminal state

#### Scenario: Reject an incomplete or substituted conductor chain
- **WHEN** a command or sealed handoff is missing, duplicated, unbounded, semantically drifted, digest-only, privately substituted, test-built, cross-authority, cross-root, cross-attempt or followed by partial output
- **THEN** finalization fails before destination creation and none of those facts can be relabelled as a closed attempt or campaign decision

#### Scenario: Reject an unpinned or repeated formal entry before Host effect
- **WHEN** the second formal command omits or changes the preflight-pinned workflow reference, changes the canonical message bytes, or any later command attempts a second session message
- **THEN** the formal wrapper invokes no Host command, appends no receipt, reserves no response target, and creates no scientific or external effect

#### Scenario: Admit bounded cadence without restoring a fixed driver
- **WHEN** the conductor selects public drain bounds inside `1..100` with hidden ready-task enqueue disabled, including a cadence other than historical `1/8`
- **THEN** the command and offline evidence validators accept that bounded request; an out-of-range value, extra field or enabled hidden enqueue fails closed without choosing a replacement cadence

#### Scenario: Reject a historical execution contract for current actions
- **WHEN** an `aox_public_conductor_execution_contract@1` artifact is presented to the current formal wrapper
- **THEN** it remains historical read-only evidence and cannot issue a Host action or be silently promoted to `@2`

#### Scenario: Bind the formal authority only to the canonical execution task
- **WHEN** the single canonical pinned entry has produced one sealed bounded drain, its sealed terminal status and a public workspace containing exactly one execution task
- **THEN** the operator grant is accepted only for that task and any speculative, absent, duplicate or different task identity creates no scientific authorization or effect

#### Scenario: Bind every terminal handoff to the durable event
- **WHEN** a conductor submits a bounded drain and later reads its terminal status
- **THEN** both public responses are sealed and the terminal response exactly reproduces the unique `runtime.command.finished` event projection; an unsealed or digest-only status GET is not terminal proof

#### Scenario: Reject terminal handoff that arrives after frozen final reads
- **WHEN** the conductor seals workspace and event responses while a bounded drain is still nonterminal, and its terminal status or durable finished event becomes available only after either final-read receipt
- **THEN** the earlier responses remain stale and cannot be backfilled by later public or private state; retirement stays blocked until one sealed terminal status is followed by fresh sealed workspace and full event replay responses that include the exact `runtime.command.finished` projection

#### Scenario: Refuse unsealed operator retirement
- **WHEN** the operator requests retirement before every public receipt has one sealed response, every bounded drain has one matching terminal event, or post-mutation workspace/events have been sealed
- **THEN** the supervisor emits a typed retirement refusal and keeps the same Host active so the conductor can perform only the missing public reads; it does not infer or alter the business outcome

#### Scenario: Preserve caller strategy under formal public execution
- **WHEN** preflight has published the formal execution contract, its exact session and single pinned entry are closed, and the conductor selects an otherwise-valid later public Host CLI action
- **THEN** the formal command injects only the exact identity and evidence sinks, rejects rebinding, and forwards the selected later action unchanged without imposing a scientific tool sequence, drain count or completion policy

### Requirement: Three-attempt GO campaign
Local Live cutover SHALL be GO only after one formal acceptance campaign and one exact authority plan produce ordinal 1, 2 and 3 in that order: two consecutive independent positive attempts on the same exact-seven launch identity, followed by one `derived_required_artifact_blob_byte_flip@2` attempt that fails closed. Every session/root/authority-policy/receipt-chain launch identity MUST be non-empty and unique across the three slots; after the public task read and Host finalization, every canonical task/envelope/attempt/lane/admission-request/admission-idempotency/selection identity MUST independently be non-empty and unique across the three real control graphs. No outer launch artifact may supply those late-bound control identities. The fault MUST traverse the real exact-14 NCBI `proteins.fasta` through `aox_hmm_reference_set_selection@1` to derived `AOX_ref21.fasta`, consume the authority-bound public capability before its unique pending MAFFT consumer, and terminate that consumer with exact `artifact_blob_digest_mismatch`. Positive attempts MUST use different clean roots and MUST each prove exact three-task completion, publish a source-linked report, preserve a final answer and pass offline evidence verification. Diagnostic live runs, implementation completion, and non-live test completion MUST NOT be reported as Live completion before all three fresh formal bundles and the sealed reducer decision exist.

A verified formal slot failure short-circuits the current campaign to `NO-GO`; it never weakens the exact three-attempt requirement for `GO` and never counts as a positive or controlled-fault attempt.

#### Scenario: Campaign reaches GO
- **WHEN** attempts one and two independently satisfy every positive criterion and attempt three seals `aox_fault_negative_state_closure@1` proving execution failed/blocked/cancelled, reporting did not complete or publish, no ready/published report or draft exists, no alternate target consumer succeeded, no downstream fixed deliverable exists, durable events/conversation/final failure agree, and all fault-attempt MICU usage is attributed to this campaign
- **THEN** the campaign emits a sealed GO decision referencing all three attempt digests

#### Scenario: Any positive attempt fails
- **WHEN** either positive attempt is degraded below required quorum, incomplete, unverifiable, or scientifically invalid
- **THEN** the campaign remains NO-GO and reports the smallest evidence-backed blocker without weakening thresholds

### Requirement: Public-only Codex test conductor and canonical approval proof
AOX live test orchestration SHALL be performed by a Codex test conductor outside
the product runtime. The conductor SHALL use only the public Host API/CLI for
session creation, one entry message, explicit bounded runtime drains, sealed terminal
status reads, canonical task reads, late-bound authority grant, compact pending-
approval reads, approval resolution, workspace reads and event replay.
It MUST NOT read or write SQLite directly, call provider/runner/HPC internals,
forge receipts, bypass approval, synthesize wakeups, infer task completion from
runtime idleness, or continue through an automatic drive-until-terminal,
no-wakeup, rollover or recovery policy. Each next public action SHALL be an
explicit test decision within the approved authority.

Host SHALL retain canonical authority for task/attempt/report state, approval,
leases and fencing, unknown/external effect classification, sandbox/provider/HPC
admission, continuations, artifact catalog truth and isolation. Runtime drains
remain explicit commands and MUST NOT write business terminal state merely
because a command is idle, bounded, exhausted or has no wakeup. Canonical wake
facts and failed ToolResults expose source-bound constraints to the agent and
conductor without selecting retry, repair, stop or success.

Every approval SHALL be resolved only by an explicit conductor action through the
public Host API/CLI when the approved test plan authorizes that exact action. The
receipt chain, final workspace, event replay and closed-attempt export MUST bind
the same approval, operation, sandbox continuation and Host process identities.
No policy-free shell may auto-approve an operation, and no browser-specific helper,
screen observation or private resolve call is required or accepted as a GO
substitute.

The append-only evidence shell MAY seal canonical `openzyme_public_api_receipt@2`
records, the final public
workspace snapshot, full event replay, process-supervision retirement receipt,
artifact roots and MICU snapshots. It MUST preserve request/response semantic
digests and typed failures, but MUST NOT label the business state or campaign
decision. The offline attempt verifier alone determines whether a bundle satisfies
its positive/fault contract, and the offline campaign reducer alone derives GO or
NO-GO from two independent verified positive bundles followed by one verified
fault bundle.

Provider and runner calls that fail before operation admission SHALL be rejected by
Host pre-admission validation and sealed as source-bound typed `no_effect` facts.
The terminal SandboxRun wrapper, failed ToolResult and canonical owner wake SHALL
retain the same cause binding. Missing, duplicate, cross-source, cross-attempt or
unknown-effect bindings remain fail-closed, but neither Host nor the shell may turn
a safe failure into an automatic retry or a business terminal.

#### Scenario: Conduct one bounded public step
- **WHEN** the Codex tester has read the current public workspace, event replay, pending approvals and the receipt for the preceding command
- **THEN** it may choose one authorized public message, drain, approval resolution or stop action; the repository contains no AOX loop that chooses or repeats that action automatically

#### Scenario: Preserve canonical Host safety
- **WHEN** a public command encounters an active lease, stale fence, pending approval, unknown effect, external effect, unretired writer or isolation violation
- **THEN** Host fails or suspends according to the canonical typed contract, and neither Codex nor an evidence/process shell can override that result

#### Scenario: Preserve a Host-local pre-admission causal chain
- **WHEN** a sandbox provider or HPC request carries an invalid Host-owned output/stage authority
- **THEN** no controlled operation or external dispatch is admitted, Host seals the exact `no_effect` cause, the non-completed sandbox run returns a failed ToolResult, and canonical wake facts retain the same source-bound cause and wrapper

#### Scenario: Verify explicit public approval without an automatic driver
- **WHEN** an attempt reaches a formal approval covered by the exact approved test plan
- **THEN** the conductor resolves that approval once through the public Host API/CLI, seals the command receipt and later public reads, and the offline verifier rejects automatic resolution, identity drift, stale receipt or missing same-operation continuation

#### Scenario: Keep process supervision non-authoritative
- **WHEN** an attempt Host or sandbox child exits, times out or requires forced retirement
- **THEN** process supervision proves only the bounded local lifecycle and root-read gate; it does not claim remote-effect cancellation, SQLite/business closure, artifact completeness or GO

#### Scenario: Derive GO only offline
- **WHEN** the conductor has stopped and sealed three fresh formal bundles
- **THEN** each bundle is checked without live I/O and only the campaign reducer may emit GO; conductor prose, an implementation commit, diagnostic evidence, process exit and Host task labels cannot substitute for the verified reducer inputs

### Requirement: Prelive qualification handle continuity is deletion-first
Before any new numbered AOX launch preparation, the Codex conductor SHALL issue at
most one full architecture-qualification command for the canonical checkout. When
`functions.exec` wraps `exec_command`, its yielded `cell_id` owns only the JavaScript
`outer cell` lifecycle and SHALL be resumed only with `functions.wait`; the nested
`exec_command` owns the `inner session`. The wrapper MUST propagate the complete
nested `structured result` and MUST NOT project only `.output` or discard
`session_id` / `exit_code`. If the inner command yields a `session_id`, the conductor
MUST resume that session only with `write_stdin` until its structured result returns
the real `exit_code`; terminal state of the `outer cell` is not terminal state of the
inner command. If the inner handle was not exposed or is no longer recoverable, the
conductor SHALL perform only read-only process/output inventory, classify the prelive
step as `blocked`, and stop. It MUST NOT `relaunch` an equivalent qualification
command, create a recovery output, retry with another parent, or adopt a focused
recheck. Any subsequent `late report` remains subject to `non-adoption` and cannot
authorize Host, live, MICU, provider, HPC, or Chrome work.

The qualification owner SHALL validate the canonical checkout-external output target
and any requested mainline sidecar before collection, harness self-tests, or scenario
execution. It SHALL hold one canonical-checkout-bound kernel lock, acquired
nonblockingly and shared across admission, diagnostic, and premerge modes and every
output path. An invalid target MUST return
`architecture_qualification_output_invalid`; an already-held checkout lock MUST
return `architecture_qualification_run_active`. Lock loss on process death SHALL
release admission without a recovery record, lock stealing, retry queue, observer, or
product-state mutation. Final report and sidecar publication MUST revalidate the
target, remain no-replace, and fsync their file and parent boundaries.

#### Scenario: Reject duplicate qualification before work
- **WHEN** one canonical checkout already has any qualification mode running and a second command targets the same or another output through the real path or a symlink alias
- **THEN** the second command returns exact `architecture_qualification_run_active` before collection, harness, scenario, report, sidecar, Host, session, live or external work

#### Scenario: Reject an invalid output before work
- **WHEN** the requested output or sidecar is relative, noncanonical, existing, symlinked, inside the checkout, or has a missing/aliased parent
- **THEN** the command returns exact `architecture_qualification_output_invalid` before collection, harness or scenario execution and creates no replacement/recovery output

#### Scenario: Stop after losing the yielded handle
- **WHEN** a qualification command yielded an execution handle but that exact handle can no longer be resumed
- **THEN** the Codex conductor inspects only current processes and target existence, marks the prelive conductor blocked, does not issue an equivalent command, and does not adopt any partial/recheck/recovery state or later report

#### Scenario: Resume the nested command owner to a real terminal result
- **WHEN** `functions.exec` resumes its `outer cell` with `functions.wait` and the nested `exec_command` structured result yields an inner `session_id`
- **THEN** the conductor preserves the complete structured result and resumes only that `inner session` with `write_stdin` until it returns an `exit_code`; outer-cell completion or `.output` alone cannot prove command termination

### Requirement: Atomic AOX final deliverable finalization
The exact 17 normalized AOX deliverables SHALL enter the artifact catalog only
through one `aox_final_deliverable_bundle@1` Host finalization request. The request
SHALL bind the current session, execution task, scientific attempt, selected chain,
workspace, sandbox run, sealed source snapshot and exact typed calculation
receipts. Before any catalog mutation, Host SHALL prevalidate every draft and run
the same production AOX scientific validator used by eval and offline verification.
The installed `aox_final_deliverable_normalization@1` calculation SHALL emit
`aox_final_deliverable_normalization_result@1`; that calculation result MUST NOT
be confused with or substituted for the Host-issued validation receipt.
Only a passed complete bundle MAY be committed, and the 17 artifact occurrences
plus one deterministic immutable `aox_final_deliverable_validation_receipt@1`
document SHALL share one short repository transaction. Any validation, metadata,
path, digest, calculation, serializer, catalog-write or receipt-write failure SHALL
leave zero normalized artifact occurrences and no receipt for that request.

The receipt SHALL close over all source identities, exact 17 artifact ids and
digests, calculation ids/contract/implementation digests, validator digest, bundle
digest and ordered typed validation result. It SHALL be replay-idempotent only for
the identical preimage. Public projections MAY bound the error list but MUST retain
the earliest typed cause and its digest. Unreferenced immutable content-addressed
blobs created during a failed transaction are not catalog truth and SHALL grant no
acceptance authority.

#### Scenario: Reject the r65 zero-candidate bundle atomically
- **WHEN** motif scoring proves 516 target candidates but the candidate FASTA draft is zero bytes or its dependent tables/report claim healthy empty
- **THEN** prevalidation reports the candidate mismatch as the earliest typed cause, writes none of the 17 normalized artifact rows, writes no validation receipt, and leaves attempt/task/report state nonterminal

#### Scenario: Roll back a partial catalog failure
- **WHEN** the Nth artifact catalog write or validation-receipt write fails after earlier writes in the same finalization transaction
- **THEN** the transaction rolls back all 17 catalog occurrences and the receipt, and a later retry must present the identical complete source-bound preimage

### Requirement: Validation receipt terminal gates
The system MUST require AOX formal `scientific.attempt.close`, execution
completion, report delegation, report publication and reporter completion to
each re-read one exact passed
final-deliverable validation receipt for the current attempt and selection.
Execution and reporter completion SHALL carry `document:<receipt_id>` in their
owner-authored evidence refs. Missing, duplicate, stale, failed, cross-session,
cross-task, cross-attempt, cross-selection, cross-workspace, cross-run,
cross-source, artifact-drift or calculation-drift receipts SHALL be rejected before
dispatch as typed `no_effect` failures. The policy SHALL NOT synthesize a receipt,
register missing artifacts, retry a calculation, complete a task, close an attempt,
delegate a replacement task or publish a report.
Report delegation, publication and reporter completion MUST additionally observe
the receipt-bound execution task in `completed`; a passed receipt alone MUST NOT
permit early report handoff.

#### Scenario: Prevent false terminal progression
- **WHEN** a formal AOX run has files or individually registered artifacts but no exact passed source-bound receipt
- **THEN** attempt closure, execution completion and report handoff all fail closed without business-state mutation

### Requirement: Retired closure-stage diagnostic non-adoption
The current runtime MUST NOT expose the completed closure-stage live
diagnostic/authority/reconstruction/CLI subsystem through a runner, authority
mint, run class, command, tool-policy
exception or runnable operator documentation because its historical master-only
companion-response contract cannot satisfy the current assignee-owned response-free
close contract. Migration `035`, historical SQLite tables/rows, sealed evidence
readers and explicit formal non-adoption validation SHALL remain.

#### Scenario: Reject historical closure-stage adoption
- **WHEN** a historical closure-stage authority, root, result, receipt or artifact is presented to a current formal cutover path
- **THEN** it is rejected as non-adoptable and cannot satisfy calculation, finalization, closure, campaign or GO evidence

### Requirement: Bounded composite workspace and approval mutation projection
The session workspace is a collection read model. Every Artifact occurrence in `workspace.artifacts`, `artifact_index`, `activity_feed`, and capability projections MUST use the same deterministic bounded item contract as `artifact.list`: exact canonical metadata remains unchanged in the Artifact row and readable through `artifact.get`, while the composite response retains short identity fields plus `artifact_list_metadata_summary@1` / `artifact_list_record_summary@1` digest, count, size, omission, and paging hints. A large accession, sequence-digest, page-digest, or identity-mapping collection MUST NOT be copied into any of those workspace branches. Activity-event backfill inside a mutation MUST build only the sanitized activity projection rather than recursively constructing the entire workspace. An approval resolve MAY still return the bounded workspace command result, but its SQLite write transaction MUST NOT scale with repeated unbounded artifact metadata projection.

#### Scenario: Coordinate approval after real-scale provider metadata
- **WHEN** a formal session has tens of thousands of UniProt identities and one or more multi-megabyte canonical Artifact metadata objects while a controlled operation requests approval
- **THEN** the compact pending-approval read remains independent of Artifact metadata size, repeated cutover polls do not GET the workspace, resolve preserves the same continuation identity, and the bounded final workspace exposes omission digests/hints without deleting or truncating the catalog metadata

### Requirement: AOX current admission consumes current source-causal qualification only
AOX pin, preflight, launch, evidence and reducer paths MUST accept only a verified `openzyme_v3_architecture_qualification_report@3` and matching `aox_architecture_qualification_receipt@3`. The receipt MUST bind the exact report schema, lock-admission source identity digest, run-evidence digest, `owner_constraint_registry_digest`, and `transformation_results_digest`; full admission MUST include the independent strategy-neutrality and world-fidelity families rather than treating one scripted reachability path as exhaustive proof. Historical `openzyme_v3_architecture_qualification_report@1`, `openzyme_v3_architecture_qualification_report@2`, `aox_architecture_qualification_receipt@1`, and `aox_architecture_qualification_receipt@2` MAY remain readable only for frozen bundle compatibility and MUST NOT authorize a current campaign or be silently upgraded. A qualification terminal failure, source-contract drift, or lost conductor handle MUST NOT trigger an equivalent command relaunch, report adoption repair, or a new numbered r-series run.

#### Scenario: Reject historical qualification at current preflight
- **WHEN** a current pin, preflight or launch receives a structurally valid historical report/receipt `@1` or `@2`
- **THEN** it fails before root/session/effect creation with version unsupported and does not upgrade, reseal or adopt the evidence

#### Scenario: Stop after one source-bound qualification failure
- **WHEN** a fresh qualification report seals a source drift, collection failure, harness timeout or scenario execution failure
- **THEN** the conductor preserves that terminal report, performs no equivalent relaunch or recovery adoption, and requests an independently approved repair before any fresh goal or rNN

### Requirement: Ordinary known-effect failure has one durable settlement
For a nonterminal task, an agent- or harness-authored ordinary failure MUST have exactly one durable settlement when its external effect is `no_effect`, `effect_known`, or `terminal_known`.
That settlement is one immutable `FailureObservation` and MUST be available to the next model
decision. `agent_can_replan`, `agent_can_retry`, or `terminal` recoverability by
itself MUST NOT create `failure_reconciliation_required`, task attention, a
synthetic recovery signal, or a second recovery state machine. The failure MUST
NOT change the task business status or authorize a retry.

System failure, `reconciliation_required`, `dispatch_in_doubt`,
`reconcile_required`, `authorization_required`, and `runtime_retry` MUST retain
their precise runtime attention semantics. They MUST NOT be collapsed into an
ordinary failure or a generic reconciliation label.

#### Scenario: Continue from one task-bound ordinary rejection
- **WHEN** a schema-valid but domain-invalid tool call is rejected on an existing nonterminal task with a known effect boundary
- **THEN** the exact source-bound failure reaches the next model decision, the task remains nonterminal, no external effect is recorded, and workspace runtime state contains no second reconciliation warning or task attention for that failure

#### Scenario: Preserve a true runtime boundary
- **WHEN** a task-bound failure is system-owned, effect-ambiguous, reconciliation-required, authorization-required, or runtime-retry-owned
- **THEN** runtime state retains the corresponding precise attention code without changing task business status or silently performing recovery

### Requirement: Workflow and knowledge document registries remain distinct
`WorkflowRegistry` MUST own exact workflow selection, manifest digest and
requirement validation, and selected-manifest prompt loading. `DocumentRegistry`
MUST own only registered knowledge documents addressed by `doc_id` or registered
knowledge path. A selected prompt MUST state that its manifest is already loaded,
that the manifest path is provenance-only, and that `docs.read` accepts the
manifest's `knowledge_refs` rather than the workflow ref or manifest path.

When `docs.read` receives a `workflow:` selection ref or a `*.workflow.json`
manifest path that is not a registered knowledge document, it MUST return a
factual registry-owner hint. It MUST NOT search for, guess, or load a replacement
manifest, and ordinary missing knowledge-document errors MUST remain compatible.

#### Scenario: Reject a selected manifest as a knowledge document
- **WHEN** an agent sends the selected `workflow:` ref or manifest provenance path to `docs.read`
- **THEN** the error identifies `WorkflowRegistry` as manifest owner and directs the agent to registered `knowledge_refs` without loading a fallback

#### Scenario: Read an exact workflow knowledge reference
- **WHEN** the agent supplies a manifest-bound knowledge `doc_id`, version, and digest to `docs.read`
- **THEN** `DocumentRegistry` returns exactly that registered document and does not re-resolve the workflow selection

### Requirement: Artifact missing-path errors expose bounded locality
When control-plane `artifact.get` cannot resolve a requested dot/index path, its failure payload MUST retain the existing `error` and
`available_top_level_paths` fields and MUST additionally return the deepest
`resolved_prefix`, exact `missing_segment`, type of the resolved parent, and a
bounded `parent_read_hint` that reads only that parent or artifact root. It MUST
NOT inline the parent value, expose a Host-private locator, infer an arbitrary-key
typed path segment, or change existing successful path/page semantics.

#### Scenario: Identify a missing nested child
- **WHEN** a valid artifact and valid prefix are followed by a nonexistent dict key or list index
- **THEN** the error identifies the valid prefix, missing segment and parent type and provides an executable bounded hint for the parent while preserving top-level choices

#### Scenario: Preserve the current resolver boundary
- **WHEN** the missing child would require arbitrary dictionary-key addressing beyond the current safe dot/index grammar
- **THEN** the tool reports locality only and does not invent an escaped or typed path, return the parent value, or claim that arbitrary-key addressing is implemented

### Requirement: Preparation ledger snapshot uses one cache-independent public invocation
The preparation conductor MUST read the cumulative MICU ledger through the current canonical checkout's installed
public console script `.venv/bin/openzyme-aox-cutover ledger --path <literal-ledger-path>`. The console owner MUST
remain the `[project.scripts]` mapping `openzyme-aox-cutover = "openzyme_host_api.aox_cutover_cli:main"`; the
conductor MUST NOT replace it with a private import or handler call. Before issuance, the conductor MAY only verify
that the console script exists, is executable and is bound to the same checkout, and MUST read and validate
`ledger_path` once from the exact pinned `aox_cutover_launch_profile@1`. The formal argv MUST carry that value as a
literal argument and MUST NOT use `jq`, shell substitution, `zsh -fc`, ambient re-resolution, or an in-command profile
lookup.

The ledger invocation MUST run once in the ordinary sandbox without `uv`, `--output`, or escalated sandbox permission.
If the entrypoint or pinned literal path is unavailable before issuance, the conductor MUST stop with
`ledger_execution_count=0` and MUST NOT probe the ledger or switch launcher, cache, environment, permission, path, or
output. Once the command is actually issued, any nonzero wrapper or CLI terminal MUST consume the one invocation and
stop the preparation. The conductor MUST NOT reissue with a changed `.venv` / `uv`, cache, environment, sandbox
permission, launcher, path, or output, and MUST NOT adopt late stdout or a late snapshot. Resuming the exact yielded
outer-cell or inner-session handle to obtain its complete structured result is not a retry; a lost handle fails closed,
and only the exact invocation's `exit_code=0` and same-result safe snapshot MAY continue preparation. These rules MUST
NOT alter the existing `uv --project ...` plus pre-authorized escalated execution contract for Podman-transitive `pin`
and formal `preflight`.

#### Scenario: Stop before an unavailable ledger invocation
- **WHEN** static pre-issue inspection cannot prove the public console binding or cannot obtain the literal path from the exact pinned launch profile
- **THEN** preparation stops as an operator/platform blocker with `ledger_execution_count=0`, no ledger probe, no fallback, and no product state or effect

#### Scenario: Freeze the first issued nonzero ledger command
- **WHEN** the one direct ledger command has been issued and its wrapper or CLI returns a nonzero terminal result
- **THEN** its execution count is one, preparation stops without changing launcher/cache/environment/permission/path/output, and any later stdout or snapshot is non-adoptable

#### Scenario: Resume only the exact ledger handle
- **WHEN** the exact direct ledger invocation yields an outer cell or inner process session
- **THEN** the conductor resumes only that handle until its complete structured result and real exit code, without issuing another command or treating platform escalation as retry authority
