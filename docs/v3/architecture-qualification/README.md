# V3 可执行架构资格验证

状态：deterministic qualification 与 AOX admission integration 已实现；每个 tracked
correction 都会使前一份 report 失效。current admission 使用 invariant registry `@2`、
owner/constraint registry、qualification report `@3` 与 AOX receipt `@3`，并强制消费独立的
strategy-neutrality/world-fidelity proof。历史 rNN 结论和不可复用状态只见
[aox-hmm-blank-world-cutover.md](../aox-hmm-blank-world-cutover.md)；本页不把它们复制为operator truth，
也不预先命名下一 rNN。

## Authority boundary

本目录拥有 repository/operator qualification contract，不拥有 session、task、lane、
approval、agent、execution 或 campaign 产品状态，也不替 agent 选择科学策略。依赖方向固定为：

```text
V3 稳定合同 + 当前实现 + invariant-registry.json
                    -> non-live production-composition scenarios
                    -> canonical qualification report
                    -> pure AOX admission verifier
```

资格 runner 通过真实 `HostApiDependencies + create_app()` composition、file-backed SQLite、
当前 workers、sandbox Host gateway、artifact roots、events 与 public projections 观察
canonical state/effect。只有 registry 声明的外部端口可使用 deterministic non-cutover
adapter。report/receipt 永不成为产品真状态；通过资格验证也不会启动 AOX。

## Supported profile and exclusions

首版且当前唯一支持的 profile 是 trusted Host 上的
`local_single_process_file_sqlite@1`。它只证明该 profile 登记的单进程、file-SQLite
架构不变量，不推导 shared writer、multi-process、multi-Host、distributed operation、
adversarial verifier、signed CI provenance 或真实 provider/HPC/Chrome availability。
扩张这些结论必须新建 versioned profile、registry、matrix 与 attestation policy。

## Canonical inputs and implementation

- `invariant-registry.json` 是 closed canonical
  `openzyme_v3_architecture_invariant_registry@2` authority，并绑定
  `owner-constraint-registry.json` 的 current canonical digest。owner registry 只描述架构
  ownership/consumer/forbidden edges，不进入 product runtime。
- `registry-schema.md` 定义 byte、field、reference 与 selection closure。
- `p0-closures.json` 是 canonical closed-P0 sidecar，绑定 baseline digest、原 red
  scenario、focused change 与 ancestor closure commit；pure verifier 会重算，不能人工
  把当前 red/unproven invariant 标记为 closed。
- `apps/openzyme-host-api/tests/architecture_qualification/` 拥有 stable scenario id 和
  production-composition deterministic matrix。
- `scripts/v3_architecture_qualification.py` 是thin repository CLI；
  `scripts/architecture_qualification_runner.py`在产品无关`scripts/test_gate`包之外负责
  qualification编排，并只通过`scripts/test_gate/runner.py`的单一bounded process owner执行
  collection/harness/scenario。
  `scripts/check-v3-architecture-qualification.sh` 清除 live credential 并
  禁止 live opt-in。
- test-gate 的 `mainline_authoritative` runner 可以为同一 invocation 传入
  mainline-private sidecar request，记录 exact harness/scenario node outcomes，并绑定
  plan、source、environment 与 canonical report digest。两参数 shell command、report
  schema、publication、pure verifier、admission 和 AOX consumer 保持不变；sidecar 不是
  admission artifact，也不能跨 invocation 复用。
- `openzyme_host_api.architecture_qualification_report` 不运行 pytest、不写产品状态，
  生成/验证current closed `openzyme_v3_architecture_qualification_report@3`；历史`@1/@2`仅只读加载。
- `openzyme_host_api.aox_architecture_qualification` 生成 AOX launch/evidence 消费的
  current closed `aox_architecture_qualification_receipt@3`；历史`@1/@2`不得进入current admission。

