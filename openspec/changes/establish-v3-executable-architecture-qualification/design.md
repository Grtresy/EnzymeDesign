## Context

OpenZyme V3 已有大量 focused repository、runtime、Host API、engine、sandbox、runner 和 AOX verifier 测试，也有 `./scripts/check-mainline.sh` 与本地 workflow eval。但当前门禁没有一份 executable architecture invariant closure：同一约束可能分别存在于稳定文档、Core 常量、Host composition、adapter wire shape、projection 和 AOX offline verifier 中，测试通常只覆盖其中一个 seam。r43-r47 因而在普通非 live gate 之后，才依次暴露 result shape、Host authority handoff、artifact identity、lost callback reconciliation 和真实规模 boundedness/terminal convergence 问题。

当前必须保留的架构事实包括：

- 顶层产品真状态仍是 `session + task board + lane/workspace + approval + resident teammate + explicit runtime/drain`；qualification 不能成为第二套 workflow、task 或 campaign reducer。
- agent 保留科学策略自由；qualification 只能验证 owner、authority、状态迁移、外部 effect、boundedness、evidence 和 projection 等 harness 约束。
- 当前可声明的 deployment profile 仍是 local trusted Host、single process、file-backed SQLite；不能把该证明扩张为多 Host、distributed writer 或 adversarial attestation。
- production composition root 是 `HostApiDependencies + create_app()`，使用 `SQLiteRepositoryProvider`、真实 V3 services、worker factories、sandbox Host gateway、artifact/blob roots 和 projection。`v3_legacy_repositories_for_tests` 与 `build_local_eval_foundation()` 不得进入 production-composition qualification。
- LLM、provider HTTP、runner/HPC、Chrome 和容器 runtime 是真正的外部端口。资格验证必须在这些端口之外使用真实产品路径，但不允许偷偷调用真实外部系统。
- AOX launch 已要求 clean checkout、full git commit、closed launch identity 和 no-replace evidence；新的 qualification report 必须在 attempt root、provider、runner、Chrome 或 MICU 调用前验证，并进入 launch/evidence closure。
- 当前 AOX r48/live campaign 保持暂停。归档 proposal、旧 GO、fixture、diagnostic report 或一次 live success 都不能解除暂停。

本 change 建立资格体系并产出 baseline GAP。它不会把所有 deferred proposal 合并实现；任何经验证确认的 P0 产品缺口仍由独立 focused OpenSpec change 拥有产品行为、迁移和 spec delta。

## Goals / Non-Goals

**Goals:**

- 建立一个 versioned、closed、可执行的 V3 architecture invariant registry，使每项声明都有 owner、profile、canonical contract、场景和可验证证据。
- 在真实 production composition 上运行确定性、non-live 场景，只替换真正外部端口，并证明没有意外网络或真实 scientific effect。
- 将 r43-r47 类型以及 crash/restart、lost callback、lease/fence、concurrent claim、order permutation、operator interrupt 和边界规模转成稳定回归矩阵。
- 用 canonical state、event journal、external-port ledger、artifact/evidence bytes 和 public projection 的交叉观察做 oracle，并为每个场景设置有限 step/time/state/event/effect budget。
- 生成可机器验证的 diagnostic/admission report 与人类可读 GAP report，完整区分 violated、unproven 和 satisfied，而不是把 skip、fixture 或缺证据计为通过。
- 用固定规则识别 P0，要求先保存 deterministic red evidence，再创建 focused change、实施、回归并关闭 P0。
- 在任何 AOX r48/live 行为前，验证 clean-current-commit 的 full admission report、registry/test selection closure 和零 open P0。
- 将 scoped AOX local GO 与 generic V3 architecture-qualified GO 分开表达并同步稳定文档。

**Non-Goals:**

- 不在本 change 中预先实现所有 `proposed` / `deferred` architecture proposal，也不把 proposal 文档本身视为缺口已证明或已修复。
- 不通过真实 LLM、provider、HPC、Chrome 或 live campaign 发现确定性 harness 缺口；live 只在完整资格门之后证明外部可达性和真实科学路径。
- 不新增 control-plane table、task status、session projection 或 agent tool 来保存 qualification truth；它是 repository/operator admission evidence。
- 不让 qualification runner 自动修改产品状态、源代码、proposal 状态、测试预期或 AOX decision。
- 不声明 external provider/HPC exactly-once，不验证远端科学结果质量，也不替代 AOX offline verifier。
- 不为 shared/multi-process/distributed profile提前设计伪证明；这些 profile 需要独立 registry、场景和 attestation policy。
- 不把 one giant E2E、fixture eval、mock-only unit test、test count 或 code coverage 百分比当作架构资格证明。

