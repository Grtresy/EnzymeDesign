# Biomni 参考资料

本文档用于沉淀 Biomni 的公开资料和对 OpenZyme 的对照笔记，方便后续做架构、能力边界和产品策略比较。

资料快照日期：2026-03-17

详细来源见：[sources.md](./sources.md)

## Biomni 是什么

Biomni 可以理解成一个面向生物医学研究任务的 agent stack，而不是单个模型。

从公开论文摘要和官方仓库来看，它的核心做法有两层：

- 用统一的 biomedical action environment 承载多种研究能力
- 让通用 agent 通过推理、检索增强规划和代码执行去动态组合这些能力

官方公开材料里目前能看到的关键词包括：

- Biomni-A1 agent
- Biomni-R0 reasoning model
- Know-How Library
- MCP support
- Biomni-Eval1 benchmark
- web interface

同时，官方仓库也明确给了一个很重要的安全提醒：当前版本会执行 LLM 生成的代码，并具有完整系统权限。因此它更适合作为研究系统或能力参考，而不是可直接照搬到 OpenZyme 的默认运行模型。

## 值得 OpenZyme 借鉴的点

### 1. 把 research 当成一等动作，而不是 prompt 附件

Biomni 的强项不只是“能回答生物问题”，而是把检索、分析、调用工具、组合工作流都视为 agent 的动作空间。

对 OpenZyme 来说，最值得借的是：

- 让 host workflow 在信息不足时先主动检索 evidence
- 再基于 evidence 选择下游 preprocess 或 HPC 动作
- 不把外部 research 仅仅塞进一次性 prompt

这与当前 OpenZyme 的 `mcp-bio-research` 方向是一致的。

### 2. 建立 evidence-first 的引用层

Biomni 适合借鉴的不是“多工具”本身，而是“让工具结果可复用、可追溯、可再消费”的思路。

对 OpenZyme 更合适的落地方式是：

- research 结果统一形成 `evidence_ref`
- 通过稳定 resource URI 读取
- 写回 decision trace 和 episode state
- 保持 external research evidence 与 curated knowledge 分层

### 3. 建立 enzyme design 版 Know-How Library

Biomni 的 `Know-How Library` 很值得参考，但 OpenZyme 不应该直接照搬成泛生物医学知识层。

更合适的方向是：

- 把 enzyme family、substrate、assay、structure analysis、失败模式、常见实验启发式做成 reviewed knowledge
- 明确区分 `evidence_ref` 和 `knowledge_ref`
- 只让已审核知识进入长期工作上下文

### 4. 用 benchmark / replay 检验借鉴是否真的有效

Biomni 明确把 benchmark 放在公开能力的一部分里。OpenZyme 如果要借鉴 Biomni，最好也补一套自己的回放与评估机制，而不是只看 demo 是否“像 agent”。

建议优先验证的问题：

- 引入 research evidence 后，是否更少出现盲目下游动作
- 是否能更稳定地产出可审计的 decision trace
- 是否能提升约束修订和 action selection 的质量

## 不建议照搬的点

### 1. 不要把 OpenZyme 改成通用生物医学代理

OpenZyme 的优势是酶设计场景下的 Host 控制平面、恢复性、审批、HPC 编排和审计，而不是“大而全”。

### 2. 不要接受高权限默认执行模型

Biomni 官方仓库已经明确提示当前版本会执行 LLM 生成代码并拥有完整系统权限。OpenZyme 应继续保留 trust policy、approval gate、workflow budget 这类约束。

### 3. 不要让聊天记录变成状态真源

OpenZyme 现有方向更适合长期工作流：project / episode / run / artifact / decision 才是状态真源，聊天只是入口。

## 对 OpenZyme 的直接映射

目前最直接的对应切入点有三处：

1. Host capability discovery 与 inspect 机制  
   参考：V1 归档规格 [host-capability-discovery/spec.md](/home/grtresy/VSCodeRepo/EnzymeDesign/legacy/v1/openspec/specs/host-capability-discovery/spec.md)

2. `mcp-bio-research` 的能力设计  
   参考：V1 归档 proposal [proposal.md](/home/grtresy/VSCodeRepo/EnzymeDesign/legacy/v1/openspec/changes/add-mcp-bio-research/proposal.md)  
   参考：V1 归档 design [design.md](/home/grtresy/VSCodeRepo/EnzymeDesign/legacy/v1/openspec/changes/add-mcp-bio-research/design.md)

3. Host-first / workflow-first 架构边界  
   参考：[OpenZyme架构设计.md](../OpenZyme架构设计.md)

注意：以上前两项目前都属于 `legacy/v1` 归档探索，不代表当前根仓库已经在主线实现这些能力。

## 我对后续参考方式的建议

后面如果继续研究 Biomni，建议优先把新增信息补到这三个方向，而不是盲目堆外部链接：

- action space：Biomni 新增了哪些能力类型
- evidence / know-how：Biomni 如何让知识可复用
- safety / product boundary：哪些地方适合 OpenZyme，哪些地方明显不适合