registry 闭合十二个 family：wire contract、authority composition、identity semantics、
reconciliation、bounded terminal convergence、restart/fencing、supervisor progress、
operator retirement、boundary scale、evidence projection、strategy neutrality 与 world fidelity。
后两类分别通过合法trace transformations证明generic Harness不规定tool order/handoff，通过
source-bound causal projection证明earliest typed cause在下一次decision前可见且无synthetic fallback。
world-fidelity 的 ordinary-rejection witness 必须绑定一个真实 nonterminal task：同一 task 上
schema-valid、domain-invalid 的 effect-known action 产生唯一 `FailureObservation`，下一次模型决策读取
exact error/source/effect facts，task 仍 nonterminal、external effect 为零且
`workspace.runtime_state` 不得再生成 `failure_reconciliation_required` / task attention。独立负控继续
证明 system、unknown-effect/reconciliation、authorization 与 runtime-owned retry 仍有精确 attention。
scripted AOX scenario只是一条reachability witness，不能独立满足current admission。AOX admission/receipt
及 schema-disjoint run-class closure 场景归入 evidence projection。后者在零外部 effect
下以真实 file-backed SQLite 证明 full-path diagnostic one-slot
plan/consumption/root/decision，以及已退役 closure-stage raw run class、attempt-id family
和 historical evidence 都不能被 formal publisher/consumer/blank-world
root/verifier/reducer 接纳，即使伪造相同 plan digest。该 negative gate 使用 frozen
literals，不依赖或恢复已删除的 closure-stage production modules。
当前 `evidence-projection.aox-run-class-disjoint-closure` scenario 同时闭合
`evidence-projection.aox-run-class-disjoint`与
`evidence-projection.aox-fresh-host-sandbox-bootstrap`，并以
`aox_public_conductor_runtime_qualification@1` observation收口真实 production
composition：场景通过`HostApiDependencies/create_app()`组成actual FastAPI应用，以current
conductor execution contract `@4`和thin Host CLI调用public route，使用file-backed SQLite和只注入agent边界的deterministic
model/runtime先调用production Host bootstrap，在session/model前证明全空registry、唯一immutable
image row、source receipt与public ready status，再建立exact session、唯一canonical message + pinned
workflow entry、首个非写死`1/8`的bounded drain、sealed terminal、唯一execution-task read与专用
late-bound authority。缺pin和第二条message必须在Host调用、receipt append和response target消费前拒绝；
legacy execution contract `@1/@2/@3`不得驱动current action。execution assignee随后经production lane/scientific tool handler
从`scientific.attempt.inspect`读取真实envelope并创建lane/admission；不存在model envelope side
channel或master lane fixture。wrong task与wrong actor在零attempt状态被拒绝，Host internal finalizer才
生成late-bound identity，独立reader再证明持久化。场景还证明terminal response与唯一
`runtime.command.finished` exact一致，fault与closed export在不匹配状态typed fail closed，且
不调用private service、不手工组装`ToolRegistry`、不直接写canonical truth或合成receipt。
同一场景把production `RuntimeCommandWorker` lease收窄为1秒；只读检查发现canonical attempt scope后，
真实Host executor等待由原production `RuntimeCommandRepository.renew_lease`成功返回触发的Event，确保file
SQLite至少发生一次scope-open后的authorized heartbeat，不再依赖固定0.4秒sleep。observer只在原方法成功后
发出进程内测试信号，不改变repository返回值或canonical truth；独立reader必须看到绑定exact command id的
`lease-heartbeat` writer全部terminal、对应command真实处理1条signal、terminal event闭合且全session没有
`runtime_command_claim_expired`。该test-only synchronization gate不替换Host service、scheduler、repository、
public route或receipt，也不把non-live witness升级为cutover evidence。
同一场景用test-only Event经thin CLI证明真实`claimed -> terminal -> fresh reads`且opaque locator不参与handoff；邻近fixture覆盖`0/1/7/254`，不引入sleep、poll、replacement、observer或产品状态。
场景还检查diagnostic authority、public generic
scientific mutation/finalizer、automatic runner/observer及其CLI/client/dead Core入口确实缺席，
而非靠一个source symbol宣称positive reachability。当前场景同时要求 public conductor 暴露
`public-host`、`grant-task-authority`、`seal-conductor-state`、`seal-slot-failure`、
`verify-slot-failure`：preflight 必须发布source-bound execution contract `@4`，formal public command
先固定exact single entry和真实late-bound grant，再只绑定identity/receipt/response而保留后续caller
策略；退休前 readiness 必须重验 one-to-one response、bounded handoff 与最终 public reads。缺少该
readiness 时 supervisor 拒绝操作员退休并保持原 Host 可读。pre-attempt formal failure 的 finalizer、
纯离线 verifier 与 reducer 仍须具备 production reachability；其 source-bound 重建、零 attempt、
append-only、篡改与 symlink 负向控制由邻近 focused tests 闭合。registry 以
`late-bound-lane-handoff`、`late-scope-command-heartbeat`、`nonterminal-response-label-misread`、`public-conductor-response-unsealed`、
`operator-retirement-readiness-missing` 和 `pre-attempt-formal-failure-unsealed` fault points 跟踪这些
边界，不能用 synthetic attempt bundle、手工 response path 组合或文字 `NO-GO` 替代。
fresh-Host invariant使用既有`admission-bypass`、`false-success`与`unverifiable-evidence` P0 trigger；
本repair不伪造新的P0 closure sidecar记录，缺失/malformed/mismatch/preexisting/duplicate/drift/tamper/
rollback controls必须由同一tracked scenario与focused tests实际为green。
每个场景都有 finite step、tick、state/event、effect 与
wall-clock budget。skip、xfail、missing collection、timeout、budget exhaustion 或证据不完整
只能得到 `violated|unproven`，不能得到 pass。