## Decisions

### 1. Qualification 是 repository/operator 层的观察者，不是产品真状态（D1）

资格体系的依赖方向固定为：

```text
stable V3 contracts + executable invariant registry
                         |
                         v
repository qualification runner
                         |
                         v
real Host production composition
  + real Core/Engine/repository/worker/projection
  + controlled external-port adapters and effect ledger
                         |
                         v
canonical machine report -> derived GAP report
                         |
                         v
pure AOX admission verifier (read-only, fail-closed)
```

runner 可以在独立临时 root 中通过正式 API/service/worker seam 创建和推进 canonical state，但不能直接补写 task 终态、伪造 event、修复 artifact 或绕过 owner。报告不进入 session workspace，也不成为 agent 可见策略提示。

替代方案是在 control plane 增加 `QualificationRun` 产品对象；拒绝，因为这会把 repository release gate 变成新的产品真状态和 reducer。另一个替代方案是继续扩张 `openzyme_host_api.evals`；拒绝，因为现有 fixture eval 有不同目的，且不能成为架构权威。

### 2. 一个 closed canonical registry 同时闭合 invariant 与 scenario selection（D2）

仓库保存 canonical JSON registry，例如：

```text
docs/v3/architecture-qualification/
  README.md
  invariant-registry.json
```

首版 schema id 为 `openzyme_v3_architecture_invariant_registry@1`，profile 只允许 `local_single_process_file_sqlite@1`。registry 至少包含：

- registry/version/profile identity；
- invariant 的 stable id、title、owner boundary、canonical doc/spec refs、适用 profile、failure class、P0 trigger 和 scenario ids；
- scenario 的 stable id、test selector、source files、controlled external ports、fault points、boundary refs 与 budgets；
- qualification runner、pure verifier、registry validator 和 AOX gate integration 的 implementation files；
- exact required scenario/invariant set，不允许未知、重复、孤立或未覆盖项。

JSON 必须是 canonical object、closed schema、UTF-8、无 duplicate key/NaN/Inf；registry digest 对 canonical bytes 计算。每个 collected scenario 必须声明 stable scenario id，每个 registry scenario 必须被准确收集一次。pytest node id 只是定位信息，不能替代 stable id；rename、source digest 或 selection drift 会改变 test-manifest digest并使旧报告失效。

资源上限仍由各 owner 的 source constant 掌权。registry 保存 symbolic boundary ref 和 seam relation，不复制一套可漂移的产品常量；场景从 owner constant 派生 `limit-1 / limit / limit+1`，并在两个 seam 应相等时显式比较二者。

替代方案是 Markdown checklist；拒绝，因为无法闭合 test selection 或防止漏跑。另一个替代方案是只扫描测试名；拒绝，因为测试存在不代表场景实际执行、无 skip 或使用正确 composition。

### 3. Production-composition fixture 只替换真正外部端口（D3）

首版 qualification composition 必须：

- 使用 `create_app(HostApiDependencies(...))`、显式 file-backed `SQLiteRepositoryProvider` 和独立 artifact/blob/sandbox roots；
- 使用真实 migration、repository scopes、V3 service、engine registry、durable worker/coordinator/supervisor、sandbox Host gateway、workspace/event projection 和 public DTO；
- 禁止 `v3_legacy_repositories_for_tests`、process-local shared repository、`build_local_eval_foundation()`、fixture-non-cutover product result和直接 repository success seeding；
- 通过正式 SPI 注入 controlled LLM/provider/runner/Chrome/process adapters；每个 adapter 标记 `qualification_fixture_non_cutover`，记录 canonical request、acceptance/effect certainty、response和调用次数；
- 在 runner 子进程中使用 credential-scrubbed environment 和 deny-by-default network guard。任何未登记 socket、SSH、provider、Chrome、MICU 或 container invocation立即使场景失败；
- 对 restart 场景销毁 app/dependencies/connection/process owner，再用同一 SQLite 和 exact roots 重建 composition，而不是只重建一个 service object；
- 对 signal/crash 场景使用独立 process group、bounded TERM/KILL cleanup 和最终无 descendant 证明，绝不接触真实远端 effect。

