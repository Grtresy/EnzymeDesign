# Versioned Workflow Knowledge Packs

本目录保存调用方可显式绑定的领域 workflow manifest。它们是版本化 knowledge/capability contract，不是顶层 workflow graph，也不是按用户文本自动命中的 prompt recipe。

稳定规则：

- selection ref 必须是完整的 `workflow:<id>@<semver>#sha256:<manifest-digest>`；只给名称、版本或自然语言都不构成选择。
- manifest digest 覆盖除 `content_sha256` 字段外的完整 canonical JSON；`knowledge_refs` 同时固定 `doc_id`、文档版本和内容 digest。
- caller 通过结构化 `workflow_refs` 选择；`skill_keys` 仅是 public compatibility input，message ingress 必须先用 Distribution-owned exact registry 归一化，不能作为 canonical authority row。模型调用 `skill.load`、关键词匹配、task subject 和 delegation instructions 都不能激活 workflow。
- message ingress 为每条 root request 原子写 `WorkflowAuthorityBinding@1`（包括显式空选择）与当前 signal 的 `RuntimeSignalAuthorityLink@1`；runtime 只从 exact link/binding/epoch 恢复，选择不跨消息 sticky/union，普通 protocol payload 和 drain/operator 参数都不授予或扩大 workflow authority。
- master delegation 只能选择 caller 当前 binding 的显式、无重复子集，原子写 child binding、manifest snapshot 与 recipient signal link；protocol、approval、continuation 和 teammate-result wake 只传播已验证的既有 causation，不扫描 latest/all conversation。
- unknown ref、manifest/document drift、缺少 requirement 均 fail closed。不得猜测新版本、回退到近似 SOP 或隐藏工具来制造可执行路径。
- 每个 current manifest 固定 `public_contract=file_workspace_public@2`，并要求 turn 从已 pin 的 Session/Host projection 原样提供 release、Extension bundle、DeclaredToolCatalog、capability binding、affordance snapshot 与 workspace backend 六类 exact identity；manifest 不硬编码部署值，也不允许 runtime 自行补默认值。
- workflow 只提供领域知识与真实约束。agent 仍负责选择步骤、工具顺序、重试策略和是否需要澄清；安全、权限、预算、数据与 provenance 边界由 harness 强制。
- Distribution-owned `WorkflowRegistryResolverPort` 是 selection owner：Standard 注册显式空 registry，EnzymeDesign 注册采用的 exact versioned refs；resolver 验证 ref、manifest/document digest、role/requirements 和 epoch，并把结构化结果交给 Kernel context builder。prompt 中的 manifest path 只说明 provenance，不是 `docs.read` 地址，也不构成 authority。
- `DocumentRegistry` 是 knowledge document owner：`docs.search` / `docs.read` 只接收 manifest `knowledge_refs` 中的 `doc_id` 或登记 path。把 `workflow:` ref 或 `*.workflow.json` 误送给 `docs.read` 会得到明确 owner hint，不会搜索、猜测或加载替代 manifest。

当前 manifest：

- `generic-sandbox-execution.workflow.json`：领域无关的 sandbox authoring 与 Host-supervised execution 约束。
- `aox-hmm-live.workflow.json`：`2.0.0` correctional breaking contract，同时 pin 主 SOP、`aox_motif_rule_score@1` 与真实序列/CD-HIT 图合同；固定 exact-14 NCBI aggregate 向 13-record HMM model reference 与 AAB-only coordinate reference 的显式拆分、HMMER → score-filter → conditional UniProt → identity-preserving join、`aox_known_positive_probe@2`、required provider quorum、artifact-derived healthy-empty omission/skip receipt 与科学 fail-closed 条件，但不固定 agent 的命令顺序或研究策略。fixture/simulation 不具备 live cutover 资格。

修改 manifest 或其引用文档时，必须重新计算并更新对应 digest、补充 drift/requirement 回归，并同步更新架构文档。不得只改正文而保留旧 digest。
