## Why

r43-r47 在 focused tests 与普通非 live gate 之后，仍连续暴露 wire shape、composition authority、identity、reconciliation 和 boundedness 的跨层缺口，说明当前验证缺少能在真实 production composition 上确定性执行的架构 oracle，且正在用昂贵 live attempt 发现本应离线暴露的问题。继续 AOX live campaign 前需要先建立独立、可重复、可审计的 V3 架构资格门，再由其证据决定哪些 deferred proposal 必须晋级实施。

## What Changes

- 建立 versioned executable architecture invariant registry，逐项绑定 canonical owner、真状态、允许的 transition/projection、failure semantics、资源上限、适用 deployment profile、验证场景和证据位置；registry 只描述 harness 约束，不编码 agent 科学策略。
- 建立 non-live production-composition qualification harness：使用真实 Host composition、Core/Engine、file-backed SQLite、artifact/blob/sandbox roots、repository、projection 与 worker 路径，只在 LLM、provider HTTP、runner/HPC、Chrome 等真正外部端口使用确定性受控 adapter。
- 把 r43-r47 的失败类型转为跨层回归，并加入 crash/restart、lost callback、lease/fence、并发 claim、顺序置换、operator interrupt，以及 `limit-1 / limit / limit+1` 的边界规模矩阵；验证 effect、approval、state/event growth、terminal convergence、artifact/evidence closure 与 public projection，而不是只验证 tool 注册或单个 repository。
- 生成 machine-readable、commit-bound 的 baseline qualification report 和 human-readable GAP report。每个失败必须区分 product defect、test/harness defect、declared profile limitation 与 deferred enhancement，并关联 owner、invariant、最小复现和相关 proposal。
- 定义 P0 晋级规则：任何可能制造错误成功、重复 external effect、authority 漂移、无界循环/写放大，或不可验证 canonical evidence 的缺口，都必须先有确定性 red test，再由独立 focused OpenSpec change 实施并回归；有界且诚实 fail-closed、只影响容量/可用性/通用化的缺口可以继续 deferred。
- 增加架构资格 admission gate：AOX r48/live preflight 在当前 commit 对应的完整 qualification report 未通过、存在未关闭 P0，或 report/registry/test selection 漂移时保持拒绝；live 外部尝试不得被计作确定性架构验证，也不得用旧 GO、fixture 或归档 proposal 绕过。
- 增加 pre-work run admission：在 collection/harness/scenario 前验证 canonical output/sidecar target，并以 canonical-checkout-bound kernel-held nonblocking single-flight 拒绝同 checkout 跨 mode/output 并发复入；保留 exact `run_active` / `output_invalid` typed failure，process crash 只释放 kernel lock，不触发 recovery/relaunch。
- 将 qualification pytest orchestration 从 Host production package 删除并收口到 repository test-gate 的单一 bounded process executor；current report/receipt 升级为 `@2`，绑定 lock-admission source identity、逐阶段 source revalidation、bounded stdout/stderr/timeout/TERM/KILL process receipt 与 earliest typed failure。terminal process failure 必须 fail-fast，不再为未执行场景生成 fallback result 或 GAP cascade；历史 `@1` 仅允许只读加载且不得进入 current AOX admission。
- 同步 `docs/OpenZyme架构设计.md`、相关 `docs/v3/` 稳定文档、architecture proposal 生命周期索引和 AOX cutover 文档，明确 scoped AOX local GO 与 generic V3 architecture-qualified GO 的证明边界。
- 本 change 不预先实现全部 proposed/deferred architecture proposal，不新增产品级真状态，不改变 agent 的任务拆解或科学策略，也不启动 r48/live。

## Capabilities

### New Capabilities

- `executable-architecture-qualification`: 定义 V3 架构不变量注册、真实 composition 的确定性验证、基线/GAP/P0 判定、资格报告完整性以及 AOX live admission gate。

### Modified Capabilities

- None.

## Impact

- 新增 repository-level architecture qualification command、测试支持代码、确定性场景与报告 schema；实现落点将覆盖 `apps/openzyme-host-api` composition tests、`packages/openzyme-core` / `packages/openzyme-engines` 的真实 runtime seams、`scripts/` gate 和对应测试目录。
- 复用当前 V3 production foundation、SQLite migrations、artifact boundary、durable workers、sandbox Host gateway、runner/provider adapter SPI 与 workspace projection，不引入第二套简化 production model，也不把 `apps/openzyme-host-api.evals` 的 fixture path扩张为新架构权威。
- AOX cutover 的 operator workflow 将更严格：资格门通过前，OpenSpec `8.3-8.8`、r48 及后续 numbered live attempt 均保持暂停；当前 r43-r47 evidence 只作为永久 NO-GO/回归输入，不得 adoption。
- 验证结果可能产生后续 focused P0 changes；这些 change 各自拥有实现、迁移和产品 spec delta，本 change 只负责可执行判定、追踪和 admission closure。