## Modes and commands

输出目录必须是 checkout 外、caller 明确选择且尚不存在的绝对路径；publication 使用
canonical bytes、append-only/no-replace 与 directory fsync。

runner 在任何 pytest collection、harness self-test 或 scenario 前统一验证 primary output
directory 与 optional mainline sidecar：路径必须 absolute、lexically canonical、target absent、
parent 是 existing real non-aliased directory，且 target 位于 checkout 外。失败稳定返回
`architecture_qualification_output_invalid`，不会先跑 matrix、创建 recovery parent 或换一个
output。获得 run admission 后会立即重验，final publication 再重验并保持 mkdir/file
no-replace、file/directory/parent fsync；mid-run target/parent race 不能覆盖既有 bytes。

同一 canonical checkout 的所有 `diagnostic|premerge_subset|admission` 和所有 output 共用一个
kernel-held nonblocking single-flight。lock key 由 canonical checkout root 的 local
device/inode 组成，checkout symlink alias也会冲突；private per-UID lock file以 no-follow/
close-on-exec方式打开并在 report pure verification及mainline sidecar publication结束前持续
持有 `flock(LOCK_EX|LOCK_NB)`。竞争者立即得到
`architecture_qualification_run_active`。lock file不记录owner或lifecycle，不产生wait/retry/
observer/recovery authority；fd close或process crash由kernel释放。

operator/Codex一次只能发出一条full command，并区分两层执行owner。`functions.exec` yield的
`cell_id`只拥有`outer cell`的JavaScript生命周期，只能用`functions.wait`恢复；nested
`exec_command`才拥有`inner session`。outer wrapper必须完整传播nested `structured result`，禁止只
投影`.output`或丢弃`session_id`/`exit_code`。若inner command yield `session_id`，只能用
`write_stdin`恢复该session，直到structured result返回真实`exit_code`；`outer cell` terminal不能
替代inner command terminal。inner handle未暴露或失联时只允许只读检查process和target，立即把prelive
step记为`blocked`并停止，不得等价`relaunch`、focused recheck或创建recovery output；随后出现的
`late report`仍是`non-adoption`停后观察。这条停止规则不改变single-flight、full matrix、bounded
timeout、pure verifier、mainline sidecar non-adoption或live fail-closed。

