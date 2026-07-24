## 1. Contract registry 与 AOX 兼容边界

- [x] 1.1 在 `openzyme-core` 增加不可变 scientific workflow contract、closed operation signature、scope/role policy 与 registry 类型，并实现稳定 canonical preimage/digest。
- [x] 1.2 为 registry 实现 exact workflow/contract/digest resolve、scope-specific allowed roles、operation-compatible roles 与 role validation，禁止 unknown identity 或近似合同 fallback。
- [x] 1.3 为 contract canonicalization、role-to-operation mapping 改动触发 digest 变化、scope isolation、unsupported identity 和 public-safe projection 增加单元测试。
- [x] 1.4 冻结 AOX `aox_blank_world_selected_chain@1` 的 historical reader/validation fixture，并新增包含完整 formal/fault/probe role-to-SDK-signature 映射的 `aox_blank_world_selected_chain@2`。
- [x] 1.5 为 AOX `@1` digest 稳定性、`@2` golden digest、mapping tamper、projection/validator 一致性及旧合同不可用于新 admission 增加资格测试。
- [x] 1.6 将 Host composition、attempt admission、runtime/tool context 与 bundle verifier 切换到同一个 registry-resolved contract object，并移除 validator-only 或独立 role map 的新写路径。

## 2. Selection head 解析与 r54 崩溃回归

- [x] 2.1 增加 `ResolvedScientificSelectionHead` 与带稳定 closed code 的 `ScientificSelectionIntegrityError`，保持现有 head 五字段及数据库 schema 不变。
- [x] 2.2 在 scientific selection repository 实现单次 join 的 `resolve_head(attempt_id)`，校验 attempt、selection id 与 revision 一致性。
- [x] 2.3 将 selection mutation、closure、workspace/evidence projection 与 runtime consistency 中直接从 head 读取 lifecycle state 的路径改为 resolved head。
- [x] 2.4 让 mutation 对 known head integrity error fail closed，让 runtime consistency 将其投影为 bounded `scientific_selection_head_invalid` attention，并继续传播未知数据库或编程错误。
- [x] 2.5 增加 no-head、draft、sealed、dangling selection、attempt mismatch 与 revision mismatch 的 repository/service 回归测试。
- [x] 2.6 增加 file-backed SQLite 的 r54-shaped consistency 回归，证明 draft head 在 max-step 后不会触发 `ScientificSelectionHead.state` 属性异常。

## 3. 统一 selection evaluator 与可观察性

- [x] 3.1 在 Core 增加无 mutation authority 的 `ScientificSelectionEvaluator`、evaluation/occurrence/issue 数据模型及稳定 issue taxonomy。
- [x] 3.2 让 evaluator 从 resolved head、完整 universe、dispositions、adoptions、materializations、executions/results、authority/ownership 与 exact contract 计算 deterministic `seal_ready` 和 bounded gaps/blockers。
- [x] 3.3 将 selection seal 与 closure revalidation 改为消费同一 evaluator 结果，并删除或收敛重复的完整性校验分支。
- [x] 3.4 为缺 disposition、缺 adoption、unexpected/duplicate facts、invalid role/signature、known failure、unknown effect、active ownership、cross-attempt、authority mismatch、CAS/universe drift 增加 evaluator 与 seal/closure 一致性测试。
- [x] 3.5 扩展 `scientific.attempt.inspect` 输入与内部查询，支持 exact attempt/selection filter、稳定 occurrence 排序、bounded limit 和 opaque cursor。
- [x] 3.6 在详细 inspect page 中投影 exact head/selection/contract identity、occurrence signature/effect/disposition/adoption/materialization、allowed/compatible roles、issues 与 readiness summary。
- [x] 3.7 在 `world.inspect` 和 composite workspace 中只投影 attempt/head、gap counts、bounded ids 与 blocker codes，并保持跨 session/task authority 隔离。
- [x] 3.8 为 inspect paging 的无遗漏无重复、payload bounds、跨 session 拒绝以及 Host locator/credentials/lease/recommended-actions 不泄漏增加 tool/API projection 测试。

## 4. 原子 operation adoption

- [x] 4.1 定义 model-visible `scientific.operation.adopt` schema，要求 exact selection id、operation id、workflow role、reason code 与 idempotency key。
- [x] 4.2 在一个 repository transaction/mutation writer turn 中校验 current draft head、universe、terminal-known execution/result/approval/effect 与 exact contract 后同时写入 adopted disposition 和 matching effect adoption。
- [x] 4.3 为两条记录实现共享 normalized request digest/idempotency identity；exact replay 返回原 identities，单边或 digest 不匹配 replay 返回稳定 integrity conflict 且不修补。
- [x] 4.4 将 adoption/role/precondition error 投影为 bounded public-safe facts，包含 exact head version、current disposition/adoption、requested/allowed/compatible roles、blockers、retry boundary 与 `mutation_applied=false`。
- [x] 4.5 对 `@2` selection 禁止 `scientific.operation.disposition(kind=adopted)`，并从新 model-visible catalog 移除 `scientific.effect.adopt`，同时保留 frozen historical records 的只读兼容。
- [x] 4.6 增加 valid adoption、invalid/incompatible role、缺前置事实、第二次写入失败整笔回滚、exact replay、partial replay、legacy tool hidden 与 historical split-record read 测试。
- [x] 4.7 增加 AOX agent-facing tool contract 回归，证明每个 occurrence 可先观察 exact compatible roles，再在单次命令内原子 adoption，且 Harness 不替 agent 选择 operation 或 role。

