## 1. 冻结当前事实并纠正完成状态

- [x] 1.1 记录当前 clean/dirty HEAD、完整 `git status`、十六个 active changes 状态、十四项目标清单以及旧 release/per-change/removal receipt 的 source identity，生成不可修改的整改基线摘要。
- [x] 1.2 定义并验证 machine-readable evidence-gap registry schema，字段覆盖 owning change/task、反证、source location、repair task、required evidence、当前 disposition 和最终 evidence digest。
- [x] 1.3 对十四个目标 changes 的 `tasks.md` 逐项核对当前文件、测试、receipt 和行为证据，将每个已确认 gap 写入 registry，禁止按 change 整体推断。
- [x] 1.4 只把 agent Git recovery、workspace publication、handoff cleanup、HPC cancellation、scientific finalizer coverage、UI coverage、stale receipts 和 startup proof 等已被反证的原任务恢复为 `[ ]`，并在任务文本中链接对应 gap identity。
- [x] 1.5 复核未被反证的原任务仍有当前直接证据并保持 `[x]`，确认不存在因批量编辑误开的已完成项。
- [x] 1.6 验证十四个 changes 均保持 active、OpenSpec status 与 checkbox 数量一致，并确认两个非目标 active changes 未被纳入整改归档 authority。

## 2. 统一 file/revision 规范与文档真值

- [x] 2.1 更新 `AGENTS.md` 的 HPC 实施守则，移除 artifact catalog staging 和 runner `expected_outputs` 要求，改为 exact revision/LFS closure/compute tree/handle/workspace-result 合同并保留所有 authority 与 supervisor 边界。
- [x] 2.2 更新 `docs/OpenZyme架构设计.md`，明确 workspace、publication、job、scientific deliverable、task truth 和 Host supervisor 的 owner/lifecycle/persistence/error semantics/forbidden fallback。
- [x] 2.3 更新 `docs/v3/03-capability-engines.md`、`04-public-interfaces.md` 与 `07-runtime-hpc-reliability.md`，删除 artifact staging/fetch/declared-output 语义并写明 exact-handle cancellation/reconciliation。
- [x] 2.4 更新 `docs/v3/file-workspace-migration.md`、`harness-complexity-audit.md` 和 `docs/v3/README.md`，准确描述已执行 removal、fresh/offline proof、当前 product nouns 和 acceptance 限制。
- [x] 2.5 对当前源码、配置、stable docs、prompts、reflection、SDK 和 UI 执行 artifact/`expected_outputs`/staging surface 审计；对历史/OpenSpec archive 明确排除，对每个 current hit 分类并清零违规。

## 3. 建立单一 workspace-job wire contract

- [x] 3.1 在 `openzyme-domain` 建立零依赖窄 wire-contract module，提供 canonical JSON、digest、exact-object validation 和稳定 typed contract error。
- [x] 3.2 将 external job handle、cancellation intent、cancellation receipt、observation 和 reconciliation 的 mapping parser/serializer 收敛到该 module，保持 domain records 只包装已验证值。
- [x] 3.3 为 cancellation receipt 固定包含 `receipt_id` 的完整字段集合和 digest payload，增加 missing/extra/type/schema/identity/digest 负例单元测试。
- [x] 3.4 给 `mcp-hpc-runner` 增加唯一的 `openzyme-domain` workspace dependency，并添加 import-boundary 测试，证明 runner 不导入 core/runtime/execution repository/service/composition。
- [x] 3.5 修改 protected wrapper 和 runner cancellation 响应生成路径，使其通过 canonical serializer 生成 exact receipt 并在持久化前重新解析验证。
- [x] 3.6 修改 Host workspace-revision runner adapter 和 domain construction，使其只消费 canonical parser 结果，不再手写 cancellation response 字段或 digest。
- [x] 3.7 修改 dispatch replay，在返回已存在 handle 前用当前 RunSpec/dispatch intent 执行同一 canonical validator；对 observe/cancel/reconcile replay 执行等价验证。
- [x] 3.8 增加 runner/Host/domain round-trip、restart replay、tampered handle、missing `receipt_id`、extra field、digest drift 和 cross-run identity 测试，证明失败前无 backend action。

## 4. 演进结构化公开诊断与私有完整证据