lock admission完成后立即采样唯一source identity。runner在collection前后、harness后、每个selected
scenario前后及publication前重新采样，并封存phase、observed digest与是否匹配admission。每个实际
process生成source-bound bounded receipt，包含safe command、outcome/exit、stdout/stderr digest、
byte count与最多4 KiB tail、spawn error、timeout及TERM/KILL事实；不存在第二个Host-owned `Popen`
executor或late source truth。

process phases必须是`collection → harness → selected scenarios`的exact prefix。collection closure、
harness、scenario evidence或source revalidation出现首个terminal failure后立即停止；`run_failure`
保留该earliest typed cause，`not_run_scenario_ids`闭合余下selection。report不再为未执行scenario
合成fallback result，也不把一次harness timeout扩张为全registry GAP/P0 cascade。健康current report
必须闭合完整process/source chain，`run_evidence_digest`同时绑定terminal source、phase observations、
receipts、earliest cause与not-run set。

current report/payload schema为`@3`，AOX receipt也为`@3`并额外绑定report schema、source identity、
run-evidence、owner-registry与transformation-results digest。历史report/receipt`@1/@2`只允许frozen evidence reader显式只读；pure
current verifier、pin、preflight、launch和reducer都返回version unsupported。operator-retirement
eligibility/quarantine/unknown-effect由pure semantic calculation决定；suite仅保留一个秒级宽限的
真实process-group containment probe，避免亚秒real-clock threshold成为业务policy。

```bash
qualification_parent="$(mktemp -d /tmp/openzyme-v3-qualification.XXXXXX)"
./scripts/check-v3-architecture-qualification.sh \
  diagnostic \
  "$qualification_parent/diagnostic-report"
```

`diagnostic` 可绑定 dirty worktree，用于 GAP/P0 定位，但始终
`admission_eligible=false`。`premerge_subset` 运行 registry/schema/selection closure 与
deterministic P0-critical subset，由当前 optimized `./scripts/check-mainline.sh` 作为同一
invocation 的 stricter owner 调用；即使全部 green 也不能 admission。

在 optimized mainline contract 中，`premerge_subset` 拥有 exact `Qh ∪ Qs`。只有同一
invocation、同一 source/environment、report 经纯验证且每个 invariant outcome 为 proven
pass 的 sidecar 才允许 general pytest 从 `G` 中减去这些节点。缺失、mismatch、timeout、
skip/xfail、report drift 或 prior-invocation sidecar 都会在 general 前失败；runner 不会
用 ordinary pytest fallback 把 qualification failure 重新解释为 green。

`./scripts/check-mainline.sh --forced-serial` 仍使用同一个 qualification owner、sidecar、
canonical report 与 pure verifier；它只把 general eligible partition 固定为一 worker。
`scripts/check-mainline-legacy.sh` 仅用于 rollback comparison，直接调用不会生成当前
authority receipt，也不改变本页 admission/AOX 边界。

完整 qualification 的 repository test-gate 会通过 Starlette `TestClient`、AnyIO 与 asyncio 使用
本地跨线程 `socketpair`。Codex 普通命令 sandbox 可能拒绝该本地 IPC，使测试在 Host lifespan
启动前等待；这属于操作员执行环境不满足，不是 qualification 或产品缺陷。获得 full admission
授权后，操作员必须在发出命令前闭合 clean HEAD、canonical checkout、fresh checkout 外 output 与
single-flight，并把下列唯一公开命令第一次且仅一次以
`sandbox_permissions=require_escalated` 运行。该权限只覆盖本地 IPC、正常包 cache 与 non-live
子进程监督，不覆盖网络或 live effect。升级调用只包含公开脚本、`admission` 与已生成的字面量 output
path，不内联 environment、管道、重定向、命令串联或持久 prefix approval；发出前还必须核对脚本
仍固定 non-live 环境、清除 live credentials 且拒绝未声明外部端口。不得先在普通 sandbox 试跑，不得以替代 `UV_CACHE_DIR`、
raw pytest、`socketpair` 探针、另一个 output 或 terminal 后的等价重发充当恢复。若平台在进程启动前
拒绝所需权限，应以操作员环境 blocker 停止，保持执行次数为零，不生成 qualification report。

