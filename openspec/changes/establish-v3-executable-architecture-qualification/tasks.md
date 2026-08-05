## 1. 冻结边界与建立可追溯清单

- [x] 1.1 在 change 证据中记录当前 AOX r48/live 暂停状态、最后已知非 live 基线与禁止外部调用的执行规则，确保后续资格命令不会隐式恢复 campaign
- [x] 1.2 盘点 r43-r47 对应的 wire、authority、identity、reconciliation、boundedness 失败链，并把历史 run 仅登记为 provenance 而非测试 authority
- [x] 1.3 盘点 `HostApiDependencies + create_app()`、`SQLiteRepositoryProvider`、worker/supervisor、sandbox Host gateway、event/workspace projection 的 production composition 路径与关闭生命周期
- [x] 1.4 盘点 LLM、provider HTTP、runner/HPC、Chrome、容器/子进程等真实外部端口及其正式注入 seam，形成 deny-by-default allowlist 输入
- [x] 1.5 盘点跨 seam 产品边界常量及 owner source，建立只引用符号 owner、不复制数值真相的 boundary relation 清单

## 2. Closed invariant registry 与选择闭包

- [x] 2.1 在 `docs/v3/architecture-qualification/` 定义 `openzyme_v3_architecture_invariant_registry@1`、`local_single_process_file_sqlite@1` 与 closed canonical-JSON 字段合同
- [x] 2.2 实现拒绝 duplicate key、unknown field、NaN/Inf、非 canonical bytes、未知 profile 和不可读 source/contract ref 的 registry loader/validator
- [x] 2.3 实现 invariant、scenario、family、owner、P0 trigger、external port、fault point、budget 与 boundary ref 的双向闭包校验
- [x] 2.4 为资格 pytest 场景增加稳定 scenario id 元数据与 collection manifest，保证每个 registry scenario 恰好收集一次且没有未登记场景
- [x] 2.5 实现 registry digest 与 test-manifest digest，绑定场景选择、source、runner、verifier 和实现文件，而不以 pytest node id 充当稳定身份
- [x] 2.6 实现 boundary ref 解析，从 owner 常量派生 `limit-1`、`limit`、`limit+1` 并校验声明的 cross-seam equality
- [x] 2.7 补充 registry/collection/boundary validator 的正向测试及 duplicate、orphan、missing、skip/xfail、source drift、selection drift 负向测试
- [x] 2.8 填充首版十个 invariant family 与全部稳定场景登记项，并证明 registry、测试 collection 和 required full selection 完全相等

## 3. 真实 production-composition 资格骨架

- [x] 3.1 在 `apps/openzyme-host-api/tests/architecture_qualification/` 建立每场景独立临时 SQLite、artifact、blob、sandbox 与 workspace roots 的 fixture
- [x] 3.2 通过显式 file-backed `SQLiteRepositoryProvider`、当前 migrations、`HostApiDependencies` 和 `create_app()` 构造真实 V3 composition
- [x] 3.3 将真实 engine registry、durable coordinator/supervisor/workers、sandbox Host gateway、event store、workspace projection 与 public DTO 接入 fixture
- [x] 3.4 实现完整 composition retirement/restart helper，关闭旧 app、dependencies、repository connection、workers 与 process owner 后在相同持久 roots 上重建
- [x] 3.5 为 legacy repositories、process-shared fixture repository、`build_local_eval_foundation()`、direct success seeding 和 fixture scientific evidence 增加 fail-closed 检测
- [x] 3.6 实现标记为 `qualification_fixture_non_cutover` 的 controlled external adapters，并记录 canonical request、acceptance certainty、effect、response、poll/reconcile 与调用次数
- [x] 3.7 实现 credential scrub、socket/network/SSH/browser/provider/runner/container/process deny-by-default guard，并对每个允许端口要求 registry 声明
- [x] 3.8 实现 canonical state、version/fence、events、effect ledger、artifact bytes、worker observations 与 public projection 的跨层 observation collector
- [x] 3.9 实现 per-scenario step、tick、state/event delta、effect count 与 wall-clock budget，预算耗尽只能产生 `violated` 或 `unproven`
- [x] 3.10 为 composition、禁止 fixture、未声明外部调用、restart 同根恢复和无 workflow/task 自动决策补充资格骨架自测

## 4. r43-r47 跨层稳定回归

