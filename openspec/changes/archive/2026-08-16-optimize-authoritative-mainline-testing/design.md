## Context

当前 `scripts/check-mainline.sh` 以 `set -euo pipefail` 顺序执行：

1. `ruff check apps packages`；
2. compatibility audit 自身 Ruff 与 `--summary` 扫描；
3. architecture qualification `premerge_subset`；
4. 仓库完整 non-live/non-integration pytest selection；
5. Web UI tests；
6. Web UI production build。

architecture qualification 不是普通 pytest 别名。它先关闭 scenario collection 和
registry/test-manifest，再以独立 pytest process 运行 harness self-tests 和每个 selected
scenario，最后发布并纯验证 canonical report。当前完整 pytest 随后再次收集并执行其中的
harness tests 与 selected scenarios；后一次执行没有 qualification 的环境、进程隔离和
report 语义，因此只是同一 mainline invocation 内的结构性重复，不能替代前一次。

`scripts/audit-v3-compat-callers.py` 已把 Python AST 缓存在 `PythonIndex`，但不同 seam scanner
仍会反复遍历目录、读取 Markdown/RST/非 Python source 和寻找相同行号。它的 authority 是
compatibility sunset evidence，优化只能改变 inventory/index 构造，不能改变分类、排序、
scan error 或 violation 结果。

本变更横跨 repository scripts、pytest collection、qualification runner、Web UI command
selection、性能证据和稳定文档，但不进入 V3 产品 control plane。主要使用者是本地开发者、
Codex/其他 agent、CI reviewer 和生成 AOX admission 前的 operator。`mainline_authoritative`
只证明 non-live merge gate；full clean `architecture_admission` 仍由现有独立命令和
canonical report/AOX verifier 拥有。

先前约十四分钟的运行和 proposal 中更早的测试数量只用于定位方向。任何切换或性能声明都
必须重新绑定同一 host、source revision、tracked/untracked identity、toolchain 和完整
collection，不能把旧输出当作当前基线。

## Goals / Non-Goals

**Goals:**

- 建立可重放验证的 stage/node timing、cold/warm baseline、execution plan、stage result 和
  final receipt。
- 让 `focused_diagnostic` / `affected_scope_diagnostic` 在常见改动上提供 `10–60` 秒反馈，
  同时从 schema、exit summary 和文档三处明确其非权威身份。
- 在一次 authoritative invocation 内让每个必需 pytest node 只有一个 owner；更严格的
  qualification execution 拥有其 harness/scenario nodes，普通 pytest 运行精确 residual。
- 只对已有资源隔离证明的节点使用固定上限并行，保持未知、SQLite、全局环境、signal、
  qualification 和 external classes 串行或排除。
- 保持现有 Ruff、compatibility、Python、Web UI、failure/skip/xfail/timeout、live exclusion
  与 architecture qualification 义务，并提供 forced-serial 和 legacy rollback。
- 在首个 authority cutover 前，用同机五组 cold/warm 样本证明 median 至少降低 `25%`；
  随后继续以 `5–7` 分钟 authoritative wall time 为现实目标。

**Non-Goals:**

- 不减少当前必需测试节点或 Web UI test/build，不引入宽泛 marker/path deselect。
- 不使用全局 `pytest -n auto`、blanket retry、跨 commit receipt/cache 或历史 pass 复用。
- 不改变 architecture qualification report/registry/test-manifest、full clean admission、
  AOX receipt、live campaign 或 scientific evidence schema/authority。
- 不把 test plan/receipt 写入 session、task、lane、artifact、report、attempt 或 event
  product truth。
- 不用降低 timeout、跳过真实同步点或共享可变数据库来制造速度。
- 不在没有 profiler/timing 证据时顺手重构产品 runtime。

## Decisions

### 1. 测试编排属于独立 repository/operator plane

新增 `scripts/test_gate/` Python package、`scripts/run-test-gate.py` CLI 和版本化配置，
shell 入口只负责固定参数、严格 shell 错误与 `exec`。核心模块使用标准库 dataclass、
`tomllib` 和 canonical JSON helper；不放入 `openzyme-domain`、`openzyme-core` 或 Host API
产品包，也不建立数据库。

