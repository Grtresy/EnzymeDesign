
## V3 runtime 并发演进备注

当前 V3 runtime 设计是务实的过渡形态：scheduler/background runtime 已经是 async，负责 claim `AgentRuntimeSignal`、限流并通过 `asyncio.to_thread()` 调用同步 `wake_agent()`；真正的 master / teammate agent loop、repository 写入、tool/engine dispatch 仍主要是同步路径，因此默认 `global/session/agent` 并发都设为 1，能守住 explicit runtime/drain 和状态一致性边界，但同一 session 内仍基本串行，长 agent turn 可能挡住其他 pending loop。短期不要把 `wake_agent()` 直接改成表面 async；更合理的演进是继续把它限定为 scheduler 内部 worker，先补强并发语义测试（不同 agent 可并发、同 agent 不重入、同 task 不双 claim），明确 session/agent/task 级写入锁和 transaction 边界，再逐步 async 化 LLM invoker、tool registry、engine dispatch 与 repository 访问，最后再考虑把 agent turn executor 本身改成真正 async。

## heuristic learning 是否可用于OZ

## memory.compact 需要再检查

## lane 这个概念是否真正有用？

## 调试问题

这部分需要进一步讨论，持久化保存用户使用过程中产生的各种记录、文件、数据库，用于后续迭代升级
