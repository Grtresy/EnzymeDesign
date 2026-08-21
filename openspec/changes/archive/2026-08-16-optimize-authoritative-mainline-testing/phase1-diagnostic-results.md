# Phase 1B explicit diagnostic profiles 结果

## 结论

`focused_diagnostic` 与 `affected_scope_diagnostic` 已形成可执行、可纯验证、永久非权威的
operator-plane feedback 层。最终同机实测中，focused compatibility slice 为 `5.008s`；
四类 affected 代表变更分别为 `14.236s`、`13.315s`、`5.509s` 和 `0.576s`，全部低于
`10–60s` 目标上限，且没有为了达标缩减对应 dependency closure。

所有 plan、receipt 和 CLI summary 均固定报告：

- `authoritative=false`
- `admission_eligible=false`
- `live_eligible=false`

即使 unknown 影响扩大到完整 Python + Web UI 集合，也不会升级为 mainline、
architecture admission、AOX、live campaign 或 scientific evidence。当前权威入口
`scripts/check-mainline.sh` 在本阶段仍保持逐字节不变。

## Selection 与 authority 闭合

focused profile 要求至少一个显式 lint path、pytest path、exact node id 或已登记
contract group。路径必须是当前 checkout 内存在的 canonical repository-relative
非 symlink 路径；node id 必须包含存在的 Python test path；unknown group、空选择、
绝对路径、父目录 traversal、缺失路径、零节点和 live/integration selector 都显式失败。

affected profile 的 change inventory 合并：

1. 显式 local base ref 到 `HEAD` 的 committed diff；
2. staged paths；
3. unstaged paths；
4. relevant untracked sources。

`scripts/test-affected-scope-map.json` 当前为
`openzyme_test_affected_scope_map@1`，包含 `22` 条规则、覆盖 `13` 个 app/package owner，
raw/map digest 为：

`sha256:83a8e718eb5ca9951b194fee520e31b437946d9cd196f4938cdfefe0a57050f5`

map 对 owner tests、domain/runtime/protocol/API cross-layer consumer、Python workspace member
metadata、migration、test tooling、root lock/config 和 Web UI consumer 建立显式 closure。
planner/map 自身、无法分类路径、规则冲突、authority/qualification contract、workspace
dependency metadata 和 migration contract 都扩大到完整安全诊断集合，不返回空 green。

Web UI tests/build 对 UI source/metadata、Host API、domain public shape，以及 workspace、
approval、event、runtime command、report、artifact、evidence projection 的精确规则启用。
未启用前端时，plan/receipt 必须同时包含当前 matched rule 和
`frontend_omission=diagnostic_only`。纯验证器拒绝：

- 缺失或乱序的 `web_ui_test` / `web_ui_build`；
- frontend top-level outcome 与 stage outcome 不一致；
- diagnostic omission 被改写为 authoritative profile；
- stage argv、cwd、environment 与 plan 不一致；
- 缺失 stage output、digest/source drift 或 unexpected deselection。

## Closed non-live 与 effect boundary

diagnostic environment 删除 provider API key/token/credential、SSH、Chrome/CDP、MICU、
HPC/Slurm、proxy、live opt-in 和 ambient `PYTEST_ADDOPTS`，并设置
`OPENZYME_LOAD_ENV_FILES=0`。collection 与 execution 都安装 remote-socket guard；
collection 还禁止 child process。

focused collection 不预先用 marker expression 隐藏 selector 内容：只要观察到 forbidden
marker 或任一 collection deselection，就在执行前失败。affected collection 使用固定
non-live marker expression；observation 对每个策略性 deselection 额外记录原始 marker，
只有至少带一个声明的 forbidden marker 才可进入
`policy_deselected_nodes`，任何 non-live deselection 仍显式失败。execution 始终使用
plan 中的 exact safe node ids，并要求零 deselection。

完整主工作树上的 fail-safe collection proof：

- raw observation：
  `/tmp/openzyme-debug-full-collection-main-20260729-r1.json`
- file SHA-256：
  `20fceff28ba2656788067e8cf8bb1163b02a934a5aa1295b9b8900634065ad38`
