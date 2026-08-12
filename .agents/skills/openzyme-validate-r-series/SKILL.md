---
name: openzyme-validate-r-series
description: 在 EnzymeDesign 仓库中准备、执行或裁决全新的 OpenZyme AOX/HMM R 系列验证。用户要求就绪审计、qualification/admission、精确授权计划、获批 live rNN campaign、封存证据或 canonical GO/NO-GO 核验时使用。每轮必须从当前索引、active OpenSpec、public CLI、机器合同和 source-bound evidence 重新推导；默认只读，不实施修复、修改代码或提交。
---

# OpenZyme R 系列验证

本 skill 只是当前合同的薄路由器，不保存事故 runbook。Codex 在产品 runtime 之外编排当前公开能力；OpenZyme agent 自由决定科学计划、任务分解、tool 顺序、delegation、试错、报告时机与业务终态。

## 权限边界

只从用户当前消息和仍有效的精确批准确定权限，不从 goal、历史批准、工具成功或阶段完成推断下一层权限：

- 只读审计不运行 qualification、不写 admission/authority state、不启动 live；
- preparation 只执行当前合同明确覆盖的 non-live 动作，不消费 live authority；
- live 只在用户批准 current exact plan、identity、预算、effects 与 stop conditions 后执行；
- commit、successor rNN 和独立 repair 各自需要新的明确授权。

平台执行许可与业务授权相互独立；只按当前工具和仓库文档请求必要平台能力，不把平台拒绝改写为产品失败或扩大业务授权。

## 每轮重新发现

从仓库根目录完整读取：

- `AGENTS.md` 与 `docs/v3/README.md`；
- `docs/OpenZyme架构设计.md` 和当前阶段由 V3 索引指向的稳定文档；
- `openspec list` 指出的 active AOX/cutover change、相关 delta spec、design 与 tasks；
- 当前实现、owner/qualification registries、public API/CLI 与相应 `--help`；
- execution contract、typed public responses 和本轮 source-bound evidence。

历史 incident 只在 current source 明确引用时作为不可变证据读取，不为当前 tester 提供策略、命令或状态解释。文档、OpenSpec、CLI 与实现冲突时报告 exact drift；不得用本 skill 或历史值补齐。

所有可变值、能力、schema、文件名、命令参数和合法顺序都从 current source 与机器合同动态解析，不硬编码 rNN、identity、配置、次数、poll cadence、下一动作或 terminal 含义。

## 不可协商不变量

- exact authorization、identity、authority、budget、deadline 与 effect 范围必须闭合；
- 一次最多发出一条当前获批的 bounded mutation；只读观察次数由 agent 根据事实决定；
- unknown/external effect、authority/fencing drift 与 source identity drift 必须 fail closed；
- 只使用 current public surface 和 source-bound evidence，不读写 private SQLite 或调用 private service/runner/provider/HPC 接口；
- receipt/provenance append-only，不删除、覆盖、回填或把人类标签升级为 canonical fact；
- 不创建 hidden poll/retry、observer、automatic driver、replacement action、synthetic wakeup、automatic approval、response veto 或 fallback；
- runtime/tool/process terminal 只证明其 own boundary，不自动终结 task、attempt、slot 或 campaign；
- offline verifier/reducer 是唯一 GO/NO-GO 权威，prose、filename、exit code、fixture 或局部状态不能替代。

## 执行与裁决

每个阶段先形成最小可核验合同：当前 identity、权限、effects、机器能力、evidence sinks、bounds 与停止条件。只在合同闭合时执行一条获批动作；随后读取 typed response、canonical state/events 和 effect facts，由 Codex 自行选择下一步或停止。

严格区分封存观测、源码推论和未证实假设。保留 earliest source-bound typed cause、effect certainty 与 outer wrapper；不把 operation failure、非终态观察或命名错误自动升级成 campaign failure。

到达人工门、typed blocker、unknown effect、identity/authority drift 或证据能力缺失时，报告 exact identity、已发生/未发生 effects、预算变化、可复用性与所需决定，然后停止。只有 current offline verifier/reducer 的 canonical GO/NO-GO 才是正式终局；不得自动 repair、提交或开始下一 rNN。
