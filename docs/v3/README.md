# OpenZyme V3 稳定文档索引

当前权威入口是 [OpenZyme架构设计.md](../OpenZyme架构设计.md)。本目录描述
当前唯一在线公共合同 `file_workspace_public@2` 的 Kernel、Adapter、Plugin、Driver 与 Distribution
实现。`file_workspace_public@1`、`openzyme_file_workspace_final@2`、旧 file-era 说明、冻结 campaign 和
归档 OpenSpec 只具有离线迁移或历史解释力。

`separate-openzyme-kernel-from-capability-extensions` 已把 mixed-package authority 迁为显式 Kernel、Adapter、
Plugin、Driver 与 Distribution，并删除旧 Core/Domain/Runtime/Execution packages。目标定义见
[ADR-0001](adr/0001-what-is-openzyme.md)，实际 component/import/table owner 基线见 [architecture/](architecture/)。
两个 Distribution manifest 的 `active` 只表示 exact component graph 可构建；Session 运行 authority 仍需
schema/wheel/composition proof、deployment epoch、Session pin 和对应 operational selection。真实历史部署的
离线 adoption/cutover 未在本 change 中执行。

建议阅读顺序：

1. [00-harness-doctrine.md](00-harness-doctrine.md)：harness 与 agent 的职责边界。
2. [01-target-architecture.md](01-target-architecture.md)：模块、所有权和数据流。
3. [02-control-plane.md](02-control-plane.md)：canonical state、repository 与 lifecycle。
4. [03-capability-engines.md](03-capability-engines.md)：引擎和外部 effect 边界。
5. [04-public-interfaces.md](04-public-interfaces.md)：Host、CLI、UI 和 media contract。
6. [05-agent-runtime.md](05-agent-runtime.md)：resident teammate、signal、lease 与 protocol。
7. [06-top-level-llm-loop.md](06-top-level-llm-loop.md)：顶层有界 agent loop。
8. [07-runtime-hpc-reliability.md](07-runtime-hpc-reliability.md)：revision-bound HPC 与恢复。
9. [08-failure-recovery-and-scientific-attempts.md](08-failure-recovery-and-scientific-attempts.md)：
   effect certainty、failure 和 scientific closure。
10. [file-workspace-migration.md](file-workspace-migration.md)：breaking cutover、离线迁移与删除。
11. [compatibility-sunset.md](compatibility-sunset.md)：已移除 surface 的防回归门禁。
12. [execution-pipeline-docs/README.md](execution-pipeline-docs/README.md)：executor 可检索文档。
13. [adr/0001-what-is-openzyme.md](adr/0001-what-is-openzyme.md)：双轴架构、组件通信与 HMMER/HPC 组合。
14. [architecture/source-bound-baseline.json](architecture/source-bound-baseline.json)：当前组件与反向依赖基线。
15. [architecture/catalog-owner-inventory.json](architecture/catalog-owner-inventory.json)：tool、route、event、
    worker、migration、资格场景等可执行 surface 的唯一 owner 与重复 authority 基线。
16. [architecture/pre-split-deployment-state-inventory.json](architecture/pre-split-deployment-state-inventory.json)：
    拆分前 SQLite 的只读、去敏聚合快照；只作迁移规划证据，不是 cutover authority。
17. [plugin-authoring-guide.md](plugin-authoring-guide.md)：Plugin application services、state、Driver 与通信规范。
18. [extension-composition-manifest-reference.md](extension-composition-manifest-reference.md)：closed
    Distribution/Adapter/Plugin/Driver schema、catalog 与 runtime mount reference。
19. [deployment-composition-operator-guide.md](deployment-composition-operator-guide.md)：read-only activation、
    Session composition pin、入口守卫与 offline Plugin change 操作手册。
20. [research-extension.md](research-extension.md)：Research Plugin、Provider Adapter、worker、来源回执与
    `PublishedRevision + RevisionPathRef` 交接边界。
21. [reporting-extension.md](reporting-extension.md)：Reporting state、file-native report、renderer、projection
    与只读 Task finish validator 边界。
22. [science-extension.md](science-extension.md)：Science lifecycle、workflow registry、namespaced state、finish
    separation 与只读 Task finish validator 边界。
23. [enzymedesign-distribution.md](enzymedesign-distribution.md)：EnzymeDesign exact composition、产品能力、
    AOX 注入、HMMER/HPC 路由与 non-live 验收边界。
24. [external-qualification-readiness.md](external-qualification-readiness.md)：外部资格六维单元、profile、
    credential locator、recording backend、real-subject identity gap、两批 dry plan、receipt/admission 与
    required non-live/manual gate。

实现 V3 时的固定规则：

- 用户消息入口不隐式 drain；runtime drain 是显式 durable command。
- `protocol.send` 只投递并排队 wakeup；`task.finish` 是显式业务终态。
- session lease、process epoch、execution fence、delivery fence、workspace generation 和
  mutation writer 是不同 authority。
- 文件通过 Git revision、published path ref 和 Git LFS closure 共享；不存在第二套通用
  catalog 或自动 staging。
- HPC 输入来自 exact revision、LFS closure 和 Gitless compute tree；结果由同一 opaque handle 的
  observation/terminal receipt 与 owner workspace result 表达，不声明 `expected_outputs`，无输出成功不补文件。
- 公开 `failure_observation@2` 与 Host 私有 diagnostic 共用 `diagnostic_id`；异常保留 cause chain，
  不静默吞掉、误分类、自动重试或隐藏 fallback。
- 历史导入 ref 永远 `historical_import_non_adoptable`。
- fresh bootstrap receipt 与 offline removal ledger 分开验证；old/incomplete/tampered database 在 mutation
  前拒绝，普通 startup 不执行 legacy upgrade。
- focused test 不能替代 architecture qualification 和 `./scripts/check-mainline.sh`。
- live/provider/HPC 行为需要单独 opt-in，不能从非 live gate 推断。
- `ready_non_live` 是独立证据层；它不能 adopt 成 `qualified`，也不能推导 `cutover` 或 live occurrence。
- Standard/EnzymeDesign 是 Distribution，不是语义层；已安装但未被 manifest 选择的组件不形成能力。
- 四类 capability fact、declared catalog 与 per-turn affordance 互不替代；dispatch 前必须重验 exact route。
- 架构拆分基线使用 `uv run python scripts/check-openzyme-architecture.py` 校验，但该 gate 不替代最终
  三 profile qualification 或离线 `@2` cutover proof。