- canonical self digest：
  `sha256:70dbf96ba968035ad39cb24c1868f3c979eaeee895b8e889ed75885f3300f9c7`
- selected non-live nodes：`2750`
- policy-deselected nodes：`39`
- deselection markers：
  `integration`、`live_e2e`、`live_hpc`、`live_llm`、`live_tavily`、
  `quality_eval`、`seeded_live_smoke`
- `session_exit_code=0`
- pytest collection duration：`1.374s`

真实 subprocess 与 remote socket import-time fault fixtures 均在 collection 阶段被 guard
拒绝，目标 test body 未开始执行。

## Final benchmark

affected benchmark 在
`/tmp/openzyme-affected-benchmark-workspace-20260729-r1` 的隔离 Git 仓库中顺序制造单一
changed path。该仓库同步最终 planner/map，并将每个 probe 前一状态提交为下一次基线；
因此每份 receipt 都只绑定表中一个 changed path。四份 affected plan 的 planner digest
均为：

`sha256:41c5ae4d4a0cdbf9847318ca9fba2c36d7ee7d52f448d60f635d946221beae30`

| Probe | Exact expansion | Nodes | Frontend | Total |
| --- | --- | ---: | --- | ---: |
| Core `agent_scheduler.py` | Ruff `packages/openzyme-core`; `test_agent_scheduler.py` | `24` | diagnostic omission | `14.236s` |
| Host API `security.py` | Ruff `apps/openzyme-host-api`; `test_security.py` | `8` | test + build pass | `13.315s` |
| architecture audit script | Ruff audit script; `test_compat_caller_audit.py` | `16` | diagnostic omission | `5.509s` |
| Web UI `view.js` | Web UI test + build | `0` Python | test + build pass | `0.576s` |

### Core

- output：
  `/tmp/openzyme-affected-owner-final-20260729-r3`
- source identity：
  `sha256:2b05f97f4450fc094a209caa309ac7db558d3cfa828a5b17eee171ad43593855`
- plan：
  `sha256:2dca2301895e8195d1d4ccca9f9608f205e24dcf8f92c76f0f60f1839e07bae9`
- receipt：
  `sha256:a1cae0ce646b592e7acd33e665ed45b92e5564cb92d73d42275654d1e8db4822`
- stages：collection `1.267s`、Ruff `0.065s`、pytest `12.542s`

### Host API

- output：
  `/tmp/openzyme-affected-host-api-final-20260729-r3`
- source identity：
  `sha256:23051059b1a7554ae45a5f7591b925ef5eb18896abc79dcd2b14a2583541e07a`
- plan：
  `sha256:4e47f20676d253d582f341d419921ddd47c2148b1e5273835214002596a7206f`
- receipt：
  `sha256:be4bb05ae240da7b239f3c07376a865f8026c0114bb7e63a00c5d6b0fd061b79`
- stages：collection `2.118s`、Ruff `0.032s`、pytest `10.337s`、
  Web UI test `0.214s`、build `0.114s`

### Architecture script

- output：
  `/tmp/openzyme-affected-architecture-script-current-20260729-r5`
- source identity：
  `sha256:03a2bffc26de500d5fbe7a2a0abea69e1344998280ae7dd741231a33c94ce138`
- plan：
  `sha256:6e28464957bc35ec14a732e0629ef734f523ca3c9e012756aa0e085022d8d588`
- receipt：
  `sha256:790d1493c7c6577a12fd00a100976003c542ce788f8e6bbb7576ba5c4eb97036`
- stages：collection `0.966s`、Ruff `0.032s`、pytest `4.172s`

### Web UI

- output：
  `/tmp/openzyme-affected-web-ui-final-20260729-r3`
- source identity：
  `sha256:3824801f4dd3e07474bf2cc592f4a1ac49c9f0127ede4d48e7139130afd3db52`
- plan：
  `sha256:4fa2fede4c93aae69ddbf273feeefcd4c4c32753a851db3f66a0542408873017`
