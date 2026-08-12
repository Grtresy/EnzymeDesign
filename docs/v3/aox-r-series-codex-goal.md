# AOX R 系列 Codex 验证与修复目标

本页只定义如何启动 `openzyme-validate-r-series`、`openzyme-repair-r-series`，以及 goal 应承载的授权信息。产品合同、CLI 参数、schema、配置值、证据结构和终局规则以 `docs/v3/README.md` 路由的稳定文档、active OpenSpec 与当前 public CLI 为准，不复制到 goal 或 skill。

## 验证 goal

```text
/goal 在当前 EnzymeDesign checkout 使用 $openzyme-validate-r-series 启动一轮全新的 AOX/HMM R 系列验证。
批准执行一次只读就绪审计和完整 preparation；发布 exact plan 后停在唯一人工 live 授权门。
收到该 exact plan 的批准后，在批准的预算与 effect 闭集内持续执行，直到 canonical GO、canonical NO-GO 或真实 blocker；同一授权不重复询问。
不得修改仓库、启动 repair，或在本轮终局后自动开始下一 rNN。
```

goal 只回答“本轮要达到什么结果、允许哪些阶段和外部影响、在哪个人工门停止”。执行细节由 skill 在当前 checkout 中重新发现。用户若只批准 preparation，该批准不消费 live authority；用户若批准已发布的 exact plan，则同一 plan/slot/authority、预算和 effect 闭集内的显式 public approval resolution 与后续 bounded action 不再重复申请业务授权。

平台执行许可不是第二轮业务授权。已获批准的动作需要本地 IPC、远程 runner 或其他平台能力时，Codex 通过工具机制申请；实际 target、operation、预算、identity 或 effect 扩大时，才返回新的人工授权门。

这条通用规则不能把一次已经实际发出的失败命令变成可重发的“权限探针”。current preparation contract
若把某一步声明为普通 sandbox 中的首次且唯一调用，则平台能力必须在发出前闭合；发出前不可用时以
`ledger_execution_count=0` 停止，发出后的 nonzero 已消费唯一调用，平台提权不能授权换 launcher、cache、
environment 或 permission 重发，late stdout/snapshot 也不得采用。preparation ledger 的具体公开
entrypoint、literal path 和 no-retry 规则仍由 validation skill、active OpenSpec、稳定文档与 current public
CLI 共同定义；`pin` / `preflight` 已文档化的预先平台许可不受影响。

## 修复 goal

```text
/goal 在当前 EnzymeDesign checkout 使用 $openzyme-repair-r-series 处理操作员指定的最新 frozen incident。
先只读诊断，完成事故耦合的有界技术债审查并提出一个 bounded repair slice，然后停在唯一 Phase 2 授权门。
收到一次明确批准后，在该 slice 内完成代码、OpenSpec 与文档同步，运行全部适用 non-live 验证并创建本地提交。
不得启动 fresh admission、下一 rNN、live、MICU、provider、HPC 或 Chrome。
```

修复 goal 只指定事故、两阶段权限和完成条件。skill 必须按事故实际边界区分 `rNN=none` preparation blocker、零 attempt formal slot failure、真实 attempt/campaign、evidence blocker 与 operator/platform blocker；不存在的后续 identity 不能被误报为缺失 evidence。Phase 1 报告完整 bounded slice 后只进入一次授权门；同一批准内的实现选择、测试修复和代码整理不再逐项申请。

Deletion-first 只优先删除 shadow truth、重复 owner、dead compatibility 与策略拦截，不要求每个正确修复都产生生产代码净删除。必要的最小 public capability、类型化 evidence、历史兼容或跨来源回归可以新增，但必须说明 canonical owner 与不可替代性。

技术债审查只覆盖事故真实调用路径、canonical owner、拟修改文件及其直接组合边界，不扩张为无关的全仓 latent-risk audit。命中文档或源码显式偿债触发器的项目必须纳入本次 slice，或缩回触发它的修改；允许延期的项目必须记录 owner、风险、再次触发条件与后续工件，不得静默遗忘。

## 验证的当前事实来源

fresh session 必须从以下入口重新推导，不使用历史 prompt 或旧 rNN 状态：

1. `AGENTS.md` 与 `docs/v3/README.md`；
2. `docs/OpenZyme架构设计.md` 的相关架构段落；
3. active AOX/cutover OpenSpec delta；
4. qualification registry/resource manifest 与 test-gate 文档；
5. public cutover/Host CLI 的当前 `--help`；
6. 本轮 actual-launch preflight、slot claim、Host startup或pre-child-ready failure receipt、execution contract、sealed public response 与 canonical export。

