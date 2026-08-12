---
name: openzyme-validate-r-series
description: 在 EnzymeDesign 仓库中准备、执行或裁决全新的 OpenZyme AOX/HMM R 系列验证。用户要求就绪审计、qualification/admission、精确授权计划、获批 live rNN campaign、封存证据或 canonical GO/NO-GO 核验时使用。每轮必须从当前文档索引、active OpenSpec、public CLI 和 source-bound receipt 重新推导合同；默认只读，不得实施修复、修改代码或提交。
---

# OpenZyme R 系列验证

把 Codex 保持在产品 runtime 之外，只编排当前公开接口和无业务判断的 process/evidence shell。OpenZyme agent 自由决定科学计划、任务分解、tool 顺序、delegation、试错、报告时机与业务终态。

## 先确定权限

只从用户当前消息和仍有效的精确批准确定最高权限，不从 goal、历史批准、工具成功或阶段完成推断下一层权限：

1. **只读 audit**：读取当前合同、代码、public surface 与冻结 evidence；不运行 qualification，不写 admission/authority state，不启动 live。
2. **Preparation/admission**：仅在明确批准后运行当前 non-live qualification、配置检查、pin 和 plan publication；不得消费 live authority 或创建正式 slot。
3. **Live campaign**：仅在用户批准当前 exact plan、digest、预算、external effects 与 stop conditions 后执行。该批准覆盖同一 plan/slot/authority、预算和 effect 闭集内的公开 approval resolution 与继续动作；不得重复询问。身份、预算、计划或 effect 范围发生实质变化时，才进入新的人工授权门。

平台执行许可与 OpenZyme 业务授权彼此独立。业务范围已经覆盖时，按工具机制申请必要的平台许可，不要求用户复述同一业务批准。平台在命令启动前拒绝执行时，报告操作员环境 blocker，不伪造产品失败。

任何会传递调用 actual rootless Podman launch resolver 的 `pin` 或 `preflight`，都必须通过当前文档声明的
`uv --project apps/openzyme-host-api run openzyme-aox-cutover ...` 公开入口执行，并在工具调用上显式使用
`sandbox_permissions=require_escalated`。不得在会把 rootless runtime 目录重新挂载为只读的普通 Codex
文件系统 sandbox 中直接调用 `.venv/bin/openzyme-aox-cutover ...`；Host 上单独执行 `podman info` 成功，
不能证明不同外层 launcher 中的子进程具备同一执行能力。

在消费 one-use authority 前，必须确认 exact formal `preflight` launcher 的上述平台许可已经可用；
平台不能在消费前授予该能力时，以未消费 authority、零 product execution 的 operator/platform blocker
停止。不得先消费 authority，再用 sandboxed `preflight` 探测权限，也不得把已知的外层只读挂载映射为
OpenZyme 产品或 Podman installation failure。该平台许可不扩大 exact plan、预算或 external-effect 授权。

preparation 的 `check-config` 与不带 `--output` 的累计 MICU `ledger` 是 current source 证明只读、零 external
effect 的 effect class。public owner identity 始终是 `[project.scripts]` 映射
`openzyme-aox-cutover = "openzyme_host_api.aox_cutover_cli:main"`；`uv --project ... run` 与 current-checkout
`.venv/bin/openzyme-aox-cutover` 只是可选 launcher，不得 private import/handler 直调或固定唯一 launcher。
`check-config` 保留完整 command-scoped environment；`ledger` 从 exact pinned launch profile 一次只读取得、
验证 literal `ledger_path`，且不使用 `--output`、shell substitution、ambient 或命令内 profile lookup。

这两个只读命令首次在 ordinary sandbox 明确因 sandbox/launcher rejection（例如 `uv` cache `EROFS`）
终止，且同一结果没有 AOX structured result、typed failure 或 unknown effect 时，允许一次 platform recovery：
exact argv、environment、cwd、path、output 与 launcher 全部不变，只把
`sandbox_permissions` 改为 `require_escalated`。成功时分别报告 `launcher_invocation_count=2`、
`platform_escalation_count=1`、`adoptable_product_result_count=1`；不得依赖不可观测的 handler-start。
若首次已有 structured product result、typed failure、unknown effect，恢复会改变任一输入/launcher，命令
并非该只读 effect class，或已有一次 escalation / 两次 issuance，则禁止恢复。exact yielded handle resume
不是新 invocation；handle 失联仍 fail closed，late result 不采用。

full qualification、Podman-transitive `pin` 与 formal `preflight` 属于已知需要 sandbox 外能力的不同
effect class，必须首次 issuance 前申请窄范围 `require_escalated`，失败即停，不以 ordinary sandbox 探测
或套用只读恢复。平台许可不扩大 preparation/live 业务授权、authority、预算或 effect 闭集。