计划的模块职责为：

- `model.py`：closed schema、canonical bytes/digest 和严格 loader；
- `source.py`：commit、tracked diff、untracked source、lock/toolchain identity；
- `pytest_plugin.py`：collection、实际 outcome 和 per-node duration sidecar；
- `planner.py`：profile obligations、node ownership、resource class 和 stage DAG；
- `runner.py`：bounded process-group execution、deadline、stage reduction；
- `diagnostic.py`：focused input 和 affected dependency closure；
- `verifier.py`：纯验证 plan/stage/receipt closure；
- `benchmark.py`：same-host paired baseline 与 median comparison。

选择 Python coordinator 而不是继续扩张 Bash，是因为 exact set algebra、strict JSON、
process cleanup、digest binding 和 deterministic reduction 在 shell 中难以 fail closed。
选择 repository scripts 而不是产品 package，是为了维持 qualification 文档声明的
operator-plane 边界。

### 2. profile 名称直接编码 authority

| Profile | Authority | Source | 必需义务 | 外部 effect |
| --- | --- | --- | --- | --- |
| `focused_diagnostic` | 无 merge/admission/live authority | dirty 可用 | caller 明确选择的 lint/tests/contracts | 禁止 |
| `affected_scope_diagnostic` | 无 merge/admission/live authority | dirty 可用 | versioned dependency closure；unknown 扩大 | 禁止 |
| `mainline_authoritative` | canonical non-live merge gate | clean/dirty 均可但绑定 exact source | 当前 Ruff、compat、qualification subset、Python、Web UI test/build | 禁止 |
| `architecture_admission` | full clean architecture admission | canonical clean HEAD | 现有 full qualification/report/pure verifier | 禁止 |
| `live_campaign` | 仅由各自 operator plan 决定 | 独立前置条件 | 现有 provider/HPC/Chrome/MICU/scientific gates | 显式 opt-in |

test-gate CLI 只实现前三个 profile。后两个只作为禁止混淆的边界出现在 plan/verifier 中，
不会被 dispatcher 自动调用。诊断 receipt 固定包含 `authoritative=false`、
`admission_eligible=false`、`live_eligible=false`，人类终端摘要使用同样措辞；即使选择了
与主线相同的所有节点也不能升级身份。

没有采用一个带大量 `--skip-*` 的通用命令，因为参数组合会产生难以命名和审计的绿色含义。

### 3. 先形成闭合 plan，再运行需要去重的测试

`openzyme_test_execution_plan@1` 至少绑定：

- invocation id、profile id、planner/config digest；
- commit、tracked diff digest、tracked dirty paths、untracked source manifest；
- Python、Node、uv、npm lock/toolchain identity；
- 每个 stage 的 argv、cwd、environment policy、deadline 和依赖；
- legacy general pytest collection、qualification harness collection、qualification
  selected scenario collection和 Web UI command identities；
- 每个必需 node 的唯一 owner、resource class 和 intentional-repeat 声明；
- expected distinct coverage digest、legacy execution multiset digest 和 output root；
- worker upper bound、forced-serial flag 和 source recheck policy。

Ruff 与 compatibility audit 保持当前先后顺序，并作为 planning preflight。它们 green 后，
planner 才执行 pytest collection；这样 syntax/compat failure 仍优先终止，不因提前 import
测试树改变用户看到的首个失败。任何 pytest execution 开始前，planner 必须关闭全部 node
ownership。

所有可消费文件写入 caller 指定、checkout 外、尚不存在的绝对 output directory，并使用
no-replace publication。每个 stage 前和 final reduction 前重算 source/config identity；
运行中 source 漂移会使 gate 失败，已经完成的 stage 仅保留诊断事实。

没有采用可变 SQLite plan store，也没有消费上一 invocation 的 receipt。跨运行 cache 即使
绑定 commit 仍会引入环境和依赖证明问题，留给未来独立变更。

### 4. baseline 同时记录 stage 和 node，不把计时本身变成通过条件