提交全部变更并确保 canonical checkout 完全 clean 后：

```bash
qualification_parent="$(mktemp -d /tmp/openzyme-v3-admission.XXXXXX)"
./scripts/check-v3-architecture-qualification.sh \
  admission \
  "$qualification_parent/admission-report"
```

只有独立重验后仍精确绑定相同 clean HEAD、当前 registry、完整 scenario/test manifest、
runner/verifier implementation、全 satisfied invariant 与零 open P0 的 full admission report，
才能允许后续 AOX preparation。

## GAP and P0 policy

每个非 satisfied invariant 必须唯一归入 `product_defect`、
`qualification_defect`、`declared_profile_limitation` 或
`deferred_enhancement`。false success、duplicate effect/approval、authority/fence drift、
unbounded self-wakeup/write growth、accepted-but-unverifiable evidence 或 admission bypass
自动推荐 P0；人工可以提高严重度，但不能 waiver 成 green。

P0 只有在保留 deterministic red evidence、建立 focused OpenSpec change、通过 owner-local
regression 与原始 red scenario，并在 closure commit 上通过完整 matrix 后才关闭。
OpenSpec change 内 Markdown GAP 文件只是 review aid；canonical machine report 与 pure
verifier 才是 authority。

## AOX admission and evidence binding

AOX `pin`、`preflight`、formal `authorize` 与 `consume-authority` 必须显式接收
`--architecture-qualification-report`。验证先于 live
settings、pin runner attestation、attempt-root、sandbox runtime probe 以及任何
provider/runner/Chrome/MICU 调用。不存在 force、debug、environment、legacy 或
pass-boolean bypass。diagnostic authority mint/consume、`run-live`、`run-diagnostic-live` 与
closure-stage commands 已退役，不能通过 qualification report 恢复。

qualification 不读取 deployment settings，也不证明 runner 当前可达。full admission 之后、`pin`
之前，operator 必须先从当前 AOX 合同装配完整 command-scoped launch profile，再只通过 public
`openzyme-aox-cutover config-contract` 提供唯一 machine-readable executable profile descriptor 与 candidate
lifecycle：字段映射来自实际 settings/reliability resolver，AOX eligibility 来自 closed normalizer 的同一约束
owner；任一 required field 缺失或 constraint projection drift 都 fail closed。`config-candidate` 只绑定 descriptor
列出的 AOX-relevant environment、ledger 与 runner-config identity；unlisted environment 被忽略，credential 只绑定
presence，private non-credential 只绑定 digest，paths 单独绑定 resolved path/content identity，并以 credential-free、
mode-private atomic no-replace `aox_config_candidate@1` 发布。`check-config --candidate` 运行 production
effective-config 解析并重验 source identity，只生成 `aox_cutover_config_check@2`，不接收 qualification
report、不写产品 state、不连接 runner。失败的 `no_effect/terminal` 只终结
`config_candidate_occurrence`；agent 可显式处置后依据 current contract 发布 identity-distinct candidate，再
执行一条新的 explicit validation。qualification 必须拒绝 automatic fill/retry、rejected identity reuse、
private builder import 与 runner/provider probe。通过的 candidate 也不能冒充 admission/pin；随后 `pin` 的
forced-SSH deterministic fixture 是首次真实 runner effect，必须由准备授权明确覆盖。