controlled adapter 证明的是 Host/harness 对外部事实的处理，不证明真实 provider/cluster 可达或科学质量。后续 live preflight仍有独立职责，但不能反向替代本资格门。

替代方案是全 mock unit composition；拒绝，因为 r43-r47 正是在真实 seams 组合时出现。全 live composition 同样拒绝，因为不可重复、昂贵且会混淆产品缺口与外部抖动。

### 4. 按 invariant family 建模，而不是按历史 run 编写一次性复现（D4）

初始 registry 至少包含以下 family：

| Family | 首批证明 |
| --- | --- |
| `wire-contract` | r43 类 direct/durable/recovered provider result 使用同一 closed wire shape，嵌套或缺字段 fail closed |
| `authority-composition` | r44 类 process/execution/delivery/mutation authority 只经 typed production gateway，stale/mixed authority不能写 canonical state |
| `identity-semantics` | r45 类 artifact member-set identity 对顺序置换不变，而有序 transcript/argv digest 保持顺序敏感 |
| `reconciliation` | r46 类 lost callback 只从同 operation/request 的 digest-verified sealed observation恢复 exact envelope；missing/tamper/drift terminal-known fail closed且不 replay |
| `bounded-terminal-convergence` | r47 类 bulk identities 留在 artifact，完整 result envelope遵守 owner上限，terminal-known invalid observation只终结一次且没有 claim/reconcile/event storm |
| `restart-fencing` | pre-dispatch、dispatch-in-doubt、result-before-delivery、stale lease/process epoch、Host restart和并发 claim均保持唯一 owner/effect |
| `supervisor-progress` | idle、claim-raced、not-claimable、database-busy、poll/reconcile 与真实 durable transition分开；无语义进展不能形成即时自唤醒热循环 |
| `operator-retirement` | SIGINT/SIGTERM、重复 signal、child exit和descendant残留走有限 retirement，保留原 signal语义且不制造remote cancellation或normal bundle |
| `boundary-scale` | 256 KiB result/metadata inline、4 MiB frame/dispatch、8 MiB control document、32 MiB sidecar及其他登记边界逐一执行 `-1/=/+1` 与跨seam equality |
| `evidence-projection` | canonical state、events、artifact bytes、workspace/public projection和offline evidence在成功/失败/重启后保持同一identity与安全边界 |

历史 r43-r47 id 只作为 provenance；场景名和 oracle描述架构 invariant，避免以后代码移动或新 route 出现时把测试误认为仅限 AOX 特例。

### 5. Oracle 必须交叉观察 canonical truth、effect ledger 与 public projection（D5）

场景不能只断言一次返回值。qualification observation 至少包括：

- SQLite canonical rows、state versions、lease/fence、append-only transition/event journal；
- controlled external-port ledger 中 request/effect acceptance/reconcile/poll/materialize 次数与 digest；
- artifact/blob/sandbox bytes、metadata和manifest identity；
- API/workspace/pending-approval/runtime-state projection及private-field absence；
- worker tick、notifier、claim、state/event增长和终态收敛；
- restart前后同一 logical operation、process、delivery、mutation generation与report identity。

每个 scenario 声明 `max_steps`、`max_ticks`、`max_state_version_delta`、`max_event_delta`、`max_effect_count` 和 wall-clock deadline。达到预算仍无允许终态时结果为 `violated` 或 `unproven`，不能继续等全局 timeout。`skip`、`xfail`、collection缺失、fixture drift或环境依赖都使 full qualification失败。

成功 scenario 必须同时证明允许 outcome 和禁止 outcome，例如 lost callback success不仅要得到result，还要证明 provider dispatch count仍为一、没有第二approval、没有 fallback summary和没有额外terminal transition。

替代方案是 golden workspace snapshot；拒绝，因为大 snapshot容易复制实现细节、掩盖 canonical owner，并对无关字段变化敏感。oracle应围绕 invariant关系和closed identities。

### 6. Diagnostic 与 admission 是同一 runner 的两个不同信任级别（D6）

唯一 repository command 由 `scripts/check-v3-architecture-qualification.sh` 调用 Python runner。它提供：

1. `diagnostic`：允许 dirty checkout，绑定 full HEAD、tracked diff digest、untracked source manifest和test implementation digest；用于建立 baseline/GAP，但固定 `admission_eligible=false`。
2. `admission`：要求 canonical repo root、完全 clean worktree、full lowercase HEAD、完整场景集、零 skip/xfail/error/violation/unproven、零 open P0；只在该条件下输出 `admission_eligible=true`。

