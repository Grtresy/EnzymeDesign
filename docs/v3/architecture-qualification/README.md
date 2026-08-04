# V3 可执行架构资格验证

状态：deterministic qualification 与 AOX admission integration 已实现；每个 tracked
correction 都会使前一份 report 失效。r43-r67 已永久 NO-GO；r68 在 root/session/attempt 前
prelaunch blocked；r69 在authority/root/session/provider/MICU已消费但attempt创建前
pre-admission blocked；r70在authority/slot/root/session/receipt已消费但首个drain与Host
scientific authorization/admission/attempt前pre-runtime conductor blocked。r68-r70均非canonical
NO-GO且全部state不可复用；当前没有r71。后继 numbered campaign 必须先在
新的 clean commit 上生成并独立验证 fresh full admission report。

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
  `openzyme_v3_architecture_invariant_registry@1` authority。
- `registry-schema.md` 定义 byte、field、reference 与 selection closure。
- `p0-closures.json` 是 canonical closed-P0 sidecar，绑定 baseline digest、原 red
  scenario、focused change 与 ancestor closure commit；pure verifier 会重算，不能人工
  把当前 red/unproven invariant 标记为 closed。
- `apps/openzyme-host-api/tests/architecture_qualification/` 拥有 stable scenario id 和
  production-composition deterministic matrix。
- `scripts/v3_architecture_qualification.py` 负责编排 collection、execution 与 report
  publication；`scripts/check-v3-architecture-qualification.sh` 清除 live credential 并
  禁止 live opt-in。
- test-gate 的 `mainline_authoritative` runner 可以为同一 invocation 传入
  mainline-private sidecar request，记录 exact harness/scenario node outcomes，并绑定
  plan、source、environment 与 canonical report digest。两参数 shell command、report
  schema、publication、pure verifier、admission 和 AOX consumer 保持不变；sidecar 不是
  admission artifact，也不能跨 invocation 复用。
- `openzyme_host_api.architecture_qualification_report` 不运行 pytest、不写产品状态，
  只加载并验证 closed `openzyme_v3_architecture_qualification_report@1`。
- `openzyme_host_api.aox_architecture_qualification` 生成 AOX launch/evidence 消费的
  closed `aox_architecture_qualification_receipt@1`。

registry 闭合十个 family：wire contract、authority composition、identity semantics、
reconciliation、bounded terminal convergence、restart/fencing、supervisor progress、
operator retirement、boundary scale 与 evidence projection；AOX admission/receipt
及 schema-disjoint run-class closure 场景归入 evidence projection。后者在零外部 effect
下以真实 file-backed SQLite 证明 full-path diagnostic one-slot
plan/consumption/root/decision，以及已退役 closure-stage raw run class、attempt-id family
和 historical evidence 都不能被 formal publisher/consumer/blank-world
root/verifier/reducer 接纳，即使伪造相同 plan digest。该 negative gate 使用 frozen
literals，不依赖或恢复已删除的 closure-stage production modules。
当前 `evidence-projection.aox-run-class-disjoint-closure` scenario 以
`aox_post_r70_public_terminal_composition_qualification@1` observation收口真实 production
composition：场景通过`HostApiDependencies/create_app()`组成actual FastAPI应用，以thin
`HostApiClient`调用public route，使用file-backed SQLite和只注入agent边界的deterministic
model/runtime建立session/message、首个bounded drain、sealed terminal、唯一execution-task
read与late-bound authority。execution assignee随后经production lane/scientific tool handler
创建lane/admission；wrong task与wrong actor在零attempt状态被拒绝，Host internal finalizer才
生成late-bound identity，独立reader再证明持久化。场景还证明terminal response与唯一
`runtime.command.finished` exact一致，fault与closed export在不匹配状态typed fail closed，且
不调用private service、不手工组装`ToolRegistry`、不直接写canonical truth或合成receipt。
场景还检查diagnostic authority、public generic
scientific mutation/finalizer、automatic runner/observer及其CLI/client/dead Core入口确实缺席，
而非靠一个source symbol宣称positive reachability。
每个场景都有 finite step、tick、state/event、effect 与
wall-clock budget。skip、xfail、missing collection、timeout、budget exhaustion 或证据不完整
只能得到 `violated|unproven`，不能得到 pass。

## Modes and commands

输出目录必须是 checkout 外、caller 明确选择且尚不存在的绝对路径；publication 使用
canonical bytes、append-only/no-replace 与 directory fsync。

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

pin transaction marker 是 `aox_cutover_pin_commit@2`，public pin receipt 是
`aox_cutover_pin_receipt@2`，blank-world root proof 是
current `aox_blank_world_root_proof@3`，launch receipt 是
`aox_blank_world_launch_receipt@2`，attempt bundle 是
production `aox_blank_world_attempt_bundle@3`。历史
`aox_blank_world_attempt_bundle@2` 只由冻结 verifier 读取，不得自动升级。新 bundle 与
其余 receipts 都绑定同一个 self-digesting
`architecture_qualification` receipt：report payload、registry、test manifest、supported
profile 与 source commit。collector/offline verifier 拒绝 missing、changed、mismatched 或
unknown-version receipt。

正式 `authorize` 只发布 exact-three `aox_live_attempt_authority_plan@3`，
`consume-authority`发布绑定它的consumption `@4`并停止，不构造live launch/root。
`aox_attempt_authority_slot_claim@3`、`aox_attempt_preflight@4`与Host supervision `@3`只闭合
campaign/ordinal/session/root/policy；task与scientific authorization必须在首个public sealed
drain/terminal/workspace read后late-bind。
historical single-slot diagnostic plan/consumption仍永久`acceptance_eligible=false`，但current
product无mint/consume命令。未来单独批准的Codex conductor只经public Host API/CLI编排；该
non-live qualification scenario证明结构边界，不批准真实diagnostic或formal campaign。

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
`aox_blank_world_runtime_config@4`，其 conductor flags 必须证明 automatic drain/approval/
rollover 全为 false；historical `@1..@3` 只允许 read-only verification。sandbox scientific backend probe 还必须从实际复制的
SDK 读取 `aox_exact_calculation_manifest@1`，证明 candidate/conditional-empty/finalization
exact callables、contract/implementation digests 与 fixed 17 path digest 都已安装；source
snapshot 或 workflow prose 不能替代该证明。该 scenario source 与当前 source commit/test manifest
共同进入 qualification receipt，因此 contract/config 改动会使旧 report 与 pin 失效。
这只证明 non-live admission 行为，不创建 attempt 或授权 external effect。