文档、OpenSpec、CLI 和实现出现冲突时停止并报告 contract drift，不由 skill 保存旧值补齐。历史 incident 只作为不可变证据索引，见 [aox-hmm-blank-world-cutover.md](aox-hmm-blank-world-cutover.md)。

上述“停止”适用于 validation preparation。Repair Phase 1 应把 contract drift 本身作为候选根因，核对 production reachability、当前公开 schema/CLI、owner registry、最近 change 的设计和验证证据，提出同步全部冲突来源及跨来源回归的方案；只有 forward intent 仍无法证明时才请求用户决策。

## 正式 public conductor

preflight 必须在 slot claim/root 前从 pinned profile重跑 full actual Podman/image/SDK/scientific-backend resolver与immediate unchanged guard；config-only equality不是 admission。actual runtime失败只走current pre-claim failure，不创建claim/root、不换slot、不retry。guard通过后，preflight再创建slot claim、blank-world root和prelaunch receipt，并发布source-bound、无绝对路径的current conductor execution contract `@2`。Codex只使用该合同声明的formal public CLI入口：前两次成功动作必须逐字闭合exact session create与唯一raw canonical message + pinned `workflow_ref`；之后禁止第二条message，scientific authority只经专用late-bound grant。入口闭合后，CLI透传由Codex选择的其余合法public Host command，并机械绑定同一receipt chain与一次sealed response，不选择科学动作、drain cadence或形成自动循环。历史contract `@1`不能执行。

每次 bounded drain 的 admission 与唯一 terminal status、最终 workspace/events，以及存在真实 attempt 时的 closed-attempt export，都必须在 Host 仍可访问时封存。随后由公开 retirement-readiness seal 证明：

- 每个 formal public response 恰有一个 source-bound envelope；
- 所有 bounded drain 已有 terminal status 并与 `runtime.command.finished` 一致；
- 最终 workspace/events 晚于所有 public mutation；
- 最终 workspace/events 也晚于每个 terminal status，且full event replay实际包含对应 finished event；
- attempt cardinality 与 closure mode 明确；
- receipt 和 response bytes 在封存后没有漂移。

在command仍nonterminal时封存的workspace/events不能被稍后public status、private SQLite或transcript回填。
若Host与原授权范围仍可用，只能先封存terminal status，再追加fresh workspace/full events；否则保持
evidence blocker，不重复drain、不合成failure、不运行finalizer/verifier/reducer。

readiness 缺失或失败时，supervised Host 拒绝操作员退休并保持运行。readiness 成功后，attempt finalizer 或 zero-attempt slot-failure finalizer只消费该 receipt 绑定的 exact sources，不再由 agent 手工拼接 response 路径。该机械门不判断业务成功、不自动 approval、drain、retry、rollover 或 closure。
完整封存的脱敏 4xx/5xx 不会阻止 readiness，但不能进入 positive bundle；只有 canonical final state 与 source-bound typed cause 同时满足零-attempt failure 合同时，才能形成正式 NO-GO。

若Host在child-ready前的sandbox bootstrap失败，尚不存在可封存的public chain。只有parent在child存活时
验证exact PID/PGID/start-time，退休完整process group，并证明fresh root、SQLite、mutation writer、effect
目录与MICU均未变化，才可生成pre-child-ready failure receipt并进入formal slot-failure `@2`分支；不得
伪造startup/supervision/readiness。缺少任一证明时如实停在evidence blocker，历史r76不回填。

## 终局

- plan 发布前失败：`rNN=none` 的 preparation blocker；
- current formal authority 已消费、slot claim/root 尚未创建且 source-bound preflight-failure receipt 完整：专用 verifier/decision 产生 canonical NO-GO；缺少该 current receipt 的历史 r75 保持 blocked，不回填；
- 正式 slot 已消费、Host已child-ready且final workspace为零attempt、public source chain与typed failure完整：formal slot-failure `public_host` verifier/reducer产生canonical NO-GO；
- 正式 slot 已消费、Host在child-ready前失败且current process/root/no-effect receipt与unchanged MICU完整：formal slot-failure `pre_child_ready` verifier/reducer产生canonical NO-GO；缺少current receipt的历史r76保持blocked，不回填；
- 存在真实 closed attempt：走 attempt bundle verifier，再由 campaign reducer 产生 GO/NO-GO；
- public closure capability 或必需 source evidence 确实不可取得：如实报告 evidence blocker。

缺少 scientific attempt 本身不是 evidence blocker，也不得伪造 attempt bundle。Offline verifier/reducer 始终是唯一正式裁决权威；Codex prose、进程退出和局部状态不能替代它。
