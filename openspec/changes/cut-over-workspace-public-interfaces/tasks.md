## 0. Public release gate

- [x] 0.1 重读并绑定 C10/C11 精确 completion receipts、统一 release bundle、静默期与 local deployment activation evidence，拒绝用 candidate source 或部分验收替代。
- [x] 0.2 将保留审计文件名的 gate 升级为 `file_workspace_public_release_gate@2`，记录 `file_workspace_public@1` 已在解析出的本地 deployment 激活并仅向 C13 离线迁移开放准入。
- [x] 0.3 明确该 gate 不授予不同 deployment activation、artifact-era session 重开、remote/provider/HPC/live、continuation/approval replay，也不把 public activation 视为历史迁移或物理删除完成。

## 1. 精确前序 receipt 与 cutover 准入

- [x] 1.1 新增准入验证器，要求 `migrate-scientific-deliverables-to-files` 与 `replace-sandbox-artifact-boundaries-with-files` 的精确完成 receipt 和已激活 contract identity；拒绝缺失、不匹配、已 superseded 或仅部分验收的 receipt。
- [x] 1.2 重新验证前序绑定的 file/revision/publication、Git LFS、capability lease、executor workspace、revision-bound job、research/report/task handoff 与 scientific-deliverable contract identity，不得以 feature flag 或 table count 替代。
- [x] 1.3 证明所有 current artifact、sandbox-artifact 和 scientific-artifact public writer 均已禁用，并且 activation 前，尚未启用的 `file_workspace_public@1` 实现只能通过隔离的 contract fixture 运行。
- [x] 1.4 根据各自的 workspace/tool catalog digest 清点 active/nonterminal session、saved continuation、pending approval、external execution、runtime drain 与 UI client，确保每个 artifact-era consumer 都有显式 closed-historical 或 unsupported disposition。

## 2. 文件优先的 Host schema、projection 与 media contract

- [x] 2.1 定义带版本的 `file_workspace_public@1` response/event/restore schema，为 authorized workspace status、private revision fact、immutable publication、report、scientific deliverable、external job/result、capability lease 与 owner-scoped executor workspace view 提供有界 typed section。
- [x] 2.2 重构 canonical workspace projection builder，使每个 section 均来自其 typed owner repository，并删除 `artifacts`、`artifact_index`、storage/catalog/materialization field、artifact-derived status 与 legacy section alias。
- [x] 2.3 重构 `/v3` Host response model、endpoint、content negotiation、pagination、authorization 与 error envelope，使其只输出新 contract，并在不存在 dual serialization 的情况下拒绝旧 media/schema/catalog version。
- [x] 2.4 用 typed workspace-generation、revision、publication、report、scientific-deliverable、external-job/result 与 lease event 替换 current artifact lifecycle event；legacy event decoding 仅允许离线历史迁移路径使用。
- [x] 2.5 更新 continuation snapshot 与 restore schema，绑定新的 workspace contract version 和 tool-catalog digest，并重建相同 typed ref，不得合成 artifact alias。

## 3. 按 owner 限定的 executor locator 与隐私边界

- [x] 3.1 实现独立授权的 executor-workspace view，仅返回 owning executor 自身的 workspace id/generation、login alias 与 native SSH/rsync/scp CRUD 所需的 workspace path。
- [x] 3.2 对该 view 强制执行 subject、membership、capability lease、workspace generation 与 owner 检查，确保 executor 无法检查其他 agent 的 alias/path，且非 owner 不会收到带 locator 的 projection。
- [x] 3.3 从所有 general/shared/workspace/job/result projection 与 event 中删除 login alias、workspace path、Host path、Git credential、private ref/token、SSH target、Slurm id、remote directory、raw job handle、transport state 与 raw backend log。
- [x] 3.4 为获准的 owner view 增加有界 redaction、path allowlist、secret scanning、count/size budget 与 Host-private diagnostic，同时不得将其退化为通用 locator catalog。
- [x] 3.5 当 producer 后续使 private workspace 变为 dirty 时，仍保留已经验证的 immutable publication/path handoff；cleanliness check 只适用于创建新 publication 或直接从 private source launch，不得针对后续 workspace state 隐式重新验证既有 handoff。

## 4. Tool catalog 与 SDK 的 breaking cutover

- [x] 4.1 用 native workspace filesystem、Git revision/publication、capability lease 与 external-job/result operation 替换 current tool declaration 和 reflection metadata；删除全部 `artifact.*`、`artifacts.*`、`scientific.artifact.*`、`hpc.stage_artifact` 与 `sandbox.file.*` public name。
- [x] 4.2 从 current tool schema 和 SDK model 中删除 artifact-id、catalog-ref、materialization、registration、staging-ref、storage-URI 与 artifact-kind parameter/result，改为暴露 typed revision/path/publication/job/result ref。
- [x] 4.3 将 `openzyme_pipeline` 和其他 current client SDK entry point 更新为 native file/Git/HPC contract，不得保留 deprecated alias、auto-staging、artifact materialization 或 silent request translation。
- [x] 4.4 对 saved 或 new legacy call 返回带版本、不可重试的 removed-tool 或 stale-catalog error；保留请求的 name 与安全 corrective contract fact，但不得调用替代 operation。
- [x] 4.5 将 tool-catalog digest、public schema bundle、prompt 与 continuation compatibility identity 作为一个 release-train bundle 重新生成并 pin；拒绝任何混合 Host/CLI/SDK/UI catalog 组合。