- [x] 4.1 将 `FailureObservation` 演进为当前 `failure_observation@2`，增加 component、operation、typed identities、mutation state、fallback fact、safe cause chain、diagnostic identity 和 next action，并保留历史 v1 只读边界。
- [x] 4.2 定义 immutable private diagnostic record，覆盖完整 traceback、`__cause__`/`__context__`、errno/return code、bounded stdout/stderr、私有 path/handle、source/correlation identities 和 record digest。
- [x] 4.3 为 private diagnostic 增加 SQLite schema、repository 和原子写入服务；若 schema 结构变化则提升 final schema generation/manifest/bootstrap receipt 版本，禁止同 generation 静默漂移。
- [x] 4.4 实现 typed boundary error/draft builder，使 durable-state 返回与 `raise ... from exc` 都能关联同一个 public observation/private diagnostic pair。
- [x] 4.5 更新 public diagnostic sanitizer，使用 allowlisted facts、secret/token/credential/path/handle redaction、长度限制和 deterministic redaction markers，同时保留 safe type/code/digest/count/phase。
- [x] 4.6 更新 Host `ApiErrorDetail`、tool result、events、workspace/world projections 和 runtime failure observations，公开完整安全字段但不返回 private payload 或 authority tokens。
- [x] 4.7 增加 public/private round-trip、earliest-cause preservation、多层 exception chaining、hostile text、secret/path/handle redaction 和 authorized operator lookup 测试。
- [x] 4.8 增加 production exception audit gate，拒绝 bare `except`、`except Exception: pass/return` 和未记录的 broad catch；允许项必须绑定 semantic boundary、typed diagnostic 和 cause preservation 测试。

## 5. 修复 publication、recovery 与 cleanup 错误语义

- [x] 5.1 修改 workspace publication dispatch failure，使 durable execution/event 保存实际 phase、specific cause diagnostic 和由 invocation stage 得出的 effect certainty，仍只 reconcile exact ref。
- [x] 5.2 修改 workspace publication read/reconcile failure，使其保留原 effect certainty 和新 observation cause，不把查询失败伪装成 ref absent、no-effect 或 terminal conflict。
- [x] 5.3 为 publication 增加 pre-invocation failure、post-invocation response loss、parser/invariant failure、exact-ref recovery、conflicting-ref 和 sanitizer 负例测试，证明零 fallback/duplicate push。
- [x] 5.4 将 agent Git workspace observation failure 分为 proven corruption、identity drift、volume mismatch、infrastructure unavailable、permission/configuration failure 和 internal invariant；未知异常不得永久写 `CORRUPT_GIT_DIRECTORY`。
- [x] 5.5 增加 Git recovery 各分类及 restart 测试，断言 blocker/agent state、diagnostic cause、mutation fact 和 explicit replacement authority 均正确。
- [x] 5.6 重构 revision-path handoff cleanup 返回并验证结构化结果；主失败加 cleanup 失败形成 ordered compound diagnostic，post-effect residue 记录 `cleanup_incomplete` 和 exact temporary identity。
- [x] 5.7 增加 initialize/append/finalize/cleanup 各阶段的 exception、nonzero return、double failure、successful effect with residue 和 successful cleanup 测试，证明无静默残留。

## 6. 实现 fresh/offline typed deployment proof

- [x] 6.1 定义 canonical `FreshInstallBootstrapReceipt` payload/digest，绑定 current schema generation、manifest、migration source、fresh mode、false legacy initialization 和 empty object-set facts，排除时间/随机/secret。
- [x] 6.2 更新 final SQLite bootstrap SQL，以一个事务创建 current schema 和 deterministic fresh metadata；不得创建或伪造 offline legacy-removal ledger row。
- [x] 6.3 将 `_verify_final_schema` 改为读取 generation、removal state、`removal_receipt_digest` 和 manifest，并按 tagged variant 调用 fresh 或 offline verifier。
- [x] 6.4 实现 fresh verifier 独立重算 receipt，验证 schema manifest、forbidden structures、foreign-key closure 和 variant isolation，并输出详细 typed mismatch facts。
- [x] 6.5 实现 offline ledger verifier，要求 receipt digest 唯一命中 complete row并验证 completed timestamp、generation/manifest、所有 prerequisite digests、item set closure、byte totals 和 empty error set。
- [x] 6.6 保证所有 startup verification query 严格只读；错误包装保留 sqlite/filesystem cause，公开 expected/observed safe facts、operator action 和 `mutation_applied=false`。
- [x] 6.7 增加 fresh bootstrap deterministic/independent digest、tampered metadata、wrong variant、forbidden schema、manifest drift 和 foreign-key failure 测试。
- [x] 6.8 增加 offline missing/duplicate/incomplete ledger、row digest drift、item/count/byte/error closure drift 和 generation mismatch 测试。
- [x] 6.9 对所有拒绝路径断言 `total_changes`、transaction state、schema/data digest 或数据库 bytes 不变，并证明 repository/writer 未启动。