pytest plugin 在 collection finish 写 exact node ids，在 setup/call/teardown 后归并每个
node 的 outcome、skip/xfail/xpass 和 monotonic duration。runner 另外记录 process startup、
collection、qualification harness/scenarios、general residual、Web UI test/build 和 receipt
verification时间。stdout/stderr 只保存 bounded tail 与完整 digest，避免 receipt 膨胀或
泄漏环境。

baseline 采用五个 paired samples：

1. 每对样本绑定相同 source、host fingerprint 和 toolchain；
2. `cold` 表示 fresh process group、fresh no-replace output root、无 prior test receipt/
   daemon reuse；不要求 root 权限清空 OS page cache，receipt 明确记录
   `cache_control=process_only`；
3. `warm` 是 cold 后立即以相同 source 再运行一次；
4. 任一 source/collection/toolchain/host 漂移会废弃整对样本；
5. 分别比较 cold median 和 warm median，并报告 MAD、min/max、stage breakdown 与 planning
   overhead。

计时字段不参与功能 green；缺失或非法 timing 使性能验收不成立，但不会把实际失败测试包装
成性能样本。首个 optimized authority candidate 必须同时满足 exact coverage/outcome closure、
五对样本、cold/warm median 至少 `25%` 降时及 planning/receipt overhead 低于总时长 `5%`。

没有使用一次最快值或只比较 pytest 自报时间，因为二者会隐藏 process、qualification、
frontend 和冷启动成本。

### 5. compatibility audit 建立一次不可变 repository index

把 `PythonIndex` 扩展为 invocation-scoped `RepositoryIndex`：

- 单次 deterministic `os.walk` 生成所有受支持 suffix 的 path inventory；
- 每个文本文件最多读取和 decode 一次，缓存 immutable lines/content digest；
- Python 文件最多 parse 一次，保留 module resolution 与所有 parse/read errors；
- 已知 literal 集合先闭合，再对 docs/non-Python text 做一次 multi-literal pass；
- root/workspace TOML 只 parse 一次；
- 所有 scanner 只读 index，最后沿用现有 caller dedup、classification、排序和 report schema。

优化前后必须对真实仓库和 injected fixture 得到 canonical-byte-identical report；单元测试用
受控 reader 证明每个候选文件只读取一次，而不设置脆弱的毫秒阈值。真实 stage timing 再证明
wall-time 收益。

没有加入 mtime/content cache：它会把 source identity、symlink/rename 和跨 commit 失效问题
带入第一阶段，收益也小于消除同调用重复扫描。

### 6. diagnostic selection 使用 versioned fail-safe dependency map

`focused_diagnostic` 要求 caller 至少提供一个 repository-relative lint path、pytest path 或
exact node id。输入必须存在、位于 checkout 内且不能选择 live/integration marker；空选择、
越界路径或未知 selector 显式失败。输出列出 caller selection 和实际 expanded nodes。

`affected_scope_diagnostic` 从一个显式 base ref 加上 staged、unstaged、untracked source
inventory计算 changed paths，再经 `openzyme_test_affected_scope_map@1` 扩展：

- app/package source → owner tests；
- shared domain/runtime/protocol/API schema → cross-layer contract tests；
- public projection/Host API/workspace/report/evidence shape → 对应 Web UI tests/build；
- dependency/lock/tooling/config → 所有关联消费者；
- planner/map 自身、无法分类路径或 map digest drift → 完整 non-live Python 与 Web UI
  diagnostic set。

前端只允许在 diagnostic 中按 map 省略；receipt 必须记录
`frontend_omission=diagnostic_only` 和匹配 rule。任何 unknown 都扩大而不是缩小，永不返回
“零测试通过”。map 的每条规则用正反 fixture 覆盖，并由 shadow 模式观察真实改动一段时间。

没有依赖仅由 import graph 自动推导影响范围，因为配置、migration、public JSON shape、
docs/generated asset 和 shell contract 并不都出现在 Python import graph 中。

### 7. qualification 通过 exact node ownership 去重，canonical report 不变

planner 分别得到：