## 5. CLI、world inspection、prompt、restore 与安全错误

- [x] 5.1 重构 CLI workspace inspection 与 `world.inspect` rendering，展示有界 file tree/status、revision/publication、report/scientific ref、job/result 与 lease，不得出现 artifact term、locator、raw handle 或 compatibility section。
- [x] 5.2 更新 model-visible instruction 与 tool-result summary，描述 native file/Git/HPC operation 和显式 publication boundary；保留 agent 策略自由，且不提供 legacy fallback 建议。
- [x] 5.3 使 restore/preflight 将旧 workspace 或 catalog context 作为 stale context 终止，而不是 replay、rename 或重新解释 saved artifact call；保留被拒绝的 exact contract identity 供审计。
- [x] 5.4 为 missing publication/ref、dirty private-source publication 或 execution、incomplete LFS closure、expired/fenced lease 与 unknown external-job effect 实现有界错误；不得 auto-commit、stash、publish、merge、stage、retry、reopen approval、选择 backend 或 finish task。

## 6. Web UI 文件/revision workspace

- [x] 6.1 用带版本的 workspace、Git status/revision、publication、report、scientific-deliverable、job/result、lease 与 authorized executor-workspace state 替换 web state reducer 的 artifact catalog/index state。
- [x] 6.2 用有界 file tree、changed-path/status view、immutable publication/path handoff、report/scientific section、job/result view 与 lease/fence status 替换 artifact list/detail/download/materialization view。
- [x] 6.3 将 executor alias/path UI 限于 owning executor 的 authorized view，并确保 shared/general/job panel 永不渲染 locator、credential、raw job handle、Slurm id、remote directory 或 backend log。
- [x] 6.4 更新 web client，要求 `file_workspace_public@1` 及匹配的 catalog/schema digest；不匹配时阻断，并删除 legacy endpoint/field parsing 与 browser-state fallback。
- [x] 6.5 将 stale contract、removed tool、dirty private source、missing publication/LFS closure、lease/fence 与 unknown-effect failure 渲染为显式 blocking state，不得提供自动 repair action。

## 7. 原子激活与 artifact-era session 拒绝

- [x] 7.1 在变更 public epoch 前，使已清点 session 的 message、runtime drain、approval、continuation、workspace mutation、publication 与 external-job mutation 达到 quiescence，并记录精确 disposition 与 effect-certainty receipt。
- [x] 7.2 在一个 release 中原子激活 `file_workspace_public@1`、其 catalog digest、Host/CLI/SDK/UI build identity 与 restore/event version；任一 component identity 不同都应使 activation transaction 失败。
- [x] 7.3 将每个 artifact-era session 设为 closed historical input 或明确标记为 current runtime 不支持；拒绝其 message、drain、approval、tool、mutation、publication 与 job，且不得自动转换。
- [x] 7.4 激活后验证 public response、event、prompt、reflection、restore、UI bundle 与 generated schema 不含 artifact catalog、artifact tool、staging ref、Host path、unauthorized executor locator 或 job-private handle。
- [x] 7.5 使 activation 后的 repair 仅能沿新 contract 前向进行，并确保剩余 legacy reader 只能从后续 offline historical migration entry point 访问。

## 8. 聚焦验收、架构文档与完成 receipt

- [x] 8.1 在 `apps/openzyme-host-api/tests/test_api.py`、`packages/openzyme-core/tests/test_projections.py`、`test_protocols.py` 及相关 tool-catalog/restore 测试中新增并运行聚焦 Host/core contract 测试，覆盖 exact schema、authorization、仅 owner 可见的 executor locator、隐藏的 general/job locator、removed tool、stale session 与 no dual projection。
- [x] 8.2 新增并运行聚焦回归测试，证明已经验证的 immutable publication/path handoff 在 producer workspace 后续变为 dirty 后仍可使用，同时拒绝新的 private-source publication/execution 且不进行 auto-repair。
- [x] 8.3 更新并运行 `apps/openzyme-web-ui/tests/state.test.js`、`view.test.js`、`client.test.js` 和 `controller.test.js`，随后运行 UI build，覆盖 schema mismatch blocking、file/revision rendering、owner-scoped locator visibility、redaction 与不存在 artifact fallback。
- [x] 8.4 更新 `docs/OpenZyme架构设计.md` 及相关 `docs/v3/` architecture、control-plane、public-interface、agent-runtime、top-level-loop、failure-recovery、compatibility-sunset 与 execution-pipeline 文档，说明 `file_workspace_public@1`、owner exception、breaking cutover、immutable handoff rule 及禁止 alias/fallback。
- [x] 8.5 对本 change 及其 dependency change 运行 strict OpenSpec validation，再运行 `./scripts/check-mainline.sh`；记录 command、exact revision、UI build result、排除的 live gate 与任何 environment-owned blocker，不得降低验收标准。
- [x] 8.6 仅当前序 identity、quiescence/session disposition、已激活 epoch/catalog/build identity、focused/mainline result、documentation digest、redaction audit 与 zero-legacy-public-surface proof 全部匹配时，签发 immutable change completion receipt。
