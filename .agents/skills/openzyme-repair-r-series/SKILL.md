---
name: openzyme-repair-r-series
description: 在 EnzymeDesign 仓库中诊断并在一次明确批准后实施 OpenZyme AOX/HMM R 系列修复。用户要求检查下一轮 R 系列问题、分析操作员指定的 frozen incident（包括 rNN=none preparation blocker、formal slot failure、attempt/campaign decision、evidence blocker 或平台阻塞）、判断提交责任、完成事故耦合的有界技术债审查、提出 bounded deletion-first 方案、实施 Phase 2、运行 non-live 验证或创建本地 commit 时使用。不得用它启动下一 rNN、fresh admission、live、MICU、provider、HPC 或 Chrome。
---

# OpenZyme R 系列问题诊断与修复

把本 skill 当作当前合同的路由器，而不是产品合同副本。消除失败背后的系统性原因，在事故真实调用路径内审查技术债，同时保留 agent 的策略自由和真实 authority、approval、fencing、unknown/external effect、provenance、quiescence 与 isolation 边界。

## 确定阶段和权限

只执行用户当前明确授权的阶段：

1. **Phase 1 只读诊断**：检查 frozen evidence、代码、合同和历史；不修改、不提交、不运行 qualification/admission 或任何 live action。
2. **Phase 2 实施修复**：仅在用户明确批准当前报告中的 bounded repair slice 后修改。一次批准覆盖该 slice 内的实现选择、测试修复、文档同步和代码整理；身份、根因或范围实质变化时重新提案。
3. **提交**：仅在当前授权明确包含 commit 时创建本地提交。
4. **后续检查**：修复完成后重新获得批准；不自动搜索下一问题或启动独立 validation。

到达唯一 Phase 2 人工授权门时，只报告一次 `workflow_status=blocked`、`blocked_on=manual_authorization`、待批准方案和安全停止状态，然后停止。持久 goal 若因状态工具规则需要后续回合，后续只确认没有新授权，不重跑诊断、测试或 diff。

## 重新发现当前合同

每个 fresh session 从仓库根目录完整读取：

- `AGENTS.md`、`docs/v3/README.md` 和相关 `docs/OpenZyme架构设计.md`；
- `openspec list` 指出的 active AOX/cutover change、相关 delta spec、design 与 tasks；
- 当前实现、相邻测试，以及改动涉及 public surface 时的 current CLI `--help`；
- `docs/v3/aox-hmm-blank-world-cutover.md` 的 frozen incident 索引和本次事故的 exact artifacts。

再按事故阶段沿 `docs/v3/README.md` 路由读取相关稳定主题：preparation/qualification、public conductor/approval/evidence、runtime/task/attempt、execution/HPC 或 report/finalizer/reducer。不要把本 skill、历史 prompt、旧 rNN 或示例中的 schema、命令、身份和数值当作现行真值。

若 `AGENTS.md`、稳定文档、active OpenSpec、CLI、实现或测试互相冲突：

1. 把冲突本身登记为 contract drift，不静默选择任一来源；
2. 结合 production reachability、当前公开 schema/CLI、owner registry、最近完成 change 的设计与验证证据，判断可证明的 forward intent；
3. 在 Phase 1 提出同步所有冲突来源及跨来源回归的修复方案，而不是像 validation workflow 一样只停在 drift；
4. 无法证明 forward intent 时列出真正需要用户决定的分歧并停止，不猜测。

## 先分类事故，再要求证据

先确定事故发生在哪个边界，只要求该阶段按合同本应存在的 identity 和 evidence：

- plan 发布前：`rNN=none` preparation blocker；
- authority/slot 已消费但 attempt 为零：pre-runtime 或 formal slot-failure 路径；
- 存在真实 attempt：attempt/selection/closure/campaign 路径；
- 必需 public closure capability 或 source evidence 不可取得：evidence blocker；
- 命令启动前的平台许可、环境或外部依赖拒绝：operator/platform blocker。

