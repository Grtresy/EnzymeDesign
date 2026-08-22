# V3 可执行架构资格验证

本目录定义当前 V3 架构资格证明。它只验证当前 checkout、closed registry 与实际
production composition；历史 campaign、旧 receipt、源码名称扫描和 focused green 都不能替代
资格结果。

## 权威边界

资格链固定为：

```text
当前稳定合同 + 当前实现 + invariant-registry.json
                -> non-live production-composition scenarios
                -> canonical qualification report
                -> pure verifier
```

资格运行器不写 session、task、lane、approval、agent、execution 或 scientific 产品状态，也不替
agent 选择策略。报告是 source-bound repository evidence，不是运行 authority；通过资格验证不会
启动 provider、真实 HPC、浏览器或任何 live campaign。

当前资格验证固定三个互补而非互相替代的剖面：

- `kernel_fake_adapters@1`：只加载 Contracts、Extension SPI、Kernel 与显式 fake Ports；不得 import
  或启动 SQLite、Git、Host、模型运行时实现和 Plugin；
- `openzyme_standard_local_file_sqlite_git@1`：加载 Plugin-free Standard、file SQLite、local
  Git/LFS、Client 与 Kernel UI 路径；
- `enzymedesign_local_single_process_file_sqlite@1`：加载 EnzymeDesign Distribution 的 exact
  Plugin/Driver 组合，但 Provider、runner、Chrome、process 与 HPC 只能经过 registry 登记的 non-live Port。

三个剖面都不推导 multi-process、multi-Host、distributed writer、真实外部服务可用性或签名 CI
provenance。场景和不变量各自声明 `profile_ids`；Science/HPC/EnzymeDesign 证据不得冒充 Kernel-only
证据。

## 当前 registry

`invariant-registry.json` 使用
`openzyme_v3_architecture_invariant_registry@3`。当前 closed registry 包含 28 个不变量、28 个场景和
十二个 family：

- authority composition、wire contract、identity semantics；
- reconciliation、restart/fencing、bounded terminal convergence、supervisor progress；
- operator retirement、boundary scale、evidence projection；
- strategy neutrality、world fidelity。

registry 必须声明非空 `boundary_relations` 和 `external_ports`。当前两个边界关系分别约束公开诊断
字节上限与 workspace mutation/quiescence 上限；唯一外部端口是
`non-live-test-process`，模式为 `local_fault_process`。任何未声明端口、source drift、selector drift、
boundary relation drift、skip、xfail、timeout 或不完整 effect ledger 都使证明失败。

除原有十四个基础场景和五个 cutover 场景外，当前还固定八个 composition profile 场景：

- 三个剖面各自的真实闭包：Kernel fake、Plugin-free Standard、EnzymeDesign exact component catalog；
- EnzymeDesign 另有 mounted product graph 下的 non-live HMMER/Vina formal cross-layer slice，从 generic Host、Session pin、authority、immutable
  publication、adopted inventory 与 affordance/route，经 mounted HMMER/Vina Drivers 和 durable Compute 到
  声明式 fake runner，再验证 exact Driver result validator、owner continuation、Science validator 与 Task 非自动终态。
  该 slice 直接 seed 部分 canonical 前置事实，并以 no-op/fake 替代其他 product application 与 external Port，
  因此不能声明 14 个 Plugin 的完整生产命令生命周期或任何真实外部 target 已验证；
- dependency/pyproject/wheel content/fresh import/archive exposure；
- Plugin activation 的 add/remove/missing/degraded/drift/collision/cycle/namespace/Session pin 负例；
- capability inventory、qualification、declared/effective catalog、affordance 与 route stale 负例；
- local/HPC Workspace Runtime 的 path、receipt、opaque identity、response loss 与 scheduler separation；
- source、owner manifest 与文档 traceability 的反向一致性检查。

当前 cutover 仍强制包含以下五个 production-composition 场景：

- `reconciliation.workspace-job-response-loss`：runner/Host/SQLite authority 的 dispatch、cancel、
  response loss、restart、fencing 与 exact-handle replay；
- `world-fidelity.diagnostic-publication-cleanup`：公开/私有诊断、publication、Git recovery 与
  cleanup 的 earliest-cause 和 effect certainty；
- `evidence-projection.fresh-offline-deployment-proof`：fresh bootstrap 与 offline ledger 的 tagged
  proof、只读 startup 和 tamper rejection；
- `identity-semantics.scientific-file-finalization`：publication/path/blob/LFS、attempt、role 与 finalizer
  identity；
- `operator-retirement.web-ui-file-workspace`：UI client、state、controller、view 与 contract reducer
  只消费当前 file-workspace surface。

这些场景通过
`apps/openzyme-host-api/tests/architecture_qualification/production_composition.py` 运行精确的本地
non-live suites。子进程 receipt 保存 command、exit、duration、stdout/stderr digest 与 byte count；失败
保留有界 tail 和 cause chain。`no_live_effects` pytest Plugin 把 live credential/opt-in、IP socket、skip
和 xfail 视为资格失败；不会因本机缺失软件而把场景静默记绿。

