---
name: openzyme-repair-r-series
description: 在 EnzymeDesign 仓库中只读诊断并在明确批准后实施 OpenZyme AOX/HMM r-series 系统性修复。用户要求“检查下一轮 r 系列问题”、分析 frozen rNN failure、判断最近提交责任、制定 deletion-first 方案、实施获批 Phase 2、运行 non-live 验证或明确要求本地 commit 时使用。不得用它启动下一 rNN、live、MICU、provider、HPC 或 Chrome。
---

# OpenZyme R-Series Repair

持续消除 r-series failure 背后的系统性原因，而不是让一条固定 trace 勉强通过。优先净删除错误抽象、合并重复真相，并保留真实 authority、approval、fencing、unknown/external effect、provenance 与 isolation 边界。

## 先确定本轮阶段

只执行用户当前明确授权的阶段：

1. **只读诊断**：检查 frozen evidence、代码、合同和历史；不修改、不提交、不运行 qualification/live。
2. **实施修复**：只有用户明确批准当前诊断报告中的具体方案后才修改。批准必须能绑定方案范围；旧批准不能授权新问题。
3. **提交**：只有当前授权明确包含 commit 时才创建本地提交。
4. **下一轮检查**：修复完成后必须重新获得批准；不得自动搜索下一问题或启动独立 validation。

到达下一人工授权门时只做一次最小必要校验，报告 `workflow_status=blocked`、`blocked_on=manual_authorization`、待批准方案和当前安全停止状态，然后立即停止。不要重复三次检查同一授权。若 Codex 持久 goal 的状态工具要求多轮重复阻塞才能正式标记 `blocked`，后续 continuation 只确认没有新授权，不重跑诊断、测试或 diff。

## 重建失败事实

从仓库根目录开始，读取 `AGENTS.md`、current code、active OpenSpec、`docs/OpenZyme架构设计.md`、`docs/v3/README.md` 指向的稳定合同、`docs/v3/aox-hmm-blank-world-cutover.md` 和最新 frozen rNN evidence。

1. 固定失败运行使用的 exact commit、canonical decision、MICU ledger、runtime commands、task board、conversation/tool traces、attempt、selection/report/closure、process supervision 和 external effects。
2. 比较失败 commit 的前后差异，明确最近修复是否具有因果责任；不要仅因时间相邻归因。
3. 从最早有证据的 source-bound typed cause 开始构造完整 causal chain。Outer wrapper、drain exhaustion、missing-control、digest 或最终 fatal label只能追加，不能替代 inner fact。
4. 区分真实安全边界、Harness 策略拦截、重复 lifecycle/readiness truth、identity/projection drift、stale contract/fixture、process containment、provider/环境错误与纯模型策略问题。
5. 使用 `rg` 和真实调用路径审计全仓同类机制，不局限于最新 trace。检查重复状态机、shadow identity、exact matcher、synthetic wakeup、response veto、hidden fallback、historical assertion、test-only production substitute，以及 fixture 与真实 API/SQLite/runtime composition 的偏差。

只读阶段不得启动 rNN、qualification、MICU、provider、HPC、Chrome 或真实外部 effect，也不得以重建、补写或升级历史 evidence 的方式制造 current proof。

## 提交 deletion-first 方案

诊断报告至少说明：

- root cause、完整失败链和最近提交的责任；
- 为什么现有静态检查、fixture 或 qualification 没有发现；
- 所有已发现的同类风险点；
- 建议删除、合并、保留的机制及其真实约束理由；
- 预计生产代码净删除量；
- 实施文件、回归测试、OpenSpec、`docs/OpenZyme架构设计.md` 与 `docs/v3/` 同步范围；
- 可能弱化的安全边界和对应 negative controls；
- 仍需用户决定的范围或权衡。

提交报告后进入单次人工授权门并停止，不提前编辑。

## 实施获批修复

1. 重新确认当前 HEAD/worktree 与获批方案仍匹配；发生实质 drift 时停止并重新提案。
2. 若涉及 Harness、runtime、protocol、supervision、public contract 或 V3 架构，创建或更新 OpenSpec，并同步主架构文档和相关 `docs/v3/`。
3. 删除错误抽象的完整生产调用链、状态、repository、tool、projection、prompt、测试和现行文档合同；不要用新的状态机、phase、signal reason、fallback、observer 或策略 hook 替代。
4. 合并 lifecycle/readiness truth owner，同时保留并强化真实 authority、approval、fencing、unknown/external effect、provenance、quiescence 与必要 isolation。
5. 保持 agent 策略自由。测试真实边界和状态变换，不固定 action order、exact trace 或科学策略。
6. 添加与风险相称的生产组合和负向控制，包括 prose/read、corrected retry、unrelated success、multiple failures、step bound、unknown effect、stale fencing、invalid authority、provenance drift、earliest cause、wrapper preservation 及历史 SQLite/migration 兼容。
7. 运行 focused tests、ruff、strict OpenSpec、non-live eval 和适用的 exact-worktree mainline。不得运行真实 rNN 或任何 live marker/external system。
8. 审查完整 diff，确认生产代码净删除、无陈旧活跃符号、无 unrelated changes。仅在当前授权包含 commit 时创建清晰的中文 Conventional Commit，并确认工作树状态。

## 停止并报告

报告实际修改、删除/保留边界、净删除统计、验证命令与结果、未证明事项，以及获授权时的 commit SHA。然后停止：

- 不自动启动 validation 或下一 rNN；
- 不自动开始下一轮 latent-risk audit；
- 不把 non-live green 宣称为 canonical GO；
- 不复用上一轮 repair approval。

若持久 goal 的最终目标是 fresh canonical GO，将当前状态报告为 `repair_complete_awaiting_validation`，等待独立的 `openzyme-validate-r-series` 和新的用户授权。