runner 写 canonical current `openzyme_v3_architecture_qualification_report@2` envelope，payload 至少包含：

- source identity、mode、profile、registry/test-manifest/runner/verifier digest；
- exact command和scenario/invariant set digest；
- 每个 scenario outcome、budgets、observation/effect-ledger digest和safe failure；
- 每个 invariant 的 `satisfied | violated | unproven`；
- GAP taxonomy、priority、owner、reproducer和related proposal/change；
- open/closed P0 closure refs；
- `admission_eligible` 与所有拒绝理由。

envelope 对 payload canonical bytes计算 digest；输出使用 caller提供的checkout外目录、no-replace写入和目录fsync，避免 report 对包含自身的commit产生循环依赖。可将派生的 human-readable baseline GAP 摘要提交到本 change，但它不是 admission authority。

pure verifier 重新执行 closed schema、canonical bytes、payload digest、registry/test/implementation digest、profile、current HEAD/clean worktree和零P0检查。只检查 JSON 中的 `passed=true` 不构成验证。

### 6a. Run admission 在 pytest 前持有 checkout single-flight（D6a）

output contract 不再只属于 report publication 尾部。runner 先解析 canonical Git checkout，
校验 primary output directory 与 optional mainline sidecar 均为 checkout 外、absolute、lexically
canonical、target absent、parent existing real directory且无 alias；任何失败以
`architecture_qualification_output_invalid` 在 collection/harness/scenario 前终止。获得 lock 后
立即重验一次，final publication 再重验并保留 no-replace/fsync，关闭 admission 与 publication
之间的 target race。

single-flight identity 只取 canonical checkout root 的 local device/inode，不含 mode 或 output，
因此 symlink/bind alias、`diagnostic|admission|premerge_subset` 和不同 output 都落到同一个 kernel
lock。per-UID private `/tmp` lock root只保存 inert regular file；`O_NOFOLLOW|O_CLOEXEC`、owner/mode/
link-count 检查后使用 `flock(LOCK_EX|LOCK_NB)`。fd 从 collection 持有到 report pure verification及
mainline sidecar publication结束；正常 close与process crash都由kernel释放。竞争者只得到
`architecture_qualification_run_active`，没有 blocking wait、steal、owner metadata、durable run
row、automatic recovery或equivalent-command relaunch。

该边界不改变 full matrix、scenario budget、report schema、pure verifier或sidecar non-adoption。
如果一次工具调用返回 yielded execution handle，恢复/停止属于外部 Codex conductor合同：只能恢复
exact handle；handle失联时只读停止，不能通过新 runner command规避single-flight或拼接partial
evidence。

### 6b. Source-bound causal evidence 只由 repository test-gate 生成（D6b）

qualification 的 pytest collection、harness self-test 与 scenario process 不属于 Host 产品能力。
删除 `openzyme_host_api.architecture_qualification_runner`，repository CLI 只调用
产品无关`scripts/test_gate`包之外的`scripts/architecture_qualification_runner.py`，而后者只能复用
`scripts/test_gate/runner.py` 的 process-group owner；不得再出现第二个 `Popen`、临时输出 executor、
late source sample 或 Host package 内无产品 caller 的 test runner。

single-flight lock 获取并重验 output 后立即采样 admission source。collection 前后、harness 后、每个
scenario 前后及 publication 前都重算 closed source identity，并把 observation digest、是否匹配
admission 和 phase id 写入 report。每个实际 process 都封存 source-bound receipt：safe command、
outcome/exit、bounded stdout/stderr digest/byte-count/tail、timeout、TERM/KILL 与 spawn error code。
receipt phases 必须是 exact selected chain 的前缀；健康 run 必须闭合 collection、harness 和全部
scenario，失败 run 必须只保留最早的 typed cause并在该点停止，禁止 equivalent relaunch、fallback
scenario result或未运行 invariant 的 GAP/P0 cascade。

current envelope/payload 为 `openzyme_v3_architecture_qualification_report@2` / `...payload@2`。
`run_evidence_digest` 闭合 admission/terminal source、phase revalidation、process receipts、earliest
failure 和 exact not-run ids。历史 `@1` loader 仅用于冻结 evidence 审计；pure current verifier与
AOX admission拒绝它。AOX receipt相应升级为 `aox_architecture_qualification_receipt@2`，额外绑定
report schema、source identity和run evidence digest；历史 receipt `@1` 只有 frozen bundle reader
可显式选择只读兼容。