## Registry 与 runner closure

- `registry-schema.md` 定义 canonical JSON、field/reference/selection closure。
- `owner-constraint-registry.json` 定义 owner、consumer 和 forbidden edge，不进入产品 runtime。
- `../architecture/catalog-owner-inventory.json` 固定 active tool/route/event/worker/migration/test/qualification
  surface 的重算 count 与 digest；重复 owner 是迁移阻塞证据，不能由资格 green 豁免。
- `../architecture/source-document-traceability.json@2` 对三剖面资格 seam 声明 owner、identity、lifecycle、
  persistence、compatibility、error、forbidden fallback 与 command/path/configuration 八类结构化合同维度，
  并重算 source/document/test 文件集合的内容摘要；它不通过关键词命中推断文档正确。
- `../architecture/pre-split-deployment-state-inventory.json` 是只读部署聚合快照，不进入 runtime，也不授权
  cutover、Plugin activation 或 live resource。
- `p0-closures.json` 只保存 source-bound historical closure，不能 waiver 当前 red/unproven。
- `apps/openzyme-host-api/tests/architecture_qualification/` 拥有 stable scenario id、safety gate、
  production composition 和负向控制。
- `scripts/v3_architecture_qualification.py` 是公开入口；必须使用该路径生成和验证报告。其他内部
  runner 路径不能冒充相同 implementation identity。
- `scripts/check-v3-architecture-qualification.sh` 清除 live credential、拒绝 live opt-in，并通过单一
  bounded process owner 执行 collection、harness 和 selected scenarios。

process phase 必须是 `collection -> harness -> selected scenarios` 的 exact prefix。首个 terminal
failure 后停止，不为未执行场景合成 fallback result。报告绑定 source、registry、selection、external
port manifest、phase receipt、earliest cause、cleanup evidence 与 not-run set。当前报告是
`openzyme_v3_architecture_qualification_report@4`；`@1`–`@3` 只能读取，不能作为当前 admission evidence。
`@4.qualification_bindings` 另外绑定 OpenSpec change、三剖面、Distribution/component manifests、wheel
集合、catalogs、inventory、schemas、文档实际字节和 test selection digest。任一 source/doc/manifest 变化
都必须重新生成报告，不接受手工沿用旧 digest。

## 模式和命令

输出目录必须是 checkout 外、绝对、canonical、尚不存在的路径；父目录必须已存在且不能是
symlink。publication 使用 canonical bytes、no-replace 和 file/directory fsync。

诊断模式允许 dirty checkout，但永远 `admission_eligible=false`：

```bash
qualification_parent="$(mktemp -d /tmp/openzyme-v3-qualification.XXXXXX)"
./scripts/check-v3-architecture-qualification.sh \
  diagnostic \
  "$qualification_parent/diagnostic-report"
```

随后必须通过 pure verifier 独立验证报告；verifier 会把公开 runner 路径纳入 implementation identity：

```bash
uv run python scripts/verify-v3-architecture-qualification.py \
  "$qualification_parent/diagnostic-report/architecture-qualification-report.json"
```

`premerge_subset` 是 mainline 同一 invocation 的有界优化证据，包含三个剖面的闭包场景，但不是完整
qualification 或 cutover proof。缺失、mismatch、timeout、
source drift 或 prior-invocation sidecar 都失败，不得回退为 ordinary pytest green。

只有全部变更已提交、canonical checkout clean 后才允许 admission：

```bash
qualification_parent="$(mktemp -d /tmp/openzyme-v3-admission.XXXXXX)"
./scripts/check-v3-architecture-qualification.sh \
  admission \
  "$qualification_parent/admission-report"
```

admission 仍不证明 provider、runner、SSH、Slurm、HPC 或浏览器当前可达，也不授权 live 调用。任何
live qualification、campaign 或真实外部 effect 都需要独立的明确授权。

## 失败与 P0

每个不满足的不变量必须归为 `product_defect`、`qualification_defect`、
`declared_profile_limitation` 或 `deferred_enhancement`。false success、duplicate effect/approval、
authority/fence drift、unbounded progress、unverifiable evidence 和 admission bypass 自动触发 P0；
人工只能提高严重度，不能把它们 waiver 为 green。

P0 关闭必须保留 deterministic red evidence、focused change、owner-local regression、原始 red scenario
和 closure commit 上的完整 matrix。Markdown 说明或旧 report 只是审计材料，不能成为当前 authority。

## 当前验收边界

资格验证必须与以下证据同时解释：

- focused behavioral tests 证明局部合同和负例；
- current retired-surface 与 production-exception audits 证明静态边界；
- `./scripts/check-mainline.sh` 证明主线软件 gate；
- fresh/offline deployment proof 证明 schema startup；
- 设备 reset receipt 只证明精确 inventory 的本机删除和 fresh 初始化。

任一层都不能替代其他层。PostHog 等非权威 telemetry 成功或失败不参与 acceptance。
