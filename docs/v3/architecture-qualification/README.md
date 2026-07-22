# V3 可执行架构资格验证

状态：deterministic qualification 与 AOX admission integration 已实现；在当前
clean commit 生成并独立验证首份 full admission report 前，AOX r48/live 继续暂停。

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
- `openzyme_host_api.architecture_qualification_report` 不运行 pytest、不写产品状态，
  只加载并验证 closed `openzyme_v3_architecture_qualification_report@1`。
- `openzyme_host_api.aox_architecture_qualification` 生成 AOX launch/evidence 消费的
  closed `aox_architecture_qualification_receipt@1`。

registry 闭合十个 family：wire contract、authority composition、identity semantics、
reconciliation、bounded terminal convergence、restart/fencing、supervisor progress、
operator retirement、boundary scale 与 evidence projection；AOX admission/receipt
场景归入 evidence projection。每个场景都有 finite step、tick、state/event、effect 与
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
deterministic P0-critical subset，由 `./scripts/check-mainline.sh` 调用；即使全部 green 也
不能 admission。

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

AOX `pin`、`preflight`、`run-live` 必须显式接收
`--architecture-qualification-report`。验证先于 live settings、pin runner attestation、
attempt-root、sandbox runtime probe 以及任何 provider/runner/Chrome/MICU 调用。不存在
force、debug、environment、legacy 或 pass-boolean bypass。

pin transaction marker 是 `aox_cutover_pin_commit@2`，public pin receipt 是
`aox_cutover_pin_receipt@2`，blank-world root proof 是
`aox_blank_world_root_proof@2`，launch receipt 是
`aox_blank_world_launch_receipt@2`，attempt bundle 是
`aox_blank_world_attempt_bundle@2`。它们都绑定同一个 self-digesting
`architecture_qualification` receipt：report payload、registry、test manifest、supported
profile 与 source commit。collector/offline verifier 拒绝 missing、changed、mismatched 或
unknown-version receipt。

Architecture qualification 是 operator admission，不是 scientific input。AOX
`allowed_prerequisites` 保持原 exact-nine closed schema。资格通过只解除 deterministic
architecture blocker；launch identity、external availability、scientific evidence 与 cutover
verification 仍须独立通过，campaign 也必须由 operator 另行显式启动。