- [x] 4.1 实现 `wire-contract` 场景，证明 direct、durable 与 recovered provider result 使用同一 closed envelope，并拒绝嵌套、缺字段和未知字段
- [x] 4.2 实现 `authority-composition` 场景，证明 process/execution/delivery/mutation authority 只经 typed Host gateway 传递，并拒绝 stale、mixed 或 caller-supplied private authority
- [x] 4.3 实现 `identity-semantics` 场景，证明 artifact member-set identity 对输入顺序不敏感，而 transcript/argv 等 ordered digest 保持顺序敏感
- [x] 4.4 实现 `reconciliation` 场景，覆盖 lost callback exact recovery、missing/tampered/drifted sealed observation、零 replay 与单一 approval/effect
- [x] 4.5 实现 `bounded-terminal-convergence` 场景，覆盖 bulk identity artifactization、完整 result envelope owner limit、terminal-known invalid observation 单次终结及无 claim/reconcile/event storm
- [x] 4.6 为五个 family 的允许结果与 forbidden effect、fallback、private authority、额外 transition、task inference 编写跨层 oracle

## 5. 故障、重启、并发、operator 与边界矩阵

- [x] 5.1 实现 `restart-fencing` 的 pre-dispatch loss、dispatch-in-doubt、result-before-delivery restart 与 stale lease/process epoch 场景
- [x] 5.2 实现 deterministic barrier 驱动的 simultaneous claim/concurrent worker 场景，证明唯一 owner、有限 effect 与稳定 terminal state
- [x] 5.3 实现 `supervisor-progress` 场景，分别观察 idle、claim-raced、not-claimable、database-busy、unchanged poll/reconcile 与真实 durable transition
- [x] 5.4 对无语义进展输入施加有限 notifier/claim/state/event/write budget，确定当前 supervisor 是否存在即时自唤醒放大并保存可复现证据
- [x] 5.5 实现 identity-bound process-group fault runner，包含有限 observation、TERM、KILL、descendant-emptiness 阶段和原始 signal exit 语义
- [x] 5.6 实现 `operator-retirement` 的 SIGINT、SIGTERM、重复 signal、child early-exit、descendant residue 与 dispatch-in-doubt cleanup 场景
- [x] 5.7 证明 cleanup 不调用 agent/provider/runner/approval/evidence collector，不制造 remote cancellation、normal bundle、quiescence 或 exact charge
- [x] 5.8 实现 `boundary-scale` 矩阵，对所有登记 owner limit 执行 `-1/=/+1`，并覆盖 256 KiB、4 MiB、8 MiB、32 MiB 等当前跨 seam 关系
- [x] 5.9 实现 `evidence-projection` 场景，证明成功、失败、重启后 canonical state/events/artifact bytes/workspace/public/offline identity 闭合且 private fields 不外泄
- [x] 5.10 为 fault runner 自身增加 deadline、identity mismatch、unretired descendant 和 outcome-unknown 的 fail-closed 自测

## 6. Runner、canonical report 与纯验证器

- [x] 6.1 在 `scripts/v3_architecture_qualification.py` 实现 `diagnostic`、`premerge_subset` 与 `admission` 对同一 registry/runner/scenario/verifier 的模式解析
- [x] 6.2 实现 source identity 收集，绑定 full HEAD、canonical repo root、tracked diff digest、untracked source manifest 与实现文件 digest
- [x] 6.3 实现 pytest collection/execution 适配，将 pass/fail/skip/xfail/error/timeout 与 observation ledger 转换成 `satisfied | violated | unproven`
- [x] 6.4 实现四类 GAP taxonomy、owner/reproducer/evidence/profile/change refs 与不可人工降级的 P0 recommendation 规则
- [x] 6.5 实现初始 closed `openzyme_v3_architecture_qualification_report@1` payload/envelope、canonical bytes 与 payload digest（现由 task 11 显式升级为current `@2`，`@1`仅保留只读兼容）
- [x] 6.6 实现 checkout 外 caller-selected output、no-replace file creation、文件与目录 fsync、alias/inside-checkout/self-reference 拒绝
- [x] 6.7 在 `openzyme_host_api.architecture_qualification` 实现无 pytest/fixture/product-state 依赖的 closed report loader、稳定错误与 pure verifier
- [x] 6.8 让 pure verifier 重新计算 schema、canonical bytes、digest、source/worktree、profile、registry、selection、implementation、invariant 与 P0 closure，而不是信任 report pass 字段
- [x] 6.9 为 diagnostic dirty binding、subset 永不 admissible、admission clean/full/zero-P0 条件及所有 report/checkout tamper 路径补充测试
- [x] 6.10 增加 `scripts/check-v3-architecture-qualification.sh`，固定 non-live 环境、显式输出目录和安全退出码，并验证它不会启动 AOX 或真实外部调用
- [x] 6.11 在任何 collection/harness/scenario 前统一验证 canonical output directory 与 mainline sidecar，跨 admission/diagnostic/premerge 和任意 output 以 canonical-checkout-bound kernel `flock(LOCK_NB)` 实现 single-flight，分别返回 exact `architecture_qualification_output_invalid` / `architecture_qualification_run_active`，保留 final no-replace/fsync/pure-verifier/sidecar non-adoption，并覆盖 concurrent/cross-mode/symlink/invalid-parent/crash-release/mid-run-race/no-work-before-rejection。