缺少一个从未创建的 attempt、selection 或 bundle 不是 evidence gap。分别记录 failure commit、当前 HEAD、实际命令次数、handle resume、blocked audit、已创建和明确未创建的状态，以及 MICU/provider/HPC/Chrome/external effect。

不要把一个 typed failure 或 `terminal` 默认扩大成 task、attempt、slot 或 campaign 停止。先核对它声明的 exact occurrence、effect certainty、retry eligibility、terminal scope、request/operation/idempotency identity、exact handle/receipt、authority、fencing 与剩余 budget。`no_effect` 加显式 disposition 或 completed exact reconciliation 后，agent 可以在当前授权内显式选择 identity-distinct 新 occurrence；unknown/external effect 只允许 exact public reconciliation。修复 Harness 时不得用 auto-fill、auto-retry、loop、replacement dispatch、策略 hook 或 AOX shadow FSM 代替这些通用事实。

## 保持证据层级

始终分开记录：

1. **封存观测**：由本次 frozen contract 纳入的 receipt、event、workspace、bundle、decision 或其他 canonical field；
2. **源码推论**：由当前或失败 commit 的代码路径解释出的机制，只能说明可能原因或责任；
3. **未证实假设**：尚无 source-bound evidence 支持的解释。

Canonical cause 只能来自对应 frozen contract 明确接纳的封存字段。private SQLite、内部异常、源码默认值或当前实现可以帮助定位机制，但不能改写历史 receipt、补出未公开 details 或升级为运行事实。从最早有证据的类型化原因构造因果链；outer wrapper、drain exhaustion、missing-control、digest 和 fatal label只能追加，不能覆盖 inner cause。

## 审查事故耦合技术债

技术债审查是 Phase 1 的必做项，但范围只覆盖本次事故的真实生产调用路径、canonical owner、拟修改文件及其直接组合、测试和文档边界。不得把它扩张为与事故无关的全仓风险搜索。

按本次边界交叉核对：

- `docs/v3/harness-complexity-audit.md` 中仍未关闭的相关条目与实施触发；
- `docs/v3/compatibility-sunset.md` 中相关 surface 的 caller evidence 和退役状态；
- active OpenSpec deferred item、相关架构 proposal、源码显式 debt marker（当前包括 `AOX-DEBT-*`）；
- 真实 production composition 与 fixture、静态检查、qualification 之间会掩盖同一机制的偏差。

技术债必须有现行记录、真实调用路径或可复现证据支持，不能把一般性的“还可以写得更好”或未知 latent risk 当成债务。将每项发现归入且只归入一类：

- **本轮必须处理**：不处理会使根因闭合、安全边界或跨来源语义仍然失真；
- **触发式必须处理**：本次拟修改已命中文档或源码记录的偿债触发条件；将其纳入 slice，或缩回触发该债务的修改；两者都不可行时交给用户决定；
- **允许延期**：不影响本次闭合；记录 canonical owner、风险、再次触发条件和承载它的后续工件，本轮不自动实施；
- **必要约束**：有证据证明该复杂度仍保护真实 authority、effect、兼容、隔离或并发边界，不误报为技术债。

不得静默延期已命中的显式触发器，也不得借技术债审查修复未获批准的相邻问题。

## 形成 bounded repair slice

比较 failure commit、其前后提交和当前 HEAD，按真实调用路径审计同一机制。将发现分成：

- 本次根因与必须一起闭合的生产路径；
- 同一 owner/机制内会使本次修复失真的相邻风险；
- 不影响本次闭合的后续候选。

不得把 Phase 1 扩张为自动 latent-risk audit。区分 repository defect、contract drift、技术债、environment/platform blocker、模型策略结果和 evidence gap；只有证据证明产品或合同缺陷，或现行技术债触发条件已经命中时，才提出代码修复。

Deletion-first 是删除 shadow truth、重复 owner、dead compatibility 和策略拦截时的优先原则，不是每轮必须净删除的验收指标。最小新增 public capability、类型化 evidence、迁移兼容或跨来源回归确有必要时允许新增，并说明为何不能通过删除或复用既有 owner 完成。

