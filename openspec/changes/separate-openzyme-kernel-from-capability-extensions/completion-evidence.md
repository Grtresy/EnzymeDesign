# Non-live completion evidence contract

## Evidence boundary

本文件是 completion evidence 的仓内覆盖索引，不是运行时 authority，也不保存可复用的绿色
receipt。最终命令的 canonical report/receipt 必须在本文件和 `tasks.md` 固定后从 exact final
source 生成到 checkout 外，并在交付说明中记录其路径与 digest。运行后再修改 source、配置、文档、
OpenSpec 或 manifest 会使这些外部证据过期，必须整组重跑。

2026-08-21 已获第二次单独授权，并在提交 `5548ca85b0b581584379b4810e0777a6d97683b6`
上执行新的完整 Store-owned `@2` reset occurrence。该次操作在删除前冻结数据库与空
repository-service 的 4 项 inventory，逐项生成 durable occurrence，再执行 exact 31-wheel EnzymeDesign
fresh bootstrap、独立只读 startup proof 与 zero scan；正式 reset receipt 为
`sha256:f523f08d26b928395c2d9269163b699f7feba954cce089a0045ea60544d20bcc`。第一次删除缺失子项日志的
历史事实没有被补造或改写。task `18.9` 因第二次新 occurrence 保持完成；Provider、SSH、Slurm、HPC、
容器、浏览器和 live campaign 均未执行。

## Current implementation gap

2026-08-22 的后续实现已把 EnzymeDesign 从 manifest/catalog activation 推进到真实 non-live product runtime
mount：read-only startup proof 仍忠实记录自身未 mount/writer-disabled，随后
`build_enzymedesign_application_runtime()` 精确核对 8 个 Adapter runtime binding、mount 13 个 Plugin runtime
bundle、闭合 37 个 Kernel/Plugin tool runtime，并且只在上述检查成功后构造 SQLite writer、Kernel gateway 与
通用 Host。该路径已完成真实 Session bootstrap；missing Adapter 会在零 mutation 下拒绝。

HMMER/Vina 已通过生产 application bridge 消费 Kernel-admitted route proof、编译 subordinate Driver
workload 并进入 Compute ControlledOperation/声明式 runner Port。该 bridge 现以一次性 post-mount binding 绑定
真实 durable service，并从 canonical PublishedRevision、publication-owned path verification、owner workspace、
authority 与 adopted binding 推导 source/admission。Compute record 已通过 Kernel-admitted
namespaced extension state 和 Store-owned SQLite coordinator/query 持久化；重启测试证明同一 request 不
redispatch，原 route/opaque handle 可结算 terminal result，Kernel continuation 与 result 在再次重启后仍可恢复。
新的 `identity-semantics.enzymedesign-product-cross-layer` 场景已从 generic Host/Session pin/authority、真实
publication 和 adopted inventory，经 affordance/route、mounted HMMER/Vina Drivers、Compute 与声明式 fake
runner，到 result validation、两条 owner continuation 和 Science validator；Task 保持 `todo`。原 catalog 场景
已如实重命名为 `wire-contract.enzymedesign-catalog` 并排除产品节点。Podman filesystem/process/
transfer 与 SSH Workspace Adapter 已改为消费 Store-owned SQLite occurrence ledger；首次 effect 前原子 reserve，
terminal/uncertain receipt 以 exact provider/operation/intent/workspace generation 持久化。跨 Host/Adapter epoch
测试证明 exact duplicate 零 redispatch，SSH uncertain occurrence 只 reconcile 原 transport identity。Slurm
submit/cancel 现在同样使用 HPC-owned SQLite occurrence ledger：opaque handle/private raw scheduler id 可跨
Adapter epoch 恢复，uncertain occurrence 只调用原 backend reconcile；EnzymeDesign application root 通过 exact
selected factory 显式注入 backend、credential resolver 与该 ledger。远端 helper 已建模为 exact 1.0.0
version/build/qualification/target-generation resource fact，缺失时 remote tool 为 `blocked_qualification`。这些是
non-live runtime evidence，不证明真实 target cutover。详细映射见
`implementation-gap-audit-20260822.md` 和 tasks 19.*。

拆分前被删除测试的语义处置见 `behavior-test-disposition-ledger.md`：它不追求同名文件一对一替换，而是把保留
不变量、迁移 capability、明确退休 surface 与 live-gated 行为分别绑定到当前 owner-local tests/absence gates。

