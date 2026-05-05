# Biomni Sources

本文档记录当前用于参考 Biomni 的公开来源、检索日期和简短说明，方便后续追溯。

资料快照日期：2026-03-17

## 1. 官方站点

- 名称：Biomni official site
- 链接：https://biomni.stanford.edu/
- 检索日期：2026-03-17
- 用途：作为项目主页入口，适合追踪公开定位、入口页和后续官方更新。

## 2. 官方 GitHub 仓库

- 名称：snap-stanford/Biomni
- 链接：https://github.com/snap-stanford/Biomni
- 检索日期：2026-03-17
- 用途：最适合查看公开可用能力、README 说明、运行方式和安全提醒。
- 备注：
  - README 中可见的公开能力标签包括 `Biomni-A1`、`Biomni-R0`、`Know-How Library`、`MCP support`、`Biomni-Eval1`、`web interface`
  - README 明确提醒当前版本会执行 LLM 生成的代码，并具有完整系统权限
  - README 同时提到该开源 release 与当前 web platform 不完全一致，并写明一个冻结时间点为 2025-04-15

## 3. 正式论文

- 名称：Biomni: a general-purpose biomedical AI agent
- 链接：https://www.nature.com/articles/s41586-025-09113-x
- 检索日期：2026-03-17
- 用途：适合确认项目的论文级目标、方法、实验设置和定位。

## 4. PubMed 摘要页

- 名称：Biomni: a general-purpose biomedical AI agent
- 链接：https://pubmed.ncbi.nlm.nih.gov/40501924/
- 检索日期：2026-03-17
- 用途：适合快速查看标准化摘要、作者信息和对外可引用的论文描述。
- 备注：
  - 摘要可用于确认 Biomni 的定位不是单点模型，而是面向多种 biomedical task 的 agent system
  - 摘要提到其目标覆盖 25 个 biomedical domains

## 5. 本仓库内的对应参考位点

- OpenZyme 架构主文档：[/home/grtresy/VSCodeRepo/EnzymeDesign/docs/OpenZyme架构设计.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/OpenZyme架构设计.md)
- V1 Host capability discovery 归档规格：[/home/grtresy/VSCodeRepo/EnzymeDesign/legacy/v1/openspec/specs/host-capability-discovery/spec.md](/home/grtresy/VSCodeRepo/EnzymeDesign/legacy/v1/openspec/specs/host-capability-discovery/spec.md)
- V1 `mcp-bio-research` 归档 proposal：[/home/grtresy/VSCodeRepo/EnzymeDesign/legacy/v1/openspec/changes/add-mcp-bio-research/proposal.md](/home/grtresy/VSCodeRepo/EnzymeDesign/legacy/v1/openspec/changes/add-mcp-bio-research/proposal.md)
- V1 `mcp-bio-research` 归档 design：[/home/grtresy/VSCodeRepo/EnzymeDesign/legacy/v1/openspec/changes/add-mcp-bio-research/design.md](/home/grtresy/VSCodeRepo/EnzymeDesign/legacy/v1/openspec/changes/add-mcp-bio-research/design.md)

## 维护建议

- 新增 Biomni 资料时，优先补官方来源，其次再补二级解读。
- 如果某条信息明显依赖“当前最新状态”，请在该条目下补充具体检索日期。
- 如果后续要下载 PDF、截图网页或保存代码片段，建议继续放在 `docs/Biomni/` 下，并在本文件里登记用途和来源。