- `G`：legacy marker expression 收集的完整普通 pytest node set；
- `Qh`：qualification root 排除 scenarios 后的 harness self-test node set；
- `Qs`：canonical registry/test-manifest 中本次 `premerge_subset` 选择的 scenario node set。

legacy distinct required set是 `G ∪ Qh ∪ Qs`。owner 规则为：

- `Qh ∪ Qs` → `architecture_qualification_premerge`；
- `G - (Qh ∪ Qs)` → general pytest 的某个 serial/parallel partition；
- 仅在 versioned contract 中声明的节点才允许 intentional repeat。

plan 在下列情况执行前失败：owner 缺失、无声明多 owner、qualification node 不在 canonical
collection、marker selection drift、duplicate node id、unknown marker/resource class 或
source/environment digest drift。普通 pytest 使用本次 plan 生成的 exact node-id manifest；
collection plugin 先证明实际 `G` 与 plan 相等，再精确 deselect `Qh ∪ Qs`。禁止 hard-coded
qualification path/marker exclusion。

qualification runner增加可选的、仅供同调用 mainline 使用的 private execution sidecar，
记录实际 harness/scenario node outcomes、plan digest、invocation id、owner environment
digest 和 canonical report digest。现有 shell 两参数接口、report schema、registry、
test-manifest、process isolation、deadline、publication 和 pure verifier保持不变；
`architecture_admission` 不生成也不消费该 sidecar。

只有 sidecar 与本次 plan/source/environment 精确绑定、qualification report pure
verification green 后，general residual 才可把这些 nodes 视为已执行。qualification failure、
missing sidecar、skip/xfail 导致 canonical invariant 未满足、worker death或digest mismatch
都使 mainline失败，不会回退为普通 pytest重跑并隐藏根因。

没有修改 canonical qualification report 来承载 mainline receipt，因为 admission consumers
不应承担 repository test orchestration 的版本迁移。

### 8. authoritative stage 顺序先保持，结果按 node id 确定性归并

初始 authoritative DAG 保持：

```text
ruff source
  -> ruff audit
  -> compatibility audit
  -> closed pytest plan
  -> architecture qualification premerge
  -> general residual pytest
  -> Web UI tests
  -> Web UI build
  -> pure gate receipt verification
```

依赖 stage 失败后不启动后继 stage，保持当前 shell fail-fast 语义。允许的并行首先只在
general residual 内部；不同时运行 qualification、file-SQLite tests、Web UI build 或
compatibility scan。所有 worker result 最终按 node id 排序，wall-clock completion order
只进入 private timing，不影响 canonical receipt。

没有一开始并行 Ruff、qualification 和 frontend。它们可能共享 source tree、Python/Node
cache、CPU/IO，且会改变首个失败和资源竞争，难以把收益归因。

### 9. resource classification 默认串行，并行上限来自版本化证明

resource manifest 采用 proposal 的 closed classes：

- `parallel_pure`
- `parallel_temp_root`
- `bounded_service`
- `serial_unknown`
- `serial_file_sqlite`
- `serial_global_env`
- `serial_process_signal`
- `serial_qualification`
- `live_external`

未登记 node 一律 `serial_unknown`。可并行条目绑定 exact module/node collection digest、
fixture closure 和 proof-test ids；新增测试导致 digest drift 时只会退回 serial candidate 或
使 authoritative plan 要求重新分类，不会自动继承“安全”标签。

首个候选实现使用 root dev dependency 中固定版本的 `pytest-xdist`，仅对
`parallel_pure|parallel_temp_root` exact partition 使用显式 `-n N`。配置给出 hard maximum，
初始候选为 `4`，CLI 只允许降到 `1..N`，从不读取 CPU 数决定 `auto`。缺少 xdist、worker
crash、未知 worker 或隔离 root/port 分配失败均显式失败，不静默串行重跑。

每个 worker预分配唯一 temp root、cache root和必要的 brokered port；MICU ledger、`.env`、
repository-local mutable root、qualification report dir、sandbox/HPC workspace 和固定 Host
port不得进入并行 partition。`bounded_service` 要在单独阶段证明 port lease和所有
server/process join 后才能启用。