pin transaction marker 是 `aox_cutover_pin_commit@3`，public pin receipt 是
`aox_cutover_pin_receipt@3`。transaction 还包含 credential-free
`aox_cutover_launch_profile@1`；marker、receipt、authority 与 preflight 绑定同一 profile digest，
preflight/Host 只从该 profile 恢复非敏感 settings，ambient 只补未落盘 credential。blank-world root proof 是
current `aox_blank_world_root_proof@3`，launch receipt 是
`aox_blank_world_launch_receipt@2`，attempt bundle 是
production `aox_blank_world_attempt_bundle@4`。历史
`aox_blank_world_attempt_bundle@2/@3` 只由冻结 verifier 读取，不得自动升级。新 bundle 与
其余 receipts 都绑定同一个 self-digesting
`architecture_qualification` receipt：report payload、registry、test manifest、supported
profile、source commit、report schema、source identity 与 run-evidence digest。collector/offline
verifier拒绝missing、changed、mismatched或unknown-version receipt；历史`@1`仅为冻结bundle读取兼容。

正式 `authorize` 只发布 exact-three `aox_live_attempt_authority_plan@4`，
`consume-authority`正常 public parser-to-handler 路径从 canonical plan 的完整 basename 推导
`<plan-name>.consumed.json`，发布绑定它的 consumption `@5`并停止，不构造live launch/root；
`preflight` 复用同一 owner helper。qualification 必须证明两条命令都不再要求该重复输入、正确 legacy
assertion 保持兼容、错误 assertion 在 receipt/claim/root/effect 前拒绝，并覆盖默认、无后缀和多点
basename。旧 `--attempt-authority-consumption` 的外部 caller 未知，故本轮不 breaking-remove。
`aox_attempt_authority_slot_claim@3`、`aox_attempt_preflight@5`与
`aox_supervised_host_receipt@4`只闭合
campaign/ordinal/session/root/policy；current `aox_public_conductor_execution_contract@4`先闭合exact session与
唯一pinned message，task与scientific authorization再通过专用命令于首个public sealed
drain/terminal/workspace read后late-bind，并声明attempt-start claim contract与deterministic entry keys。
execution contract `@1/@2/@3`只读，public `openzyme_public_api_receipt@3`
绑定 request identity、effect/retry/reconciliation 与 occurrence-local terminal scope；相同 request/response
只收敛到一条 receipt。receipt-written/envelope-missing window 仅允许最后且唯一的 current successful
mutation 以 exact command/request/idempotency 重入；GET、历史/较早/多个缺口、unknown effect 或 drift 均
fail closed。public drain只按Host schema
`1..100` signals/steps与hidden enqueue关闭验证，不把历史`1/8`写成qualification policy。
historical single-slot diagnostic plan/consumption仍永久`acceptance_eligible=false`，但current
product无mint/consume命令。未来单独批准的Codex conductor只经public Host API/CLI编排；该
non-live qualification scenario证明结构边界，不批准真实diagnostic或formal campaign。

current preflight必须从pinned profile调用full `prepare_aox_cutover_launch()` actual resolver并立即执行
unchanged guard，严格先于slot claim与root factory；actual Podman/rootless/image、SDK或
`aox_sandbox_scientific_backend_probe@2`失败不能被config-only digest掩盖。AOX admission scenario把
active normative requirement、实现schema与该source call order闭合；focused regression以fake probes
证明failure不创建claim/root，真实non-live process回归证明pre-ready frame绑定PID/PGID/start-time并完成
process-group retirement。另以真实no-replace publication证明single start、publish race只保留winner、
pre/post-claim MICU drift在process creation前停止、child重验claim/epoch、无PID spawn只产生最小blocked
outcome，且current/legacy schema不能互相adopt；该claim必须绑定并由child重验同一process epoch。上述证明
不执行live Podman、provider、HPC或MICU。