## 5. Runtime command 真实回执

- [x] 5.1 定义 typed `RuntimeDrainCoreReceipt`、`RuntimeDrainProjectionOutcome` 与 `runtime_command_outcome@2`，并保留旧 `@1` bounded reader。
- [x] 5.2 重构 V3 runtime drain，使 scheduler batch 后立即形成不可丢失的 core receipt，再独立执行 trace/activity/consistency/event/workspace projection settlement。
- [x] 5.3 对 post-scheduler settlement failure 返回 sanitized `runtime_projection_failed`，保留 scheduler status、真实 processed count、suspended/output/event identities，并在 count 大于零时固定 `replay_safe=false`。
- [x] 5.4 将 Host runtime command executor/worker 改为消费 typed drain result；仅在 core receipt 尚未形成的 boundary exception 上允许零 processed count，catch-all 不得覆盖 partial receipt。
- [x] 5.5 增加 core/worker 测试，分别覆盖 pre-core exception、正常 completion、suspension、post-core consistency failure、event/workspace failure与历史 `@1` outcome 读取。
- [x] 5.6 增加 file-backed Host r54-shaped 回归，证明一个 signal 已 durable processed 后即使 projection 失败，command 仍报告 count=1、projection failed 与 replay unsafe。
- [x] 5.7 更新 Host API、event/status projection 及 Web UI/CLI consumer 对 `@2` 两层状态的 bounded 展示，并增加 cross-session 与私有字段不泄漏测试。

## 6. Step-budget recovery 语义

- [x] 6.1 扩展 canonical runtime failure observation，显式记录 `agent_turn_budget_exhausted`、`recoverability=agent_can_replan`、exact-signal `retry_eligibility=terminal` 与 signal-local effect certainty。
- [x] 6.2 修改 bounded teammate loop 的 max-step 终止路径，使 exact signal/turn failed terminal 且不自动 replay，同时保持 task status 与 business failure fields 不变。
- [x] 6.3 保持 source-bound deduplicated master wakeup，并从 canonical failure observation 与当前 selection evaluation 构造 bounded recovery facts。
- [x] 6.4 将 runtime consistency 的新 max-step 分类切换到结构化 error code，只为 frozen historical signals 保留只读文本匹配兼容。
- [x] 6.5 增加 scheduler/protocol/consistency 回归，证明同一 signal 不重放、不隐式加 budget、不重开 operation，master 可在新 turn 显式 replan。
- [x] 6.6 增加 controlled-operation effect preservation 回归，证明 signal-local `no_effect` 不擦除或重解释同一 exhausted turn 已产生的独立 durable scientific effects。
- [x] 6.7 闭合 post-r55 receipt 分类：只有 canonical failed teammate signal、exact budget observation、nonterminal task 与 unique source-bound master wakeup 全部成立时才把 scheduler batch 记为 completed settlement；缺 wakeup 与 master max-step 保持 failed，并增加真实 SQLite 回归。

## 7. AOX 规格、配置与稳定文档同步

- [x] 7.1 更新 active `aox-hmm-blank-world-cutover` delta spec，将 known terminal/no-effect 的同 attempt 显式处置/替换与 unknown/active/cross-attempt/authority/resource blockers 区分开。
- [x] 7.2 为 active AOX change 增加 r54 诊断 addendum：永久 NO-GO、operations 成功不等于 attempt/report/campaign 成功、selection 未闭合、receipt 曾错报、修复只面向新合同/新 attempt。
- [x] 7.3 更新 AOX non-live driver、config/pins、qualification fixtures 与 bundle verifier，使任何新 admission 只接受完整 `@2` contract identity，同时保持 r54/`@1` evidence immutable/read-only。
- [x] 7.4 同步 `docs/OpenZyme架构设计.md` 与 `docs/v3/00-harness-doctrine.md`、`04-public-interfaces.md`、`05-agent-runtime.md`、`06-top-level-llm-loop.md`、`08-failure-recovery-and-scientific-attempts.md` 的 contract、readiness、atomic adoption、receipt 和 recovery 语义。
- [x] 7.5 更新 AOX runbook/验收文档，明确 fresh clean commit、完整 non-live qualification、fresh authority plan 与用户精确批准是任何后续 live 的独立前置条件。

## 8. Non-live 验证与交付审计

- [x] 8.1 运行 scientific contract/head/evaluator/adoption、scheduler/protocol/consistency、runtime command 与 AOX focused pytest，并修复所有失败。
- [x] 8.2 运行相关 Python `ruff check`、`git diff --check` 与本 change/active AOX change 的 OpenSpec strict validation。
- [x] 8.3 运行 V3 本地 workflow eval，确认新 observation/receipt 不降低 tool、event、workspace projection 的安全边界。
- [x] 8.4 运行 Web UI `npm test` 与 `npm run build`，确认 runtime/selection 状态消费兼容。
- [x] 8.5 运行 `./scripts/check-mainline.sh` 并按 slice scope 解释或修复任何失败。
- [x] 8.6 审计最终 diff、OpenSpec checkbox、历史 r54 evidence 与 live authority 状态，确认未运行 provider/HPC/Chrome/numbered campaign、未迁移 r54、未消费或创建 live authority。