诊断报告至少说明：

- 事故分类、root cause、完整失败链和最近提交责任；
- 为什么现有静态检查、fixture、qualification 或组合测试没有发现；
- 事故耦合技术债清单，逐项给出来源或 marker、owner/调用路径、分类和理由；
- 本轮预计消除、保留、延期和新增的技术债；延期项必须给出风险、再次触发条件和后续工件；
- 本次 slice、删除/合并/新增/保留边界及明确非目标；
- 预计生产代码净变化，允许为负、零或正并说明理由；
- 实施文件、风险、回归测试、OpenSpec、主架构与 `docs/v3/` 同步范围；
- 可能弱化的安全边界及对应负向控制；
- 真正需要用户决定的权衡。

报告完整方案后进入唯一 Phase 2 授权门，不提前编辑。

## 实施获批修复

1. 重新确认 HEAD/worktree、事故 identity、获批 slice、技术债分类和显式触发器；发生实质 drift 时停止并重新提案。
2. 只实施获批的“本轮必须处理”和“触发式必须处理”项；不得顺手偿还“允许延期”项。
3. 删除错误抽象的完整生产调用链；不要用新状态机、phase、signal reason、fallback、observer 或策略 hook 替代。需要新增时复用 canonical owner，并保持职责单一。
4. 涉及 Harness、runtime、protocol、supervision、public contract 或 V3 架构时，更新 active OpenSpec、主架构文档和相关稳定文档；同步修正 `AGENTS.md` 等仓库级现行指导中的冲突语义。
5. 同步更新适用的技术债台账和源码 marker。只有完整触发条件、生产路径和回归证据均闭合时才能标记已偿还；不得静默删除未完成项。兼容 surface 的删除必须满足 caller evidence 和 sunset gate。
6. 保持 agent 策略自由。测试真实身份、权限、状态变换、因果保真和 effect 边界，不固定 action order、exact trace 或科学策略。
7. 对 continuation 修复，验证 occurrence-local terminal、exact idempotent convergence、receipt-written/envelope-missing crash window、no-effect disposition/new-identity gate、unknown-effect reconciliation 与 authority/budget 负控；只有最后且唯一的 current successful mutation 可 exact 重入，GET、历史/较早/多个缺口与 drift 必须 fail closed；不得把某一 runner/provider 的 action 顺序写成 Harness 策略。
8. 按本次风险选择 production composition 和负向控制，不机械复制固定测试清单；保留历史 SQLite/schema/evidence 的只读兼容与 current non-adoption gate。
9. 为本次漂移建立跨来源语义闭合：从实现导出的 current owner/schema/capability 约束 active OpenSpec、稳定文档和仓库指导；`openspec validate --strict` 只证明单个 change 合法，不能替代该检查。配置 profile 必须由 settings/reliability resolver 实际消费的 executable descriptors 与 runtime normalizer constraint owner 导出；不得在 candidate、skill、文档或测试中复制 env prefix/name allowlist 第二真值，且 credential identity 只绑定 presence、unlisted environment 不得进入 candidate identity。
10. 运行 focused tests、Ruff、适用的 strict OpenSpec、non-live eval 和 exact-worktree mainline。不得启动 fresh admission、真实 rNN、任何 live marker 或外部系统。
11. 审查完整 diff、陈旧符号、unrelated changes、生产代码净变化和技术债净变化。仅在获批时创建清晰的中文 Conventional Commit，并确认工作树状态。

## 停止并报告

报告实际修改、删除/合并/新增/保留边界、生产代码净变化、技术债的消除/保留/延期/新增情况、验证结果、未证明事项和 commit SHA，然后停止：

- 不自动启动 validation 或下一 rNN；
- 不自动开始下一轮 latent-risk audit；
- 不把 non-live green 宣称为 canonical GO；
- 不复用上一轮 repair approval。

若持久 goal 的最终目标是 fresh canonical GO，报告 `repair_complete_awaiting_validation`，等待独立的 `openzyme-validate-r-series` 和新的用户授权。