每次扩张并行集合前运行 repeated shuffled order、fixed-order、forced-serial 与 fixed-worker
对照；任何 outcome、node set 或持久副作用不一致都会把该 partition降回串行。forced-serial
使用同一 plan/coverage，只把 eligible partition 的 worker count 设为 `1`。

没有手写通用 subprocess pool，因为 pytest-xdist 已处理 fixture/worker lifecycle；安全性由
我们在 xdist 外的 exact partition 和资源证明控制，而不是由 xdist 自行猜测。

### 10. 串行热点只依据 trace 做语义等价修复

去重和首批并行稳定后，按 per-node累计时间优先处理：

- 以真实 sleep轮询的测试：改用已存在或新增的 injected monotonic clock/event通知，但仍
  保留至少一条真实 deadline/process integration 回归；
- 重复 `create_app()`：仅共享 immutable dependency graph/template，request state、repository
  connection、event loop和override仍按测试隔离；
- migration/schema初始化：允许从经 digest验证的 immutable pristine DB/template复制到每个
  test独占路径，禁止测试共享 writable SQLite；
- 重复大 fixture/serialization：使用 session-scoped immutable bytes/object factory，
  每个会修改的消费者显式 copy；
- subprocess/server cleanup：以 readiness/join event替代固定等待，不降低最终 retirement
  断言。

每项优化先有单独 focused regression，随后通过 forced-serial/optimized parity 和完整
mainline。若需要改变生产 runtime seam，则同一 slice 同步主架构与相关 `docs/v3/`，不能以
“仅测试优化”绕过产品合同评审。

### 11. receipt 证明 closure，不授予其他 authority

`openzyme_test_gate_receipt@1` 包含 plan/source digest、每个 stage argv/environment/
toolchain identity、collected/executed/outcome node sets、qualification report digest、
frontend outcomes、timing/resource assignments、terminal status 和 bounded diagnostics。
pure verifier重新计算：

- plan与receipt canonical/self digest；
- source/config/toolchain未漂移；
- required、owned、executed、missing、duplicate、skip/xfail/deselected set closure；
- qualification sidecar/report绑定；
- Web UI test/build均 present且green；
- stage dependency、deadline和worker policy；
- diagnostic authority flags或 authoritative terminal outcome。

missing output、unexpected deselect、worker death、timeout、receipt parse/version错误和 verifier
失败都使 gate失败。receipt可用于审计本次运行，但改动任一 source/toolchain/config 后不能
复用，也不能被 AOX pin/preflight/live verifier接受。

### 12. authority切换是一次原子入口变更

在 shadow阶段，`scripts/check-mainline.sh` 保持原样。optimized candidate通过所有验收后：

- 把当前顺序实现冻结为明确的 `scripts/check-mainline-legacy.sh` rollback入口；
- `scripts/check-mainline.sh` 原子切换为
  `run-test-gate.py mainline_authoritative`；
- 提供同一 planner 的 `--forced-serial`，用于区分并行/顺序问题；
- 终端和文档只声明一个当前 authority，legacy输出明确标记 rollback comparison，不能与
  optimized receipt混合；
- rollback只需恢复 wrapper到legacy入口，并使 optimized receipt不再代表当前 authority。

没有长期保留两个都叫 authoritative 的脚本；双权威会让 CI、开发者和AOX文档产生不同绿色
含义。

## Risks / Trade-offs

- **[collection 增加前置开销]** → collection 结果同时服务 ownership、resource partition 和
  node timing；验收要求 planning/receipt低于总时长 `5%`，否则先优化 planner再切换。
- **[pytest collection 本身可能执行 import side effect]** → 保持 Ruff/audit优先、清除 live
  opt-in、使用 closed environment，并对 collection期间零外部 effect增加回归。
- **[qualification sidecar与canonical report分叉]** → sidecar只允许引用并验证 report
  digest；AOX consumers完全不读取sidecar，缺失sidecar只影响 optimized mainline。
- **[exact deselection掩盖新测试]** → 每次 invocation重新收集 `G/Qh/Qs` 并做set closure；
  manifest不跨运行持久复用。