## 7. 重建 HPC、scientific 与 UI 行为覆盖

- [x] 7.1 增加 direct 和 Slurm workspace job dispatch/observe/cancel/reconcile 正常生命周期测试，断言 cancellation receipt 只证明 request acceptance、terminal 只来自 observation。
- [x] 7.2 增加 dispatch/cancel response loss、runner restart、Host restart、missing handle、tampered journal、deadline preservation 和 zero replacement submit/cancel 测试。
- [x] 7.3 增加 authority、lease/fence stale callback、duplicate worker、one-occurrence credential replay 和 caller raw-handle injection 负例。
- [x] 7.4 为 `ScientificFileEffectAdoptionService` 增加 exact same-attempt adoption、cross-attempt rejection、identity drift、fetch-without-adoption 和 effect-certainty 测试。
- [x] 7.5 为 `ScientificDeliverableFinalizationService` 增加 atomic valid set、revision/path/blob/LFS drift、artifact-era request rejection 和 task-authority independence 测试。
- [x] 7.6 为 `AoxFileBundleFinalizer` 增加 exact 17-role bundle、malformed/missing/duplicate role、contract-valid empty result 和 source-bound closure 测试。
- [x] 7.7 恢复或新建 Web UI state/view/controller/client 测试，覆盖 file tree、revision、publication、job、diagnostic、pagination、redaction 和 stale contract rejection。
- [x] 7.8 修正 C10/C12/C14 task 中的测试路径与覆盖声明，使每个 `[x]` 只引用实际存在且直接调用目标行为的测试。

## 8. 恢复可执行 architecture qualification

- [x] 8.1 从当前 production composition 推导 architecture invariant owners、boundary relations 和 external ports，更新 registry 并拒绝空集合或未解析 owner。
- [x] 8.2 将 qualification scenarios 绑定真实 repository/service/worker composition，仅在已声明 external ports 使用受控 fake；增加检测 simplified fixture 和 undeclared real-world call 的负例。
- [x] 8.3 恢复 authority/fencing/concurrency/restart/reconciliation/response-loss/cleanup 的跨层 oracles，每个同时断言 allowed outcome 与 forbidden duplicate/fallback/inference。
- [x] 8.4 将 HPC、publication、diagnostic、fresh/offline proof、scientific finalizer 和 UI required families 加入 closed selection/registry，并让缺失 family 阻止 full claim。
- [x] 8.5 更新 qualification report/verifier，绑定 exact source、registry、selection、external-port manifest、process receipts、earliest cause 和 cleanup evidence。
- [x] 8.6 运行 focused qualification regression，故意破坏 boundary relation、external port、receipt/source 和 no-replacement oracle，证明 gate 会 fail closed。

## 9. 收敛当前文档、检查清单与静态边界

- [x] 9.1 更新 architecture qualification README 和相关 `docs/v3/`，只声明当前 executable registry/production composition 实际证明的范围，删除已不存在的 artifact roots/test paths。
- [x] 9.2 更新 migration、operations、HPC、scientific 和 UI 验收文档，记录 fresh/offline proof、详细错误字段、explicit cleanup 和 no-live 限制。
- [x] 9.3 更新十四个 change 的 tasks/evidence 引用，确保 source-only gates、旧 receipts 和 PostHog telemetry 噪声不被描述为 acceptance。
- [x] 9.4 运行 current package exports、tool registry、schema、prompt、SDK、UI reducer 和 production caller retired-surface scan，清零 artifact/staging/`expected_outputs` 违规并保留 historical exclusions。
- [x] 9.5 运行 broad-exception/static diagnostic scan，逐个审查允许的 catch-all 并绑定 cause-preserving test；零静默 exception/cleanup/fallback 才完成。

## 10. 完成本机删除前的软件 gate

- [x] 10.1 运行 wire contract、diagnostics、publication、Git recovery、handoff cleanup、deployment proof、scientific finalizer 和 UI focused suites，记录 exact selection 与 source identity。
- [x] 10.2 运行完整相关非-live Python 和前端 tests，确认没有用 marker/filter 排除本 change 的 required family。
- [x] 10.3 运行完整 current architecture qualification profile并独立验证 report；green subset 不得代替 full result。
- [x] 10.4 运行 `openspec validate --strict`、retired-surface audit、broad-exception audit 和 `./scripts/check-mainline.sh`，任何失败都保留详细 earliest-cause evidence并修复后重跑。
- [x] 10.5 在临时空数据库和构造的 offline fixture 上独立验证 final bootstrap/startup verifier，冻结可用于设备 reset 的软件 source identity。

