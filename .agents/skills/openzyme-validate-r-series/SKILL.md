---
name: openzyme-validate-r-series
description: 在 EnzymeDesign 仓库中准备、执行或裁决全新的 OpenZyme AOX/HMM R 系列验证。用户要求就绪审计、qualification/admission、精确授权计划、获批的 live rNN campaign、封存证据或 canonical GO/NO-GO 核验时使用。默认只读；不得用它诊断并实施系统性修复、修改代码或提交 commit。
---

# OpenZyme R 系列验证

把 Codex 保持在 OpenZyme 产品 runtime 之外，只编排当前公开接口、保存命令 receipt，并依据当前 canonical evidence 裁决测试资格。让 OpenZyme agent 自由决定科学计划、tool 顺序、delegation、试错、报告时机与业务终态。

## 先确定本轮权限

只从用户当前消息和仍然有效的精确批准确定本轮允许的最高层级，不从 goal、历史批准、工具成功或前一阶段完成推断下一层权限：

1. **只读 audit**：读取代码、合同、public surface 与既有冻结 evidence；不运行 qualification，不写 admission/authority state，不启动 live。
2. **Preparation/admission**：仅在用户明确批准对应准备范围后运行 current non-live qualification、pin、plan publication 或合同允许的其他准备动作；不得消费 live authority 或创建 attempt。
3. **Live campaign**：仅在用户批准当前 exact plan、digest、预算、external effects 与 stop conditions 后执行批准范围内的 public 操作。

到达下一人工授权门时只做一次能够证明 gate 的最小检查，报告 `workflow_status=blocked`、`blocked_on=manual_authorization`、所需批准和保持不变的 canonical state，然后立即停止。不要重复三次扫描、轮询或恢复来寻找同一授权。若 Codex 持久 goal 的状态工具要求多轮重复阻塞才能正式标记 `blocked`，后续 continuation 只确认没有新授权；不得重新运行 readiness、qualification、命令或 evidence 收集。

## 每轮重新发现当前事实

从仓库根目录开始，并按需要读取：

- `AGENTS.md`；
- `docs/OpenZyme架构设计.md` 与 `docs/v3/README.md` 指向的稳定合同；
- `docs/v3/aox-r-series-codex-goal.md`；
- `docs/v3/aox-hmm-blank-world-cutover.md` 的 current contract 和 frozen evidence index；
- `docs/v3/architecture-qualification/README.md`、current registry/resource manifest；
- active OpenSpec、当前实现、public Host API/CLI 及其 `--help`。

以当前代码、active OpenSpec 和 current-contract 文档为事实来源。历史 incident 只作为冻结证据，不能恢复其中已退役的 observer、driver、browser helper、private finalizer 或 CLI。

动态解析 clean HEAD、worktree、最新 canonical rNN、current schemas、qualification selection、MICU ledger 和 public capabilities。不要硬编码或预生成 rNN、HEAD、task/lane/envelope/attempt identity、action order、schema version 或 command list。旧 campaign 的 plan、authority、slot、root、session、effect、receipt、bundle 和 decision 一律不可复用，除非当前合同明确把它们定义为只读兼容输入。

## 保持真实产品边界

- 只使用 current public Host API/CLI 和无业务判断的 process/evidence shell。
- 不直接读取或修改 SQLite，不调用 private repository/service、provider adapter、runner helper、SSH、Slurm 或 HPC 内部接口。
- 不创建 observer、watcher、automatic campaign loop、drive-until-terminal、synthetic wakeup、response veto、hidden fallback、automatic approval 或 automatic retry。
- Host 独占 canonical session/task/lane/attempt/report、approval、lease/fencing、unknown/external effect、quiescence、provenance 与 isolation 真状态。
- Offline verifier/reducer 是唯一 GO 权威；Codex prose、exit code、局部 task label、fixture 或 process retirement 不能替代它。
- 将模型的合法策略变化当作可观察行为；不得用 exact trace、phase matcher 或规定下一 tool call 的方式纠正 agent。

## 执行验证

1. 先完成一次 bounded read-only readiness audit，确认 source identity、worktree、current contract、public reachability、冻结历史、预算和待授权阶段。
2. 只在当前授权允许时进入 preparation；任何 source、identity、registry、output target 或 prerequisite drift 都立即停止。
3. 只在 exact live approval 有效时消费对应 one-use authority，并只经 public Host surface 建立 fresh state。
4. 一次只发出一条 command。若命令 yield `cell_id` 或 `session_id`，只能恢复该 exact handle；handle 失联时做有界只读检查后停止，不重发等价命令、不换 output、不自动 recovery。
5. 每个 bounded action 后先读取 public ToolResult、FailureObservation、canonical wake facts、events、workspace、pending approvals 与 export，再自行决定唯一下一步 public action或停止。
6. 新出现的 manual approval 进入同一个单次授权门；不得自动批准。Runtime idle、no wakeup、zero-signal drain、tool success、child exit 或 process settlement都不自动构成业务终态。

不要把 operation failure 自动升级成 campaign failure。保留 earliest source-bound typed cause、effect certainty 和 wrapper；只有 current canonical state 与 selected-chain contract 能决定是否仍具备继续资格。

## 证据纪律

严格区分封存观测、依据当前源码得出的推论和尚未证实的假设。可以自由调查、比较实现并形成假设，
但不得把假设写成权威原因（canonical cause），也不得仅凭假设请求或执行状态变更、纠正后重试
（corrected retry）或授权消费（authority consumption）。当前公开证据未给出内部原因时，如实标明
具体原因尚未证明并停在现有权限边界；源码检查可以缩小假设范围，却不能改写已经封存的证据。

检查配置时只报告与判断相关的存在性、类型、来源和经过脱敏的字段标识。不得打印密钥、令牌、凭据、
私有定位信息或其他机密值；内部 `details` 只有在产品公开契约明确投影后，才能作为公开事实使用。

## 裁决与移交

只接受 current schema、current full qualification receipt、sealed public evidence 与 current offline verifier/reducer 结果。历史 report/receipt 仅按当前兼容合同读取，不能升级成 current admission 或 GO。

若失败或失去资格，立即停止新的 live action，不修改仓库，并报告：

- exact HEAD、rNN、campaign/plan/authority 和真实 control identities；
- earliest typed cause、outer wrappers、effect certainty 与 external effects；
- MICU/cost/time delta、process settlement 和完成/未完成状态；
- 哪些 state 永久不可复用；
- failure 属于产品、Harness、supervision、provider、环境还是模型策略；
- 交给 `openzyme-repair-r-series` 的 frozen evidence 入口。

只有 current canonical GO 才表示 validation 成功。除此之外如实报告 nonterminal、ineligible 或 blocked，并停在真实边界。
