
## V3 runtime 并发演进备注

当前 V3 runtime 设计是务实的过渡形态：scheduler/background runtime 已经是 async，负责 claim `AgentRuntimeSignal`、限流并通过 `asyncio.to_thread()` 调用同步 `wake_agent()`；真正的 master / teammate agent loop、repository 写入、tool/engine dispatch 仍主要是同步路径，因此默认 `global/session/agent` 并发都设为 1，能守住 explicit runtime/drain 和状态一致性边界，但同一 session 内仍基本串行，长 agent turn 可能挡住其他 pending loop。短期不要把 `wake_agent()` 直接改成表面 async；更合理的演进是继续把它限定为 scheduler 内部 worker，先补强并发语义测试（不同 agent 可并发、同 agent 不重入、同 task 不双 claim），明确 session/agent/task 级写入锁和 transaction 边界，再逐步 async 化 LLM invoker、tool registry、engine dispatch 与 repository 访问，最后再考虑把 agent turn executor 本身改成真正 async。

## heuristic learning 是否可用于OZ

## memory.compact 需要再检查

## lane 这个概念是否真正有用？

## 调试问题

这部分需要进一步讨论，持久化保存用户使用过程中产生的各种记录、文件、数据库，用于后续迭代升级

## hpc访问问题

如果需要频繁调用hpc中工具，会不会导致需要大量网络传输带宽？

## mcp-hpc-runner 是否有必要收回？

## LLM wiki

https://mp.weixin.qq.com/s/KSBftq6OJlahrm725FZELQ

## 训练skill

https://mp.weixin.qq.com/s/sqHF3d3l5PX3VOs0Mtwk3A

## 学习Biomni

通俗讲：OpenZyme 不应该学 Biomni “怎么放开手让 agent 随便跑”，而应该学 Biomni “怎么让生物研究动作变丰富”。

  最该学这几件事：

  1. 把生物工具做成大工具箱

  Biomni 强在工具面很宽：文献、数据库、基因、单细胞、药物性质、protocol、各种分析函数都有。
  OpenZyme 现在的骨架更严谨，但工具还偏少。

  应该学的是：给 OpenZyme 增加更多真实可用的生物/酶设计工具，而不是只靠 LLM 解释。

  例如：

  - 查 UniProt / PDB / InterPro
  - 拉序列、结构、功能注释
  - 做 MSA、HMM、同源搜索
  - 查文献和实验 protocol
  - 把结果变成可复用 artifact / evidence

  2. 把 research 当成正式步骤

  Biomni 不是只让模型“回答问题”，而是让模型先检索、再分析、再调用工具。

  OpenZyme 应该学这一点：
  不要一上来就跑 docking / fpocket / HPC。应该先问：

  - 这个蛋白有没有可靠序列？
  - 有没有结构？
  - 有没有同源家族？
  - 底物/功能证据来自哪里？
  - 哪些信息缺失？

  也就是说，先形成 evidence，再决定后续执行。

  3. 做 enzyme design 版 Know-How Library

  Biomni 有 Know-How Library，类似“领域经验库”。

  OpenZyme 可以学这个思路，但不要做泛生物医学知识库，而是做酶设计专用知识库：

  - 酶家族常见判断方法
  - 底物识别经验
  - 活性位点分析套路
  - 常见失败模式
  - assay / mutagenesis / docking 的注意事项
  - AOX/HMM/fpocket/Vina 的推荐工作流

  这比把一堆规则硬塞进 prompt 好，因为可以版本化、检索、审计。

  4. 学它的 benchmark 思路

  Biomni 有 Biomni-Eval1，用任务集衡量 agent 能力。

  OpenZyme 也需要自己的 eval/replay，不然只能靠 demo 感觉判断“好像能跑”。

  OpenZyme 应该有类似：

  - 给定一个 enzyme design 任务，是否能先找证据？
  - 是否能正确生成 task board？
  - 是否能选择合理工具？
  - 是否能把 artifact 和 report 串起来？
  - 是否避免无证据乱跑 HPC？

  5. 学 MCP/外部工具生态

  Biomni 支持 MCP，说明它很重视“工具可插拔”。

  OpenZyme 也应该继续往这个方向走：外部工具可以接入，但必须经过 OpenZyme 的边界：

  - 统一 tool schema
  - 统一 provenance
  - 统一 approval
  - 统一 artifact catalog
  - 统一失败语义

  不应该让 MCP 工具直接变成“agent 想怎么调用就怎么调用”。
#
  最不该学的是：

  - 不要学 Biomni 的高权限默认执行。它自己也提醒会用完整系统权限执行 LLM 生成代码。
  - 不要把 OpenZyme 改成泛生物医学 agent。OpenZyme 的定位应该还是酶设计/HPC/可审计工作流。
  - 不要让聊天记录或 notebook log 变成状态真源。OpenZyme 仍然应该坚持 session、task、artifact、approval、run、report 这些结构化状态。

  一句话总结：
  学 Biomni 的“生物能力广度”和“research-first 工具生态”，不要学它的“高权限自由执行模型”。OpenZyme 要把 Biomni 的工具丰富度装进自己的安全、可恢复、可审计架构里。

## bio_tools.hmmer_search_cli 未完成

## structure_tools.fpocket / docking.vina 需核查真实 runner backend是否接入

## 自动approval

## 参数向用户确认

## 工具 skill

## 关注文章

https://mp.weixin.qq.com/s/nMRaj4aCY8DPqFC3pcItDg

## 科学对象模型

## 上下文缓存复用（codex）

## 论文想法

从领域知识出发，对比不同形式的领域知识对最后设计效果的影响。

## 分析一下openzyme现在暴露给agent的工具，学习参考 @references/codex 里面的设计，我们的工具是不是过于冗余复杂了？我在考虑进行简化以降低agent的心智负担

## agent 应保留策略自由；harness 要把世界的真实约束忠实、结构化、低摩擦地呈现出来。