## 11. 只读解析并执行本设备 fresh-install reset

- [x] 11.1 只读解析当前 OpenZyme 配置、process argv、database locator、state/cache/storage roots、旧 receipts/backups 和 repository-service Git/LFS roots，禁止用 glob、`~`、`$HOME` 或宽泛 workspace/root 推导删除目标。
- [x] 11.2 为每个候选 target 记录 absolute identity、owner evidence、inode/device/size/digest、target kind、可恢复性、删除方法与 post-delete check；为 Git/OpenSpec/source/current Git-LFS/non-OpenZyme 建立 explicit exclusions。
- [x] 11.3 输出冻结的 device reset inventory，逐项证明所有目标属于 OpenZyme，确认 unresolved/unknown target 为零；未知 sibling 保留且阻止 all-records-deleted claim。
- [x] 11.4 发现并停止/隔离属于该部署的 Host、runner、worker、UI 或其他 OpenZyme owner，记录 PID/start time/argv 和 settlement；不影响无关进程。
- [x] 11.5 验证数据库无写 transaction/lock、mutation writer/lease 已结算、process/state roots 不再变化，生成 quiescence evidence；不满足时停止删除。
- [x] 11.6 在 destructive call 前再次核对显式绝对 targets 未跨越 exclusion、symlink、mount、home/workspace/root 边界，并记录删除不可恢复且用户授权已绑定。
- [x] 11.7 按冻结 inventory 逐项目标删除旧 OpenZyme database/runtime records、legacy storage、旧 release/removal receipts、cache 和 backups，记录每个 occurrence；不递归删除未列明 sibling。
- [x] 11.8 对每个 target 执行 post-delete identity/absence 检查并运行零 legacy schema/storage/marker/process 残留扫描；任何失败保持 reset incomplete。
- [x] 11.9 从空 deployment locator 使用冻结 final source 初始化新数据库，验证 deterministic fresh bootstrap receipt、schema manifest、foreign keys、forbidden structures 和 startup success。
- [x] 11.10 生成并独立验证 `DeviceFreshInstallResetReceipt`，绑定 inventory、exclusions、quiescence、deletion occurrences、`recoverable=false`、zero scan、fresh proof 和 source identity，且不把它用作 task/scientific/runtime authority。

## 12. 最终证据、任务闭环与归档

- [x] 12.1 在设备 reset 和所有 source edits 完成后重新确认 clean source identity；若与第 10 组不同，重新运行全部 authoritative software gates。
- [x] 12.2 在最终 clean HEAD 重新运行 full mainline、complete architecture qualification、strict OpenSpec、retired-surface 和 broad-exception audits，并独立核验全部 evidence digests。
- [x] 12.3 生成逐 change evidence map，证明十四个 changes 每个 requirement/task 的 current code、direct test、docs、deployment proof 和 source identity；缺失项保持未完成。
- [x] 12.4 将旧 release/per-change/removal receipts 标记为 superseded history，不覆盖、不复用、不伪造；设备 inventory 中的旧本地 receipts 按 fresh-reset authority 删除。
- [x] 12.5 仅在 source、tests、qualification 和 fresh deployment 固定后生成新的 source-bound release bundle、十四个 per-change receipts 和本 change closure receipt，避免 self-reference。
- [x] 12.6 独立验证新 receipts 的 schema、source/plan/evidence/reset/bootstrap identities、签发顺序和 no-replace 性；任何 drift 使 receipt chain 失效并回到 12.1。
- [x] 12.7 只在对应 direct evidence 全部通过后重新勾选原 changes 中恢复为 `[ ]` 的 tasks，并核对十四个 changes 与本 change 均无虚假完成项。
- [x] 12.8 确定 delta sync/archive 顺序，先处理被本 change 修改/移除的基础 requirements，执行协调 bulk archive 十四个目标 changes 与本 change；保留其他 active changes 等待独立裁决。
- [x] 12.9 验证 archive 后路径、main specs、git rename detection、active change 列表和历史 artifacts，确认没有遗漏、重复 sync 或意外包含非目标 change。
- [x] 12.10 审计最终 worktree/diff/验证证据与设备状态，报告所有删除 targets、不可恢复性、fresh-install 状态、remaining active changes 和未执行的 live/HPC/push actions。
