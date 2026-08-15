## Why

现有 `SessionRuntimeLease`、execution lease 和 mutation fence 分别解决 scheduler 与 canonical mutation ownership，不能表达“一次授予后 agent 在自己的 capsule 中自由使用文件、网络、Git 和传输”的产品语义。逐命令 approval 又会重新制造用户明确要求移除的摩擦。

## What Changes

- 新增独立的 `AgentCapabilityLease`，绑定 `session + agent_member + workspace_generation`，在 session 结束、agent retirement、workspace generation 替换或显式 revoke 前持续有效。
- lease 一次性授予原生 filesystem、shell、Git、Git LFS、network、upload 和 download 能力；scope 内命令与传输不重复请求 approval。
- executor lease 额外包含 SSH、rsync/scp、HPC login workspace CRUD 与 Slurm 操作；其他角色可使用一般网络和 Git，但不因此获得 HPC credential。
- delegation 为每个 subagent 自动签发绑定其独立 workspace 的派生 lease；不共享 parent token 或 workspace。
- capability lease 与 session runtime lease、controlled-operation execution lease、scientific authorization 和 publication intent 保持正交，任何一种都不得替代另一种。
- 错误直接返回并停止当前动作，不做 endpoint fallback、隐式降权、自动重开 approval 或静默重试。

## Capabilities

### New Capabilities
- `agent-capability-lease`: 定义 agent/capsule 生命周期的一次性能力授予、派生、撤销与 scope 语义。

### Modified Capabilities

## Impact

影响 domain/repository、agent creation/delegation、tool exposure、Podman 网络和 credential 注入、Host API projection 及 executor/HPC admission。不会改变 `task.finish`、runtime drain 或 scientific attempt authority。
