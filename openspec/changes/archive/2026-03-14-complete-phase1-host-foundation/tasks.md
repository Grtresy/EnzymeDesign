## 1. Capability Gateway And Registry

- [x] 1.1 在 `packages/enzyme-host-runtime` 中定义 capability summary、detail contract、inspect scope 和 normalized execution result 的类型模型
- [x] 1.2 实现 Host capability gateway / registry，统一列出 summaries、inspect detail contract，并支持 Host override、MCP metadata、自动生成三层 summary 来源
- [x] 1.3 让 `mcp-preprocess`、`mcp-hpc-tool-contracts` 与 `mcp-project-memory` 通过统一的 runtime-facing capability/client contract 接入，而不是继续作为上层 workflow 的专有直连路径

## 2. Planning And Workflow Integration

- [x] 2.1 调整 host agent planning，使默认决策上下文消费 capability summaries，并在需要时显式 inspect 单个 capability
- [x] 2.2 为 capability inspect、selected action、execution start、execution finish 和 observation record 增加显式 workflow transition 语义与稳定标识关联
- [x] 2.3 收敛 execute/observe 路径，使 runtime 在执行后通过规范 workflow transition 回写 observation，而不是只做 service 层快照副作用

## 3. Project Memory Canonical State And Audit

- [x] 3.1 扩展 `apps/mcp-project-memory`，增加 canonical workflow audit 资源与 append-only 事件写入契约
- [x] 3.2 让 canonical snapshot 与 workflow audit 共享稳定对象标识，并覆盖 capability inspect、gate transition、execution 和 feedback resolution 事件
- [x] 3.3 校准 `state_version` / `resume_token` 相关写入路径，确保跨宿主 stale-state 拒绝、恢复锚点和新鲜度边界与新 audit 模型一致

## 4. Host Surfaces And Runtime Consumption

- [x] 4.1 更新 shared runtime 服务接口，让 CLI 与 Web Host 都能读取 capability summaries、inspect detail contract 和 workflow audit 摘要
- [x] 4.2 调整 Web Host，仅在 trace / debug 视图暴露 capability inspect 与 workflow audit 事件，并保持主操作区聚焦 workflow 控制与 gate 状态
- [x] 4.3 确保 CLI 与 Web Host 都不维护 capability visibility 或 workflow audit 的私有副本，而是继续只读取 canonical runtime/project-memory 状态

## 5. Verification And Cleanup

- [x] 5.1 增加 capability registry、summary 解析、detail inspect scope 和 normalized gateway 的单元测试
- [x] 5.2 增加 workflow 集成测试，覆盖 summary -> inspect -> tool selection -> execution -> observation audit 链路
- [x] 5.3 增加 `mcp-project-memory` 的回归测试，覆盖 append-only workflow audit、canonical resources 和 stale-state 行为
- [x] 5.4 更新相关开发文档，说明 capability discovery、统一 runtime capability gateway、workflow audit 和 Phase 1 foundation 收尾后的接入方式
