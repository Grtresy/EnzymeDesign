# V3 可执行架构资格完成审计

状态：implementation 与 verification 完成；OpenSpec 尚未同步/归档；AOX/r48 未启动。

## 结论

本 change 的 14 项 requirement 与 86 项实现任务均已有直接代码、确定性测试或机器报告
证据。首份有效 clean admission 报告绑定提交
`1c59a045c834c061f2f445fd3ba05ce0d52edfad`，其 payload digest 为
`sha256:bb305036635457d1fa5b598dca2fe285e4c1d78796ac49e8000186f1a6516bad`。
当前 checkout 的 pure verifier 独立重算出相同 digest、source commit 与空 rejection list。

这只解除 AOX 的架构资格阻断，结论是“允许 operator 另行恢复 AOX live campaign”。它不是
新的 attempt admission，不替代外部可用性、scientific exact-nine、launch、证据或 operator
门禁，也没有创建 r48、attempt root 或任何真实外部 effect。

本审计与 task 状态提交后会改变 source commit，因此上述报告保留为首份 clean admission
证据；必须再从包含本审计的最终 clean HEAD 生成并纯验证一份 definitive admission report，
且不再修改 checkout，才能对外报告最终 digest。

## 机器证据

| 检查 | 结果 |
| --- | --- |
| source identity | clean full commit `1c59a045c834c061f2f445fd3ba05ce0d52edfad`，无 tracked/untracked source drift |
| selection | `full`，12 个稳定 scenario id |
| harness | `pass`，exit code 0 |
| scenario/invariant | 12/12 scenarios satisfied；12/12 invariants satisfied |
| GAP/P0 | 0 GAP；0 open P0；2 条具名 closed P0 记录 |
| safety | `external_effects_real=false`；`aox_live_started=false` |
| pure verifier | admissible；相同 payload digest/source commit；无 rejection |
| AOX receipt | `sha256:7e1b8bcfac263c76403cda207a87a7cae8a2b13758bbb0aff52ec25ece784809` |

两条 closed P0 均绑定实现提交
`d653030a573600aa458318e4122c28fa872ee3ed`：

- `p0.boundary-scale.public-diagnostic-bounded-work` →
  `bound-public-diagnostic-sanitizer-work`；
- `p0.supervisor-progress.semantic-progress` →
  `fix-v3-durable-supervisor-semantic-progress`。

第一次 clean admission 还暴露并阻断了一项 qualification harness 缺陷：dirty diagnostic
自测曾依赖工作树碰巧为 dirty。该测试现显式构造、绑定并重算 synthetic dirty source
identity，由提交 `1c59a045c834c061f2f445fd3ba05ce0d52edfad` 修复；随后 clean admission
通过。失败报告没有被降级或人工豁免。

最终 clean mainline 随后暴露了第二项 qualification runner 集成缺陷：non-admission
`premerge_subset` 的进程退出判定错误地要求 P0 历史记录列表为空，而不是只要求零 open
P0，导致两条合法 closed P0 记录触发假阴性。runner 现在显式要求所有现存 P0 记录均为
`closed`，并有 closed-green/open-red 的定向回归；报告 verifier 与 admission 语义未放宽。

## Requirement-by-requirement 审计

| Requirement | 完成证据 |
| --- | --- |
| Closed executable registry | canonical registry/schema、loader、collection closure 与 validator tests |
| Real production composition | file SQLite、`HostApiDependencies + create_app()`、真实 worker/gateway/projection composition tests |
| Complete cross-layer matrix | 十个 family、12 个稳定场景；r43-r47 与 restart/fencing/operator/boundary 全覆盖 |
| Allowed/forbidden oracles | canonical state/event/effect/artifact observations 与禁止 task/workflow 推断断言 |
| Process-isolated bounded faults | identity-bound process group、TERM/KILL/deadline/descendant closure 自测 |
| Diagnostic/admission authority split | dirty diagnostic 与 subset 永不 admissible；clean/full admission 才可通过 |
| Immutable pure-verifiable reports | checkout 外 no-replace canonical report、source/manifest/digest 重算与 tamper tests |
| GAP taxonomy | closed taxonomy、owner/reproducer/profile/change refs 与 baseline GAP 报告 |
| Evidence-driven P0 closure | frozen red evidence、两个 focused changes、owner regressions 与 canonical closure sidecar |
| Agent strategy freedom | qualification 只验证真实约束，不写 task/workflow 产品事实，不启动 agent/live |
| Exact AOX admission ordering | `pin/preflight/run-live` 在 settings/root/provider/runner/Chrome/MICU 前纯验证 report |
| Receipt outside exact-nine | schema-v2 launch/evidence 闭合 qualification receipt；scientific exact-nine 未变 |
| Fast feedback cannot claim qualification | mainline `premerge_subset` 绿色但固定 non-admissible |
| Explicit profile scope | 仅声明 `local_single_process_file_sqlite@1`，拒绝 distributed/shared-Host 推论 |

## 验证清单

- architecture qualification 全测试树与 12 个注册场景通过，无 skip/xfail/timeout；
- public diagnostic owner tests 111/111 通过；durable supervisor/runtime owner 选择集 19/19
  通过；
- AOX architecture adapter 4/4、CLI pre-effect gate 4/4、注册 AOX admission 场景 1/1
  通过；
- `ruff check apps packages scripts/v3_architecture_qualification.py` 通过；
- `uv run python -m openzyme_host_api.evals` 2/2 通过，AOX fixture 明确为 non-cutover；
- `./scripts/check-mainline.sh` 通过：2300 个 Python tests、40 个前端 tests 与前端 build；
- parent change 与两个 focused P0 changes 的 OpenSpec strict validation 退出码均为 0。

OpenSpec 的离线 PostHog `EAI_AGAIN` 只发生在成功退出后的 telemetry flush，不改变 strict
validation 结果。
