# OpenZyme V3 稳定文档索引

当前权威入口是 [OpenZyme架构设计.md](../OpenZyme架构设计.md)。本目录描述
`file_workspace_public@1` 与 `openzyme_file_workspace_final@2` 的稳定实现；旧 artifact-era
说明、冻结 campaign 和归档 OpenSpec 只具有历史解释力。

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