operator-retirement 的 business claims不再由亚秒 wall-clock threshold决定。identity、exit/signal、
final descendant count和forced-unproven输入一个纯函数，确定 retirement/quarantine/unknown-effect/
non-cutover语义；真实时钟只保留一个使用秒级宽限的 bounded process-group containment probe。

### 7. GAP taxonomy 与 P0 晋级不允许人工 waiver 制造 green（D7）

每个非 satisfied invariant先分类：

- `product_defect`：真实 composition违反既有稳定合同；
- `qualification_defect`：场景、controlled port或oracle自身不能证明目标；
- `declared_profile_limitation`：当前 profile明确不声称该能力且现有路径有界fail-closed；
- `deferred_enhancement`：只改善容量、可用性、性能或generic profile，不改变当前正确性。

以下任一可观察事实自动给出 P0 recommendation，人工只能升级、不能降级：

- invariant失败后系统仍声称success/GO/completed；
- 同logical operation产生超过允许数量的external effect或approval；
- 无有效owner/fence的写入被接受，或private authority泄漏成caller输入；
- 在有限输入和fault下无法在预算内收敛，产生即时自唤醒、claim/reconcile或event/write storm；
- canonical evidence、artifact set、result或report不能离线闭合，却仍可被accept/publish/admit；
- qualification/live admission gate可以被fixture、旧report、partial selection、dirty source或manual flag绕过。

baseline 必须先封存 red report和最小复现。每个确认 P0 创建独立 focused OpenSpec change；产品修复不得直接把 scenario删除、放宽budget、改为xfail或更换简化fixture。P0只有在原red scenario、相关focused tests和full qualification均通过，且report引用完成change/commit后才关闭。

有界、明确、pre-effect fail-closed且只影响当前未声明profile的gap可以继续deferred，但report必须保留限制，不能写成generic implementation complete。

### 8. AOX admission 消费 exact report，不把它混入 scientific prerequisite（D8）

AOX `pin`、`preflight` 与 `run-live` 在创建attempt root、sandbox runtime probe或任何外部调用前，要求显式 `--architecture-qualification-report`。gate verifier要求：

- report是 `admission` mode、当前local profile和当前clean HEAD；
- registry、test manifest、runner/verifier implementation与checkout一致；
- full required set全部satisfied，零open P0；
- report不是fixture、diagnostic、历史commit或可变路径引用。

qualification 是 operator/repository admission，不是 scientific input，因此不加入 exact-nine `allowed_prerequisites`。launch pin/declaration/receipt 增加 versioned `architecture_qualification` receipt，绑定 report、registry、test-manifest和payload digest；AOX evidence collector/offline verifier检查同一receipt。任何现有closed schema需要显式version bump和migration tests，不能静默追加字段或只在CLI里检查。

不提供 `--force`、环境变量、debug route或代码内fallback。若资格工具自身失败，AOX保持NO-GO；恢复路径是修复qualification change并重新在clean commit生成report，而不是跳过。

### 9. 文件与依赖方向保持现有 monorepo 边界（D9）

计划落点：

- `docs/v3/architecture-qualification/`：稳定registry、schema说明、profile和operator runbook；
- `scripts/v3_architecture_qualification.py` 与 `scripts/check-v3-architecture-qualification.sh`：repository orchestration、collection closure与report生成；
- `apps/openzyme-host-api/tests/architecture_qualification/`：production-composition fixture和跨层scenario；
- 各package相邻tests：owner-local red/green focused tests，但必须由跨层scenario引用同一invariant id；
- `openzyme_host_api.architecture_qualification`：只包含AOX admission所需的closed report loader/pure verifier和stable errors，不运行pytest、不构造fixture、不拥有product state；
- AOX launch/evidence/CLI：调用pure verifier并绑定versioned admission receipt。

不新增 workspace package。Core/Engine/domain不依赖Host或scripts；scripts和Host tests可以从顶层组合既有packages。资格support不能进入agent tool registry或public API。

### 10. Fast feedback 与 full qualification 分层但不混淆声明（D10）