因此旧 27/27 结果仍只保留为历史组件级 diagnostic evidence；当前 closed registry 已变为 28 个 scenario/
invariant。20.1—20.6 已修复无 handle uncertain dispatch、SSH/Slurm reconcile certainty、runtime gateway
effect truth、Driver terminal result validation 与 Adapter runtime identity 双通道；20.7 的声明收窄已进入文档，
但仍须与 18.10、19.12 一起由最终 clean-source closure 证明。仓内索引只记录历史 candidate 证据和封口规则；
最终 clean SHA、最终 report path 与 digest 必须由封口后的外部运行产生并记录在交付说明中，不写回仓库造成自引用。

## 2026-08-22 历史 clean candidate 与封口验证

以下结果先证明 20.x correctness 修复之前的审计实现与非 live 行为闭合；随后 clean candidate
`ba10837dc233a09617d0b1b3da18a481f5ad709d` 在零 source mutation 的顺序中完成正式 admission：

- 受影响 owner-local 集合：`269 passed in 16.53s`；SSH/HPC/EnzymeDesign digest 修复后再次运行的 focused
  集合为 `61 passed in 4.02s`；
- 静态架构检查：37 components、115 import edges、150 tables、134 indexes、679 triggers、422 foreign keys，
  catalog digest 为 `sha256:5315d578ebcd49d6a440f38fb14b41c0779605b539173b00008fdcf67254e978`；
- fresh-wheel qualification：37 个 component wheels 全部构建，Contracts+SPI、Kernel、Plugin-free Standard、
  runner、EnzymeDesign 五个 fresh Python 3.13 profile 全部通过，`network_used=false`、
  `external_effects_real=false`；
- 完整三 profile diagnostic qualification：报告位于 checkout 外
  `/tmp/openzyme-v3-qualification.6PK9YP/diagnostic-report/architecture-qualification-report.json`，payload digest
  为 `sha256:5a2d431bda66536e71c43ba26fe1e3796c49ab4261638b7e067c282f808afa9c`，28/28 scenario 与
  28/28 invariant 全部 `satisfied`，零 not-run，`run_failure=null`，独立 verifier `valid=true`；拒绝
  admission 的原因严格为 `mode_not_admission` 与 `source_not_clean`；
- authoritative mainline：evidence root `/tmp/openzyme-mainline-authoritative.7YlyDJ/evidence`，receipt digest
  `sha256:79354555b69939b9e679b48324b750f79cb98ed5bf63bc600b1774d23c405710`，脚本与自身 pure verifier
  均为 `terminal_status=pass`；
- `uv run python -m openzyme_host_api.evals` 已通过；strict OpenSpec authoritative JSON 为 `valid=true`。

clean candidate 的正式 admission 报告位于 checkout 外
`/tmp/openzyme-v3-admission.3QVZNO/admission-report/architecture-qualification-report.json`，payload digest 为
`sha256:266a718d119ff4e535ee54fbccf559dcca6a3e0fcbb6b29c1553827b1eb9e85d`；独立 verifier 记录
`admission_eligible=true`、`valid=true`、`rejection_reasons=[]` 和上述 exact source commit。随后同一 clean source
上的 authoritative mainline evidence root 为 `/tmp/openzyme-mainline-authoritative.45IuBm/evidence`，plan digest
`sha256:818e3f74c247e13d084619f405178a5aa5f452424883510cf04f1cf417508baf`，receipt digest
`sha256:9594080c9f336fdf3935c7d7241104cf932686aa09da4682ea3700855b33cd83`，`terminal_status=pass`、
pure verifier `valid=true`；eval 仍为 `status=passed`、`external_effect_performed=false`、
`fallback_performed=false`，strict OpenSpec authoritative JSON 仍为 `valid=true`。

以上路径是本地临时历史证据位置，不承诺跨机器持久化，也不证明后续 20.x source。tasks/evidence 文本封口会改变
source identity，因此包含本文件的最终 clean SHA 仍须按 19.12 顺序整组重跑 focused tests、fresh wheels、
qualification、mainline、evals、strict validation 与独立 verifier；该最终外部结果必须在交付说明中记录，且运行后
不得再修改 source、配置、文档、OpenSpec 或 manifest。

## Frozen implementation surface

最终 source-bound architecture inventory 必须同时满足：

- 37 个 active components；
- 115 条 active import edges；
- component inventory digest
  `sha256:45ef292313b323fb2bb7fd82266e63cad60e90e1c3c6cb616e1bd1ca96436a65`；
- import graph digest
  `sha256:be4252b8c30e0c6f9c9a098eb3c2e881c0a26681b6fad92a04b2ffdef593c5a5`；