若 current authority 已消费，但 pinned profile/effective-config 在 slot claim 与 root 前失败，CLI
只在 claim 不存在且 campaign root absent/empty 时封存 source-bound
`aox_formal_preflight_failure@2 / failed_stage=actual_launch_guard_pre_slot_claim`。它嵌入 current
`aox_cutover_launch_failure@4`，并由同一 AOX-family normalizer 分开验证 occurrence 与 cause；formal
preflight 只采用 schema/sandbox cause，不采用另一个 lifecycle occurrence。`verify-preflight-failure` 与
`decide --preflight-failure` 是纯离线专用 NO-GO 路径，必须证明零 Host/session/attempt/MICU/provider/
runner/HPC/browser effect，且不得生成 launch/attempt identity。r75 发生时没有该 current receipt 链，
因此保持 blocked/noncanonical，不允许回填。历史 `aox_formal_preflight_failure@1` 与 nested launch
failure `@3` 只读，不能被 current writer adoption。

AOX admission 与 owner-constraint regressions 还必须直接组合 `check-config` adapter：当 runtime normalizer
给出 source-authorized schema cause 时，public `@4` 同时保留 exact candidate
`no_effect/terminal/config_candidate_occurrence`，不得由 lifecycle wrapper 覆盖 cause。该断言补足通用
`world-fidelity.earliest-cause-visible` 只覆盖 task/runtime envelope 的空白；它不运行 qualification、读取
protected environment 值、调用 runner 或产生任何 external effect。

claim/root后、child-ready前的sandbox bootstrap failure只有在
`aox_supervised_host_pre_ready_failure@2`证明live process identity、start claim、exact descendant retirement、fresh
root、zero control-plane/mutation/effect与unchanged claim-derived MICU baseline后，才可进入
`aox_formal_slot_failure@3 / closure_mode=pre_child_ready`。`public_host`分支继续使用retirement-readiness。
qualification同时证明CLI source shape、current `@3` finalizer/verifier可达、历史`@1/@2`只读且
不能crossgrade。r76缺少该receipt，继续blocked/noncanonical，不回填。

historical `aox_closure_stage_*` plan/consumption/root/source/parity/live/decision schemas
只保留离线读取与 formal non-adoption。blank-world root factory、formal publisher 和
verifier 对 raw `closure_stage_diagnostic` 及 closure-stage attempt-id family 必须
fail closed；registry 不再把已删除的 authority/reconstruction/live/CLI 文件纳入
implementation identity。

Architecture qualification 是 operator admission，不是 scientific input。AOX
`allowed_prerequisites` 保持原 exact-nine closed schema。资格通过只解除 deterministic
architecture blocker；launch identity、external availability、scientific evidence 与 cutover
verification 仍须独立通过，campaign 也必须由 operator 另行显式启动。

AOX admission scenario 还执行 selected-chain contract closure：active registry 必须能以
`for_new_attempt=true` 精确解析 `aox_blank_world_selected_chain@2`，historical `@1`
必须返回 read-only rejection；new launch config schema 必须是
`aox_blank_world_runtime_config@5`，且不存在 conductor/driver identity或`automatic_*` policy fields；
historical `@1..@4` 只允许 read-only verification。absence of automatic orchestration由production
reachability/static qualification证明，而不是sealed false flags。sandbox scientific backend probe 还必须从实际复制的
SDK 读取 `aox_exact_calculation_manifest@1`，证明 candidate/conditional-empty/finalization
exact callables、contract/implementation digests 与 fixed 17 path digest 都已安装；source
snapshot 或 workflow prose 不能替代该证明。该 scenario source 与当前 source commit/test manifest
共同进入 qualification receipt，因此 contract/config 改动会使旧 report 与 pin 失效。
同一 scenario 还读取 active blank-world normative requirement，并将其 current runtime config、
qualification report/AOX receipt 与实现导出的 schema identity 精确闭合；历史 schema 被提升为current、
`conductor` shadow truth重新出现，或owner/transformation digest binding缺失时均以零外部effect负向控制拒绝。
OpenSpec strict继续负责单个change的结构合法性，不能替代这项跨来源语义闭合。
这只证明 non-live admission 行为，不创建 attempt 或授权 external effect。
