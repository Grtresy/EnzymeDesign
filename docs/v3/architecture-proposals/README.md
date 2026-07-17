# Deferred V3 architecture proposals

本目录记录实施中发现、会影响 agent 发挥但超出局部修复边界的架构调整。每份文档对应一个独立计划；它们不是当前产品合同，也不表示代码已实现。

进入本目录的调整通常涉及顶层真状态、跨包 ownership、scheduler/approval/protocol 语义或 workflow schema 的整体迁移。当前 Goal 只允许记录问题、目标、不变量、方案、迁移、风险与验收，不实施这些大调整。

当前提案：

- `role-scoped-workflow-composition.md`：把一个显式 workflow 选择拆成可验证的 role-scoped knowledge bindings，同时避免固定 agent 拓扑。