到达人工授权门时只做一次最小必要校验，报告 `workflow_status=blocked`、`blocked_on=manual_authorization`、待批准对象和保持不变的 canonical state，然后停止。持久 goal 若要求多轮才能标记 blocked，后续只确认没有新授权，不重跑检查、qualification、命令或 evidence 收集。

## 强制读取当前合同

每个 fresh session 从仓库根目录开始，完整读取以下稳定入口：

- `AGENTS.md`；
- `docs/v3/README.md`；
- `docs/v3/aox-r-series-codex-goal.md`；
- `docs/OpenZyme架构设计.md` 中与本轮阶段相关的当前架构；
- `openspec list` 指出的 active AOX/cutover change 及其相关 delta spec；
- 当前 public CLI 的顶层和本阶段子命令 `--help`。

随后按 `docs/v3/README.md` 的当前路由读取阶段文档，不把本 skill 当作产品合同副本：

| 阶段 | 必须读取的当前主题 |
|---|---|
| readiness / qualification | architecture qualification README、registry、resource manifest 与 test-gate 合同 |
| check-config / pin / plan | AOX cutover current contract、launch/config OpenSpec 与 public cutover CLI help |
| 首次正式 public mutation | public interfaces 中 conductor、receipt、response sealing 与 late-bound authority 合同 |
| runtime drain / approval | agent runtime、top-level LLM loop、failure/attempt 合同与 public Host CLI help |
| final read / retirement / reduction | public export、process settlement、slot-failure、finalizer、verifier 与 reducer 合同 |

在首次不可逆动作前和每次阶段转换前重新核对对应文档。只在启动时“读过一次”不构成后续阶段的执行依据。

若文档、active OpenSpec、CLI help 与当前实现不一致，报告 exact contract drift 并停止。不得自行选择其中一个，也不得用 skill 中的旧知识补齐。

## 先形成阶段执行合同

每个阶段在发出状态变更命令前，先形成一份短小、可核验的阶段合同：

- 当前 HEAD、worktree 与权威文档/章节；
- current schema/capability 和 public command surface；
- 本阶段用户授权与真实 effect 边界；
- 输入、identity、source digest 与前置条件；
- 必须从动作开始持续封存的 receipt、response 和 output；
- current defaults/bounds 及其来源；
- 成功、失败、停止和下一阶段条件。

所有可变值都从当前 checkout、public preflight/CLI 和封存 receipt 动态解析。不得硬编码或预生成 rNN、HEAD、schema version、配置值、fixture 数量、task/lane/envelope/attempt identity、action order、step bound 或 command list。

阶段合同未闭合时不得发出不可逆动作。公开 preflight 已发布机器可读 execution contract 时，必须使用它返回的 formal public command、evidence sink 和 retirement gate；不得退回手工拼装可选 receipt 参数。

## 保持产品和策略边界

- 只使用 current public Host API/CLI 与合同声明的 policy-free process/evidence shell。
- 不直接读写 SQLite，不调用 private repository/service、provider adapter、runner helper、SSH、Slurm 或 HPC 内部接口。
- 不创建 observer、watcher、automatic campaign loop、drive-until-terminal、synthetic wakeup、response veto、hidden fallback、automatic approval 或 automatic retry。
- Host 独占 canonical session/task/lane/attempt/report、approval、lease/fencing、unknown/external effect、quiescence、provenance 与 isolation 真状态。
- Offline verifier/reducer 是唯一 GO/NO-GO 权威；Codex prose、exit code、局部 task label、fixture 或 process retirement不能替代它。
- 机械合同只约束身份、权限、证据、boundedness 和退休条件；不得规定 agent 的科学路线、tool 顺序、exact trace 或下一次调用。

## 执行 preparation

1. 完成 bounded read-only readiness audit，动态确认 source identity、clean worktree、current contract、public reachability、冻结历史、预算、启动配置来源和待授权阶段。
2. 按 qualification 文档给出的当前唯一公开入口运行一次 full admission。若以 `functions.exec`
   包装 `exec_command`，则 yielded `cell_id` 只拥有 `outer cell` 的 JavaScript 生命周期，只能用
   `functions.wait` 恢复；nested `exec_command` 才拥有 `inner session`。必须向 conductor 完整传播
   nested `structured result`，禁止只投影 `.output` 或丢弃 `session_id` / `exit_code`。当
   `inner session` yield `session_id` 时，只能用 `write_stdin` 恢复该 session，直到其 structured
   result 返回真实 `exit_code`；`outer cell` terminal 不能替代该 terminal result。若 inner handle
   未暴露或失联，立即记为 `blocked` 并停止，不 `relaunch`、不换 output、不自动 recovery；随后出现的
   `late report` 仍受 `non-adoption` 约束，只能作为停后只读观察。