- receipt：
  `sha256:1882ca34fb887e33ec9754832abf1a5071a23d1871cb745759f282026581a901`
- stages：Web UI test `0.214s`、build `0.114s`

最终 focused compatibility probe：

- output：
  `/tmp/openzyme-focused-diagnostic-compat-final-20260729-r2`
- planner：
  `sha256:28bf97bd354db8047b46c86ef3c6e63d90ce70f9f2f19a24a40e049191edb845`
- source identity：
  `sha256:9ca90a9c47594d6a9e9f349b941ac59de4424229b12e5e9c5082a391983bfb7b`
- plan：
  `sha256:0c40b2d6c193ed996b8dd08aee3c9f80d82e9a90a1489d85deda1938f30781f3`
- receipt：
  `sha256:6099ebb0ad738e15cb89fcbd3ece905e37438cec037264534dbe4d1c9b15a972`
- exact selection：audit Ruff + `16` compatibility tests
- stages：collection `0.515s`、Ruff `0.032s`、pytest `4.022s`
- total：`5.008s`
- CLI current-source pure verification：pass

最终 test-gate contract-group recheck：

- output：
  `/tmp/openzyme-focused-test-gate-final-r2`
- plan：
  `sha256:0966b7b6a1faa792de4bc290940fa0da87f153c356ff4ab5e5472d241610488d`
- receipt：
  `sha256:311ed48db3b5f067b7ee67aa9c9249d8cae00fcad0cc1135011d5d216e82f812`
- exact selection：`13` 个 `test_test_gate_*.py` 模块、`139` nodes 与
  `scripts/run-test-gate.py + scripts/test_gate/` Ruff
- stages：collection `0.615s`、Ruff `0.065s`、pytest `8.180s`
- total：`9.435s`，低于 10–60 秒反馈目标的下界而未缩小 contract group
- pure verification：pass；`authoritative=false`、
  `admission_eligible=false`、`live_eligible=false`

该 recheck 同时发现并修复了早期 `test_gate` contract group 未纳入后增
`authoritative/resource/replay` 三个测试模块的诊断选择漂移；新增回归要求该 group 与
当前全部 `test_test_gate_*.py` 文件 exact equality。被替代的
`/tmp/openzyme-focused-test-gate-final-r1` 不计为最终证据。

## Rejected probes

两份不合格探针没有计入上表：

1. `/tmp/openzyme-affected-architecture-script-20260729-r1` 因最初裁剪 benchmark
   fixture 缺失 `legacy/v1`，真实得到 `1 failed, 15 passed`；receipt 保留 fail，
   没有被包装成 green。
2. `/tmp/openzyme-affected-architecture-script-20260729-r3` 因临时仓库错误追踪
   `__pycache__`，被 fail-safe 扩大为全仓；该裁剪仓库又不含
   `docs/v3/workflow-packs`，collection exit `2`，因此在 plan 发布前失败。修正临时
   fixture 后，完整 fallback collection 另在真实完整主工作树证明。

## Regression 与验证

最终验证：

- `uv run ruff check ...`：通过
- `uv run pytest packages/openzyme-kernel/tests/test_test_gate_*.py -q`：
  `86 passed`
- `uv run pytest packages/openzyme-core/tests/test_compat_caller_audit.py -q`：
  `16 passed`
- `.venv/bin/python scripts/audit-v3-compat-callers.py --summary`：
  `21` seams、`0` violations、`0` scan errors
- `uv run python scripts/run-test-gate.py inspect-config`：通过；worker hard max `4`，
  `architecture_admission` / `live_campaign` 均在 dispatcher 外
- `openspec validate optimize-authoritative-mainline-testing --strict`：通过
- `git diff --check`：通过
- `git diff --exit-code -- scripts/check-mainline.sh`：通过

回归覆盖空/越界/缺失/unknown selector、live marker、环境净化、真实 collection effect、
invalid base、四源 inventory、unknown/conflicting map、owner/map/schema/planner drift、
frontend inclusion/omission、full-repository-but-still-diagnostic、source drift、unexpected
deselection、stage/output/authority tampering 和 no-replace evidence。