- catalog digest
  `sha256:5315d578ebcd49d6a440f38fb14b41c0779605b539173b00008fdcf67254e978`；
- 150 tables、134 indexes、679 triggers、422 foreign keys；
- table owner digest
  `sha256:7fb0d7f66afe1b0350d34d6ba494c2f2dd03b6efe70e6ca6ba71fccaf60c0638`；
- `temporary-reexport-ledger.json.entries == []`，旧 mixed packages 不在 workspace、wheel、entry
  point 或 active import graph；
- generic Kernel/Host/Standard source 中没有 AOX、HMMER、Vina、fpocket、AlphaFold、RDKit、
  Meeko、Biopython、Slurm 或 Tavily 垂直 dependency；
- 当前在线公共合同只有 `file_workspace_public@2`，`@1` 只有显式 offline historical reader，
  不存在 dual-write、online translation、per-Session legacy mode 或 automatic conversion。

## Required final command closure

以下命令必须全部基于同一 final source 成功，且执行顺序中不得插入 source mutation：

1. `python3 scripts/check-openzyme-architecture.py`；
2. `.venv/bin/python scripts/qualify-openzyme-contract-wheels.py`（offline wheelhouse）；
3. `./scripts/check-v3-architecture-qualification.sh admission <new external dir>`，随后以
   `.venv/bin/python scripts/verify-v3-architecture-qualification.py <report>` 独立验证；
4. `./scripts/check-mainline.sh`，随后由脚本自身执行 pure authoritative verifier；
5. `uv run python -m openzyme_host_api.evals`；
6. `openspec validate separate-openzyme-kernel-from-capability-extensions --type change --strict
   --json --no-interactive`。

三 profile qualification 必须是 report schema `openzyme_v3_architecture_qualification_report@4`，
28/28 scenario 为 `satisfied`，28/28 invariant 为 `satisfied`，零 skip/xfail、零 undeclared
external effect、零 not-run、`external_effects_real=false`、`live_campaign_started=false`、
`run_failure=null`，并且 clean source 的 admission 必须为 `admission_eligible=true`、零 rejection。dirty checkout
的 diagnostic report 必须且只能因 `mode_not_admission` 与 `source_not_clean` 不具备 admission authority；这不
允许被解释为真实 cutover proof。

wheel qualification 必须在 fresh Python ≥3.12 environments 验证以下闭包：

- Contracts + SPI only；
- Kernel only；
- Plugin-free Standard only；
- runner only；
- EnzymeDesign component set。

mainline 必须让 lint、compatibility audit、premerge architecture qualification、完整 non-live
pytest、Web UI tests 和 Web UI build 全部为 `pass`。OpenSpec strict validation 的 authoritative JSON
必须为 `valid=true`；PostHog telemetry 的网络失败不参与 acceptance。

## Requirement and documentation closure

`requirement-evidence.md` 为 18 个 delta specs 的全部 162 个 requirements 保留 source、test 和 document
owner bundle 索引；product composition、restart/reconcile、完整 layered qualification 与 final completion
均由 clean-source 外部 evidence chain 证明，不由结构映射或仓内 checkbox 单独推断。最终审计还必须
确认：

- `docs/OpenZyme架构设计.md`、相关 `docs/v3/`、package/app README 与实际 owner/path/command 一致；
- OpenZyme Standard 是 Distribution，不是语义层；Adapter、Plugin、Driver 与 Distribution 不混用；
- HMMER/Vina 等领域 Plugin 通过 capability requirements 和 resolved route 使用 HPC，不 import
  Slurm/SSH internals；
- Workspace Runtime 由 Kernel 定义 contract/authority/receipt，Local/Podman/SSH 实现位于 Adapter，
  HPC workspace lifecycle 位于 HPC Plugin，scheduler 永久与 login/file authority 分离；
- Agent 保留策略自由；Shell/CRUD 或 job success 不自动形成 publication、Science adoption 或
  `task.finish`。

## Archive condition

tasks 19.2—19.11 与 20.1—20.6 已完成；tasks `18.10`、`19.12`、`20.7` 的最终成立仍以包含本索引与
correctness 修复的 clean source 在 checkout 外生成并经独立 verifier 验证的整组 evidence 为条件。本 change 不因为
OpenSpec artifacts 为 `done`、单一绿色 gate 或旧 receipt 而提前宣称完成。task `18.9` 的第二次正式 reset 已完整
执行并验证；它不证明后续 product runtime implementation closure，也不会因后续代码修复而被倒推改写。