## 7. Baseline GAP 与证据驱动 P0 闭环

- [x] 7.1 在 checkout 外 no-replace 目录运行完整 `diagnostic` 矩阵，保存 machine report、registry/test-manifest/source digest 与精确命令
- [x] 7.2 从 machine report 生成 change 内人类可读 baseline GAP 摘要，并明确其非 authority 属性、machine digest 与 dirty source identity
- [x] 7.3 对每个 `violated` 或 `unproven` invariant 核对 production composition、oracle 完整性和稳定合同，逐项归入唯一 GAP taxonomy
- [x] 7.4 独立复核 supervisor no-progress 与 operator interrupt 两个优先场景，只按 deterministic production evidence 判断是否触发自动 P0，禁止预先把 proposal 当成 defect
- [x] 7.5 在任何产品修复前冻结每个 confirmed P0 的原始 red scenario、最小复现、effect/state/event 证据与 baseline report digest
- [x] 7.6 为每个 confirmed P0 创建独立 focused OpenSpec change，并在本清单追加具名的实现、owner-focused regression、原 red scenario 与 closure-ref 子任务；若零 P0，则记录完整零缺口证据
- [x] 7.7 逐项完成新增的具名 P0 子任务，禁止通过删除/deselect/skip/xfail、简化 fixture、无合同依据放宽 budget 或弱化 invariant 获得 green
- [x] 7.8 每关闭一个 P0 后重跑其原始 red scenario 与 owner-focused tests，并在后续 immutable report 中记录 exact change/commit closure refs
- [x] 7.9 全部 P0 子任务完成后重跑完整 diagnostic matrix，要求十个 family 全部 satisfied、零 open P0、零 unproven，才允许进入 AOX admission 集成
- [x] 7.10 `bound-public-diagnostic-sanitizer-work`：实现 fixed-left-boundary credential URI scan，保持完整输入、既有脱敏顺序和稳定 marker
- [x] 7.11 `bound-public-diagnostic-sanitizer-work`：owner-focused 64 KiB、混合 URI、encoded locator、nested payload 与 idempotence 回归通过
- [x] 7.12 `bound-public-diagnostic-sanitizer-work`：原冻结场景与 pure verifier 通过，closure report 为 `sha256:ae4d784719af50069c6fbc339758359233de534a44a8426f93f892561ff398fe`
- [x] 7.13 `fix-v3-durable-supervisor-semantic-progress`：实现三类 durable worker 的 typed semantic-progress outcome 与 canonical execution fingerprint
- [x] 7.14 `fix-v3-durable-supervisor-semantic-progress`：owner-focused contract/accounting/wakeup/task-authority 回归通过
- [x] 7.15 `fix-v3-durable-supervisor-semantic-progress`：原冻结 supervisor 场景与 pure verifier 通过，并记录具名 change/commit closure refs

## 8. AOX qualification admission 与证据 receipt

- [x] 8.1 在 AOX `pin`、`preflight`、`run-live` 的共同最前置边界增加显式 architecture qualification report 参数和 pure verifier 调用
- [x] 8.2 证明 missing/diagnostic/subset/fixture/stale/tampered/dirty/unknown-profile/open-P0 report 在 attempt-root 创建、sandbox probe 与任何 provider/runner/Chrome/MICU 调用前 fail closed
- [x] 8.3 明确拒绝 force/debug/env/legacy/pass-boolean 等 bypass，并证明 qualification pass 本身不会创建 attempt 或启动 r48/live
- [x] 8.4 为 launch pin/declaration/receipt 的 closed schema 做显式 version bump，加入绑定 report payload、registry、test-manifest、profile 与 source commit 的 `architecture_qualification` receipt
- [x] 8.5 保持 scientific `allowed_prerequisites` exact-nine 结构不变，并补充防止把 qualification 静默混入 scientific input 的兼容性测试
- [x] 8.6 让 AOX attempt collector、sealed evidence 与 offline verifier 闭合同一 qualification receipt，并拒绝 missing/mismatch/drift/unknown-version
- [x] 8.7 补充 CLI、launch、collector 与 offline verifier 的正向、tamper、old-report、selection-drift、schema-migration 和 pre-effect ordering 回归