3. 在第一次 public config check 前按当前合同一次性装配完整 command-scoped launch profile。不得先以 ambient defaults 试跑再逐字段补值。
4. 配置检查和 pin 均只执行合同允许的次数。typed terminal failure 后停止，不 corrected retry；源码调查只能形成推论，不能改写 receipt。
5. 只有 qualification、pin 和 exact formal plan 都成功发布后才分配并冻结下一 rNN，并报告映射、预算、effects、stop conditions 与可复制授权语句。

plan 发布前失败记为 `rNN=none` 的 preparation blocker。旧 plan、authority、slot、root、session、effect、receipt、bundle 和 decision 一律不可复用。

## 执行获批 live campaign

1. 只在 exact live approval 有效、且 exact formal `preflight` 的 Podman 外层执行许可已在消费前闭合时，才消费 one-use authority；随后必须以同一已许可的公开 launcher 执行 preflight，并严格使用它发布的 source-bound execution contract。
2. 在调用 execution contract 声明的 supervised Host start 命令前，重新确认 exact prestart root/evidence
   仍处于 closed clean phase。只允许该公开命令在 process creation 前由 canonical ledger owner读取一次
   baseline、原子 no-replace 发布 attempt-scoped start claim并立即重读同一 ledger；不得手工创建 claim、
   standalone before snapshot、campaign-global lock或替代启动路径。child必须重验同一 claim digest与process
   epoch。既有claim、root污染、ledger drift或exclusive-create race均停止，不replay、不换slot或attempt。
3. process creation若在可验证child identity出现前失败，只接受当前合同的最小typed spawn blocker并停止：
   external effect保持unproven、retry为terminal、successor保持blocked；不得把它当作startup、supervision、
   formal slot closure、zero effect或reducer input。schema和文件名每轮从active OpenSpec、CLI与实现重新发现。
4. 每次 operator-selected public action都通过合同声明的 formal public CLI入口执行，使 receipt chain 与 sealed response 自动绑定；不得直接调用缺少该合同的普通 CLI 路径。
5. 一次只发出一条 bounded command。每次读取 public ToolResult、FailureObservation、canonical wake facts、events、workspace、pending approvals 和 export 后，由 Codex 决定唯一下一步；不得形成自动循环。
6. runtime command 的 terminal 只证明该 bounded command 已结算，不自动代表 task、attempt、slot 或 campaign 终结。保留 earliest source-bound typed cause、effect certainty 与 outer wrapper。
7. Host 仍可访问时，先完成最终 workspace、events、所有 drain admission/terminal handoff，以及存在真实 attempt 时的 closed-attempt export。随后调用 execution contract 的 retirement-readiness seal；readiness 未通过时 Host 必须保持运行，不得先退休再补采。
8. readiness 通过后才请求 supervised Host 退休。current finalizer 的 MICU before只能从start claim派生，
   再读取一次final snapshot；不得由agent手工挑选response或standalone baseline source。

正式 slot 已消费后：

- final workspace 证明恰有一个真实 attempt 时，走 closed-attempt export、attempt finalizer、offline verifier 和 campaign reducer；
- final workspace 证明 attempt count 为零且存在 source-bound typed failure 时，走 formal slot-failure seal、offline verifier 和 failure reducer，形成 canonical NO-GO；
- 缺少 scientific attempt 本身不是 evidence blocker；只有 current public closure capability 或必需 source evidence 确实不可取得时，才报告 evidence blocker。

不得把 operation failure直接升级成 campaign failure，也不得用 slot-failure伪造 attempt bundle。

## 证据纪律

严格区分封存观测、源码推论和未证实假设。只有 public contract 明确投影的字段才能成为 authoritative cause；内部异常、路径、配置值、credential 或未公开 details 不得外泄或升级为 canonical fact。

分别记录 qualification、config check、pin、public command、handle resume 和 blocked audit 次数。只有实际发出命令才增加 execution count；恢复 handle 和只读授权复核不算重试。

## 裁决并停止

只接受 current schema、current full qualification receipt、sealed public evidence 与 current offline verifier/reducer 结果。报告 exact HEAD、rNN、campaign/plan/authority、真实 control identities、earliest cause、effects、预算/MICU变化、process settlement、不可复用 state 和 frozen evidence 入口。

canonical GO 或 verified formal-slot-failure/campaign reducer 得出的 canonical NO-GO 才是正式终局。除此之外如实报告 ineligible、nonterminal 或 blocked；不修改代码、不启动 repair、不自动开始下一 rNN。
