# Implementation gap audit — 2026-08-22

## Evidence boundary

本审计针对提交 `5548ca85b0b581584379b4810e0777a6d97683b6` 及随后尚未提交的第二次正式
`@2` reset 证据。它不修改 Kernel、Plugin 或外部系统状态，不把 manifest/catalog 解析成功解释为
runtime mount，也不把 non-live 组件测试解释为真实外部 HPC cutover。

第二次 reset 是独立、完整且有效的新 occurrence，因此 task 18.9 保持完成。其后发生的 OpenSpec、代码、
配置或文档修复会使旧 final completion chain 失效，但不会倒推改写已经完成的 reset occurrence。

## Current truthful state

| Slice | State | Direct observation | Repair owner |
| --- | --- | --- | --- |
| Contracts/Kernel/Adapter/Plugin/Driver/Distribution boundary | implemented | Kernel dependency direction、closed manifests、capability/affordance 与 Workspace Runtime contracts 已存在 | existing tasks remain complete |
| EnzymeDesign manifest/catalog composition | implemented | exact component/tool/schema/bundle identities 可解析 | 14.1、14.3—14.5 |
| EnzymeDesign runtime mount | implemented | read-only proof 后精确核对 8 Adapter、mount 13 Plugin bundles、闭合 37 tool runtimes，再启用 writer 并完成真实 Session bootstrap | 19.2—19.3 complete |
| HMMER/Vina formal product execution | implemented and product-qualified non-live | Kernel-admitted ToolApplication → subordinate Driver → typed workload → Compute lifecycle → declared runner Port 已闭合；真实产品场景同时证明 immutable source、adopted inventory、result、continuation 与 Task 终态分离 | 14.6、19.4—19.5、19.8 complete |
| Product-level non-live qualification | proven on current working source | catalog 场景已如实重命名并排除产品节点；独立场景从 generic Host 经 exact mounted graph 运行 HMMER/Vina，只替换声明式 Agent-turn、Git-shaped revision 和 external runner Ports | 17.4、19.8、19.11 complete；最终 source-bound 全量 report 由 19.12 生成 |
| Workspace restart reconciliation | implemented | Store-owned SQLite ledger 原子 reserve exact provider/operation/intent/workspace generation；Podman filesystem/process/transfer 与 SSH terminal/uncertain restart tests 均保持 zero redispatch | 19.6 complete |
| Slurm restart reconciliation | implemented non-live | HPC-owned SQLite ledger 持久 submit/cancel occurrence 与 private raw handle；新 Adapter epoch 的 duplicate 只读原 receipt 或 reconcile 原 effect，EnzymeDesign 通过 selected factory 显式注入 backend/credential/ledger；产品场景不调用真实 Slurm | 19.7 complete；最终全量 report 由 19.12 生成 |
| SSH/Slurm distribution selection | selected and runtime-mounted, not cut over | EnzymeDesign runtime 核对 exact Adapter binding 并构造 Slurm runtime；remote helper 已是 exact version/build/qualification/generation resource requirement，缺失时工具被阻断 | 19.7 complete；19.9 文档总审计、真实 target cutover 另行授权 |
| Real external SSH/Slurm/HPC operation | not executed | 当前 change 仍是 non-live；不得补造 live proof | separate authorized operational change after closure |
| Formal `@2` device reset | complete | 第二次 reset 有 frozen inventory、4 项 occurrence、fresh bootstrap、独立 zero scan 和 final receipt | 18.9 |
| Final archive evidence | invalidated/pending | OpenSpec 与后续实现将改变 final source identity | 18.3—18.8、18.10、19.12 |

## Non-negotiable repair constraints

1. 不建立第二套 Plugin 架构；继续使用现有 Extension Manifest、Kernel mount、capability resolver 与
   ControlledOperation seam。
2. EnzymeDesign 只能依赖公共 Kernel application API、Extension SPI 和 capability contracts；不得访问
   Core repositories、raw SQLite、Host internals、SSH/Slurm 私有实现或 Git locator。
3. HMMER/Vina 通过 typed workload 和 explicit resolved route 组合 Compute/HPC；Agent 保留 route 与科学策略
   选择权，Harness 只呈现真实 blocker 和可用 route。
4. 所有 response-loss/restart 修复保持 zero redispatch、zero fallback、exact occurrence identity 和私密 locator
   redaction；不能用“重新执行一次”恢复不确定效果。
5. Product qualification 必须使用 generic Host 和真实内部 composition，只允许替换 invariant registry 明确
   声明的外部 Port。
6. 代码、manifest、schema、README、主架构、`docs/v3/`、OpenSpec tasks 与 evidence 在同一实施阶段更新。

## Acceptance boundary

当前 change 只有在 tasks 19.2—19.12 完成，原被重开的任务重新获得当前 source-bound 证据，并在 exact clean
source 上完成最终 closed-order validation 后才可归档。`add-openai-compatible-delivery-surface` 在此前只能继续
完善规格，不能进入 apply。真实 SSH/Slurm/HPC 环境安装、credential 配置和 live target cutover 需要后续单独
授权，不是本次 non-live 修复的隐含动作。