## 9. 主线门禁与稳定文档同步

- [x] 9.1 将 registry/schema/selection closure 与 deterministic P0-critical `premerge_subset` 接入 `scripts/check-mainline.sh`，并保持 subset report 非 admissible
- [x] 9.2 在 `docs/v3/architecture-qualification/README.md` 记录 profile、registry、runner、report、GAP/P0、clean admission、operator 命令与非 live 安全边界
- [x] 9.3 同步 `docs/OpenZyme架构设计.md` 与相关 `docs/v3/` harness、control-plane、runtime、reliability/public-interface 文档中的 qualification 依赖方向和非产品真状态边界
- [x] 9.4 同步 AOX 操作文档、launch/evidence schema 文档与 architecture proposal index，明确零 P0/full admission 只解除架构阻断而不自动启动 campaign
- [x] 9.5 记录首版只声明 trusted-Host `local_single_process_file_sqlite@1`，明确排除 shared/multi-process/multi-Host/distributed/signed-attestation 推论
- [x] 9.6 更新 pytest marker/开发命令说明，清楚区分 focused tests、premerge subset、full qualification、workflow eval、seeded/live E2E 与外部 availability proof

## 10. 完整验证、clean admission 与最终审计

- [x] 10.1 运行 registry/runner/verifier/production-composition focused tests，并保存精确命令与结果
- [x] 10.2 运行 r43-r47、restart/fencing/concurrency/progress/operator/boundary/evidence 全部场景，确认无 skip、xfail、timeout、real external effect 或 descendant leak
- [x] 10.3 运行完整 diagnostic qualification、相关 package/app pytest、ruff 与 `uv run python -m openzyme_host_api.evals`
- [x] 10.4 运行 `./scripts/check-mainline.sh`，确认 mainline subset 绿色但仍被正确标记为 non-admissible
- [x] 10.5 运行 OpenSpec strict validation 与 implementation-to-artifact verify，逐条审计本 spec 的 14 项 requirement 和所有 scenario 均有直接证据
- [x] 10.6 提交全部资格体系、P0 closure、AOX gate 与文档变更后，从 canonical clean HEAD 在 checkout 外生成首个 full `admission` report
- [x] 10.7 用当前 checkout 的 pure verifier 独立验证 admission report，确认 exact clean commit、full selection、十个 family satisfied、零 open P0 与所有 digest 一致
- [x] 10.8 验证 AOX 在缺失/错误 report 时仍于任何 effect 前 NO-GO，在 exact report 下仅变为可进入独立外部门禁且没有实际启动 r48/live
- [x] 10.9 完成 requirement-by-requirement completion audit，确认 machine/admission evidence、GAP/P0 refs、文档、OpenSpec 状态与工作树一致后，才记录“允许另行恢复 AOX live campaign”结论

## 11. post-r73 source 与 causal evidence deletion-first repair

- [x] 11.1 将 r73 封存为 stale conductor HEAD shadow truth、错误丢弃首份 789f1c1 report、串行重复 full admission 及 qualification timeout 所致的 prelive conductor/qualification blocked（非 canonical NO-GO），并声明其 report/reproduction/stop state 与 persistent goal 全部不可复用
- [x] 11.2 删除 Host production package 中无产品 caller 的 pytest qualification runner、duplicate process executor、late source sampling 与 fallback gap cascade；把 orchestration 移到 repository `scripts/` plane，并且仅通过 `scripts/test_gate/runner.py` 这一唯一 bounded process executor 执行
- [x] 11.3 在 checkout lock admission 后封存 exact source identity，并在 collection、harness、scenario 与 publication phase 逐段 revalidate；用 source-bound bounded process receipts、fail-fast selected chain、earliest typed cause 与未执行场景闭包替代 digest-only timeout/cascade
- [x] 11.4 显式升级 machine report 与 AOX qualification receipt 到 current `@2`，保留 historical `@1` closed read-only compatibility，但 current AOX admission 必须拒绝 `@1`、partial evidence、source drift 与 causal receipt drift
- [x] 11.5 把 operator-retirement 的亚秒 real-clock policy 改为 deterministic semantic checks，并只保留一个宽限 bounded process-containment probe；补 source drift、phase fail-fast、partial run、receipt tamper 与 legacy-schema negative controls
- [x] 11.6 同步 invariant registry、resource manifest、OpenSpec、主架构、`docs/v3/` 与 fresh Codex goal，运行全部 non-live gates 和一次明确 non-adoptable clean full diagnostic，证明 production code 净删除后提交本地 commit，且不启动下一 rNN/live/MICU/provider/HPC/Chrome