- **[affected map漏掉跨层消费者]** → unknown/default扩大到完整non-live+frontend，
  shadow记录实际选择；它始终非权威。
- **[并行暴露顺序/资源竞争]** → unknown默认串行、fixed workers、隔离proof、
  shuffled/serial parity和快速demotion。
- **[xdist增加依赖和worker启动成本]** → 只在预计收益超过启动成本的closed partition使用，
  小集合保持单进程；版本固定并进入toolchain digest。
- **[single-pass audit提高内存]** → 只缓存受支持文本和AST，记录index size；若峰值不可接受，
  改为按suffix一次流式multi-pattern scan，不退回重复磁盘读取。
- **[计时噪声造成虚假25%]** → paired five-run median、host/source绑定、MAD和stage
  breakdown；不使用单次最好值。
- **[legacy与optimized长期漂移]** → shadow期以exact obligations比较；切换后legacy仅作
  短期rollback并有drift test，稳定后是否退休另行评审。
- **[真实串行热点修复改变产品行为]** → 每个热点单独slice、focused semantic regression、
  forced-serial和完整mainline；涉及runtime seam时同步稳定架构文档。

## Migration Plan

1. **Phase 0 — measurement/shadow**
   - 新增schemas、strict model/verifier、pytest collection/timing plugin和benchmark runner。
   - 捕获legacy五对cold/warm baseline；shadow plan对比exact Python node和Web UI command
     closure，当前 `check-mainline.sh` 不变。
2. **Phase 1 — audit与diagnostic**
   - compatibility audit切为single-pass index并证明canonical output parity。
   - 发布focused/affected入口、dependency map和non-authoritative receipts；收集常用改动
     `10–60` 秒数据，legacy mainline仍为authority。
3. **Phase 2 — qualification exact dedup**
   - 增加mainline-only qualification sidecar、exact ownership和general residual plugin。
   - 先以shadow/opt-in candidate运行；missing/duplicate/drift fault injection必须在执行前
     fail closed。
4. **Phase 3 — resource-audited bounded parallelism**
   - 从pure/temp-root小分区开始，加入fixed-worker与forced-serial对照。
   - 每次扩张均保留serial route并记录真实收益、flake和resource evidence。
5. **Phase 4 — first authority cutover**
   - 在代表性clean revisions或约定replay corpus上完成至少二十组terminal/coverage等价
     对照，并取得五对same-host cold/warm median至少 `25%` 降时。
   - 同步 `docs/OpenZyme架构设计.md`、`docs/v3/README.md`、qualification文档、proposal
     lifecycle和开发命令；原子切换wrapper并保留legacy rollback。
6. **Phase 5 — serial hotspot closure**
   - 按trace处理真实等待、app/migration和fixture热点，逐slice重复parity/performance测量。
   - 达到或尽可能逼近 `5–7` 分钟；若物理下界更高，报告remaining critical path而不删测。
7. **Final verification**
   - strict OpenSpec、focused regressions、audit parity/fault tests、diagnostic closure、
     optimized+forced-serial mainline、Web UI、pure receipt verification和文档一致性全部green。
   - 明确重验full clean architecture admission仍使用原命令且report/AOX consumers无行为变化；
     不启动任何live/AOX operation。

任一阶段回滚都把 `scripts/check-mainline.sh` 指回最后一个已验证authority实现，并废弃后续
candidate receipts；不会把失败candidate解释成legacy通过。

## Open Questions

- 首批可安全并行的exact modules和worker hard maximum由Phase 0资源/时序数据决定；在证据
  形成前默认全部 `serial_unknown`，候选上限不得超过 `4`。
- `5–7` 分钟是否能在当前16-core、现有file-SQLite测试比例下实现需要Phase 3/5 critical-path
  数据回答；它是优化目标，不是弱化coverage的理由。
- process-only cold与warm差异若小于host噪声，将额外报告host load和重复样本，但不会请求
  root级page-cache清理或删除用户tool caches。
- legacy rollback入口的退休时间不在本变更内；至少保留到optimized authority经过持续CI/
  本地观察且没有unresolved parity mismatch。
