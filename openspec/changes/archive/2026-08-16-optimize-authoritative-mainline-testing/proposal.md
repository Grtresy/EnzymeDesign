## Why

当前 `./scripts/check-mainline.sh` 在同一次调用中重复执行 architecture qualification
已拥有的 pytest 节点，并把 compatibility audit、完整 Python 测试与 Web UI 验证串行
排布，实测一次反馈约需十四分钟。需要在不减少必需节点、不弱化环境与证据语义的前提下，
把常用诊断反馈压到秒级，并把权威主线现实压缩到约五至七分钟。

## What Changes

- 为当前主线建立阶段级和节点级计时、至少五次同机 cold/warm 基线以及 shadow execution
  plan；在任何权威切换前，以 exact node-id 和前端命令集合证明 coverage closure。
- 优化 compatibility audit 的重复源码发现、解析与规则扫描，使同一次调用共享一次闭合
  inventory，同时保持未知输入、解析失败和规则违规的 fail-closed 语义。
- 增加 `focused_diagnostic` 与 `affected_scope_diagnostic` 入口；它们允许 dirty tree，
  必须机器可读并醒目声明“非权威”，未知路径或依赖图漂移只能扩展到更安全集合，不能静默
  选成零测试。
- 把现有完整非 live 验证定义为 `mainline_authoritative`：继续包含 Ruff、compatibility
  audit、architecture qualification `premerge_subset`、完整必需 Python 节点、Web UI
  tests 和 production build，并保留当前失败、skip、xfail、timeout 与环境关闭语义。
- 在单次 `mainline_authoritative` invocation 内，为每个必需 pytest node 建立唯一 owner；
  architecture qualification 继续拥有其 harness self-tests、所选 scenarios、canonical
  report 与 pure verification，普通 pytest 仅按本次运行生成的 exact node-id manifest
  排除已经成功执行且语义不弱于普通执行的节点。
- 仅对已经用回归证明资源隔离的测试类别启用固定上限、可复现的 bounded parallelism；
  未分类节点默认串行，SQLite、全局环境、process signal、qualification 与 live external
  类保持串行或排除，并保留 forced-serial 对照和旧顺序入口作为回滚路径。
- 在覆盖和并行闭合后，继续缩短真实等待、重复 app construction、migration/schema
  初始化等串行热点；不得用 blanket retry、放宽 timeout 或伪造时钟结果掩盖失败。
- 产生版本化的 execution plan、stage/node timing 与 gate receipt，记录 source identity、
  toolchain、环境策略、节点所有权、资源分类和终态；它们只属于 operator/CI evidence，
  不成为 session、task、lane、approval、artifact 或 scientific workflow 真状态。
- 以同机同 revision 的 cold/warm median 验证首阶段权威主线至少降低 `25%`，持续以
  `5–7` 分钟作为现实权威目标、`10–60` 秒作为 focused/affected 目标，并报告每阶段真实
  测量及回滚状态。
- 保持 full clean `architecture_admission`、AOX launch、live marker、MICU/provider/HPC/
  Chrome effect 与 scientific evidence contract 独立；禁止删测、宽泛 deselect、全局
  `pytest -n auto`、跨提交 pass cache 或用普通 pytest 输出替代 qualification receipt。
- 同步 `docs/OpenZyme架构设计.md`、相关 `docs/v3/` 稳定文档与架构提案生命周期，并为
  planner closure、诊断选择、精确去重、资源隔离、receipt 验证、回滚和性能验收补充回归。

## Capabilities

### New Capabilities

- `authoritative-test-execution`: 定义权威主线的闭合 execution plan、节点唯一所有权、
  qualification 精确同调用去重、资源审计后的有界调度、版本化 evidence、回滚以及
  cold/warm 性能验收，同时保持现有必需覆盖与权威边界。
- `diagnostic-test-selection`: 定义 focused/affected-scope 的选择输入、依赖图闭包、
  unknown/drift 扩展策略、前端诊断选择和明确非权威输出，使常用反馈变快但不能冒充
  mainline、architecture admission 或 live/cutover 证据。

### Modified Capabilities

无。现有主规格描述产品/runtime/scientific/HPC 行为；本变更新增的是仓库级验证编排和
operator evidence，不改变这些产品能力的需求语义。

## Impact

- 主要影响 `scripts/check-mainline.sh`、`scripts/audit-v3-compat-callers.py`、
  `scripts/check-v3-architecture-qualification.sh`、`scripts/v3_architecture_qualification.py`
  及新增的 test planner/runner、配置、schema 和 verifier。
- 测试影响覆盖 `apps/`、`packages/` 的 pytest collection/resource metadata，以及
  `apps/openzyme-web-ui` 的 diagnostic dependency mapping；产品生产代码只在移除真实
  测试初始化/等待热点确有必要时进行局部、行为等价优化。
- 文档影响 `docs/OpenZyme架构设计.md`、`docs/v3/README.md`、architecture
  qualification 文档和原始 deferred proposal；切换前旧 `check-mainline.sh` 语义仍是
  权威回滚基线。
- 不新增 live 外部调用、AOX authority、产品 API 或顶层控制面状态；依赖变更仅允许为
  明确、固定的测试编排能力服务，并须经过资源隔离和覆盖等价证明。