`check-mainline.sh` 加入 registry/schema/test-selection closure和P0-critical deterministic subset，使普通变更不能轻易删除owner、scenario或gate。完整命令运行全部family、subprocess/restart/concurrency/scale场景并生成report；只有完整命令的clean `admission` report可解锁AOX。

subset report必须标记 `selection=premerge_subset`、`admission_eligible=false`，即使全绿也不能被称为architecture-qualified。full matrix仍是non-live，可在本机或CI运行；外部availability preflight只在它之后开始。

## Risks / Trade-offs

- **[Qualification harness itself drifts from production]** → 强制使用Host composition root、file-backed provider和真实worker；registry闭合implementation files与source digest，并对legacy/eval fixture注入做negative test。
- **[Controlled external ports给出虚假安全感]** → report明确`external_effects_real=false`，只声明harness correctness；真实provider/HPC/Chrome availability仍由后续live preflight证明，二者互不替代。
- **[Report被复制、伪造或重用于新commit]** → canonical envelope、current checkout re-verification、clean HEAD、registry/test/implementation digest和no-replace输出；首版只声称local trusted Host，shared profile需要后续signed CI attestation。
- **[Dirty development tree无法生成admission report]** → diagnostic mode绑定完整diff/untracked manifest供迭代；只有commit后clean rerun可生成admission，避免自引用tracked report。
- **[Fault tests变慢或不稳定]** → 使用deterministic barriers/fake clock、有限budgets和subprocess hard deadline；premerge只跑P0-critical subset，但full gate不允许skip或降级。
- **[Signal/crash test泄漏子进程]** → 每场景独立process group、identity-checkedTERM/KILL、最终descendant emptiness assertion；cleanup失败使整个qualification失败。
- **[自动P0规则误判qualification defect]** → recommendation和taxonomy分开；任何unproven仍阻断admission，但只有production invariant证据确认后创建产品P0 change。
- **[为使gate变绿而放宽稳定合同]** → scenario绑定canonical doc/spec refs；合同变更必须独立spec delta和迁移，不能在qualification change中静默改expected outcome。
- **[AOX gate扩大现有launch/evidence schema]** → 显式version bump、negative compatibility tests和offline verifier closure；不把qualification混成scientific prerequisite或仅在CLI层检查。
- **[Full matrix长期增长]** → invariant family、profile和stable scenario id去重；新增scenario必须证明新failure surface，不能按每个历史bug复制整套fixture。

## Migration Plan

1. **Freeze and contract**：保持AOX r48/live暂停；落地registry schema、profile、pure validator/verifier和文档，不改变当前product transitions。
2. **Composition harness**：建立受控external ports、effect ledger、network guard、file-backedproduction fixture和scenario collection closure；先以diagnostic mode运行。
3. **Baseline**：运行full diagnostic matrix，封存machine report和本change内human GAP摘要；所有violated/unproven保持admission red。
4. **P0 promotion**：按D7为确认缺口建立focused OpenSpec change，保留原red scenario，逐项实施和回归；qualification change持续追踪closure refs。
5. **Admission enablement**：零open P0且full matrix全绿后，在clean commit生成首个admission report；随后把pure verifier接入AOX pin/preflight/run-live，version bump launch/evidence schema并补bypass/tamper/old-report tests。
6. **Stable docs and gates**：同步主架构、V3 reliability/control-plane、architecture proposal index、AOX文档、pytest markers和operator commands；把premerge subset接入`check-mainline.sh`。
7. **Final audit**：重跑focused、full qualification、mainline、eval和OpenSpec verify；确认没有live call、没有未关闭P0、report与clean HEAD一致后，才允许另行执行AOX `8.3-8.8`。资格通过本身不自动启动campaign。

Rollback原则：qualification runner/registry早期可整体revert且不迁移product state；一旦AOX admission schema启用，不得通过运行时flag回退到无gate旧路径。若gate实现有缺陷，系统保持fail-closed NO-GO，修复后生成新schema/current-commit report。历史reports和baseline evidence永不改写。

## Open Questions

- shared/multi-process profile是否要求CI签名、SLSA-style provenance或独立attestation service，留给独立change；首版不作安全声明。
- full matrix最终由哪一个CI executor持久保存admission artifact，需要结合现有部署/CI能力决定；本地operator输出和验证合同不依赖该选择。
- 哪些deferred proposal会晋级P0不是设计预判项，必须由baseline production-composition evidence决定；已知operator interrupt和durable progress语义只作为优先场景，不提前写成已确认修复结论。
