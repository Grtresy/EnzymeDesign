# Versioned Workflow Knowledge Packs

本目录保存调用方可显式绑定的领域 workflow manifest。它们是版本化 knowledge/capability contract，不是顶层 workflow graph，也不是按用户文本自动命中的 prompt recipe。

稳定规则：

- selection ref 必须是完整的 `workflow:<id>@<semver>#sha256:<manifest-digest>`；只给名称、版本或自然语言都不构成选择。
- manifest digest 覆盖除 `content_sha256` 字段外的完整 canonical JSON；`knowledge_refs` 同时固定 `doc_id`、文档版本和内容 digest。
- caller 通过结构化 `skill_keys` 选择；模型调用 `skill.load`、关键词匹配、task subject 和 delegation instructions 都不能激活 workflow。
- master delegation 持久化 selection ref 与 manifest snapshot；teammate restore 重新对照 authoritative registry，并在 provider call 前验证实际 role、engine capability 和 tool surface。
- unknown ref、manifest/document drift、缺少 requirement 均 fail closed。不得猜测新版本、回退到近似 SOP 或隐藏工具来制造可执行路径。
- workflow 只提供领域知识与真实约束。agent 仍负责选择步骤、工具顺序、重试策略和是否需要澄清；安全、权限、预算、数据与 provenance 边界由 harness 强制。

当前 manifest：

- `generic-sandbox-execution.workflow.json`：领域无关的 sandbox authoring 与 Host-supervised execution 约束。
- `aox-hmm-live.workflow.json`：AOX/HMM live cutover 的严格科学 prerequisite、provider/HPC route 与 deliverable contract；fixture/simulation 不具备 live cutover 资格。

修改 manifest 或其引用文档时，必须重新计算并更新对应 digest、补充 drift/requirement 回归，并同步更新架构文档。不得只改正文而保留旧 digest。
