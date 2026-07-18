# Deferred: single-source HPC toolchain contract registry

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Problem evidence

当前同一个 AOX/HMM HPC toolchain identity 分散在多个 owner 中：

- `apps/mcp-hpc-runner/.../contracts/hpc_tool_contracts.json` 定义 runner 侧 tool、adapter、SIF locator、资源和输出合同；
- `packages/openzyme-tools/.../command_templates.py` 定义 Host 编译出的命令模板；
- `packages/openzyme-runtime/.../route_policies.py` 定义 control-plane `route_policy_id`、`runtime_packaging_id` 和 `toolchain_id`；
- `packages/openzyme-execution`、`packages/openzyme-engines`、`packages/openzyme-core` 分别重建同一 `toolchain_runtime_identity` 安全投影；
- AOX cutover collector/verifier 再维护 tool、template、toolchain id 与 prerequisite key 的闭集映射。

本 Goal 已做的局部正确性修复是：runner 以自己的 manifest 绑定 SIF locator，在同一 SSH login shell、实际 payload 前计算 digest；各信任边界只投影闭集字段；collector 将执行身份与 sealed prerequisite 精确比较。重复校验属于必要的 defense-in-depth，但重复的合同常量会产生长期漂移风险。若直接在本 Goal 中把这些定义合并，会同时改变 runner deployment、package dependency direction、route-policy ownership、历史 RunSpec 兼容和 evidence schema，属于大架构调整，因此只记录、不实施。

## Agent impact

- agent 应只看到稳定的领域能力、参数、受控 operation、已选择 backend 和可验证结果，不应推断 SIF path、SSH 命令或部署细节。
- harness 必须把“可用能力”“选择的工具链版本”“真实执行镜像 digest”“为何 fail closed”结构化呈现给 agent；不能靠 prompt 告知或隐藏 fallback。
- executor 仍只提交 `bio_tools.*`，不得自行选择 runner locator、覆写 SIF 环境变量或伪造 runtime identity。
- runner/operator 可以更新部署 locator，但任何会改变工具内容或合同的更新都必须产生新的 versioned identity，并在 agent 执行前显式暴露为 capability drift/prerequisite mismatch。

## Target invariants

1. 一个 versioned registry record 是 toolchain contract identity 的唯一语义 owner；其他层只消费生成的 typed projection，不手写平行常量。
2. registry 分离 logical tool contract 与 deployment binding：logical contract 可进入 route/approval identity，private locator 只留 runner deployment view。
3. caller 永远不能提交或覆写 runtime attestation；只有实际执行边界能签发 execution identity。
4. public projection 只含 schema、tool/adapter/template/toolchain/packaging ids、contract digest、execution mode/scope 和 image digest；不含 path、command、SSH target、storage URI 或 credential。
5. route selection、command compilation、runner validation、operation persistence 和 offline verification 必须能从同一 registry digest 证明一致。
6. registry 缺失、版本未知、projection schema 不兼容或 execution attestation 缺失时 fail closed；不得退回 native binary、mutable tag 或 caller command。
7. registry 不是新的顶层产品真状态；session、task、approval、operation 和 artifact 仍由 V3 control plane 持久化，registry 只提供 immutable capability/deployment contract。

## Proposed model

```text
HpcToolchainContract
  contract_id / version / contract_digest
  logical_tool_id / adapter_id / command_template_id
  parameter_schema / input_contract / expected_outputs
  runtime_packaging_id / toolchain_id
  resource_profile / failure taxonomy

HpcDeploymentBinding (runner-private)
  contract_digest / deployment_epoch
  entrypoint_kind / private locator
  bind policy / cluster capability requirements
  observed image digest / observation scope

ToolchainExecutionAttestation (runner-issued)
  schema / contract_digest / deployment_epoch
  tool + adapter + template + toolchain identities
  execution mode / attestation scope / image digest

PublicToolchainProjection
  closed safe subset of ToolchainExecutionAttestation
  no locator, command, host, scheduler handle or secret
```

推荐由一个不依赖 Host API、engine 或 runner implementation 的窄共享包拥有 logical schema 和 canonical digest；runner plugin 拥有 deployment binding。生成器从 logical record 产生 route-policy projection、command compiler input、runner manifest validation schema 和 verifier fixture。各信任边界仍独立验签，但共享 typed schema/version，不共享私有 locator。

## Migration plan

1. 盘点当前 JSON manifest、route policies、command templates、catalog entries、tests 和 AOX verifier 映射，生成逐字段 drift report；只读 shadow 阶段不改变执行。
2. 定义 `hpc_toolchain_contract@1` 与 canonical digest，并为现有 CD-HIT 4.8.1、MAFFT 7.525、HMMER 3.4、fpocket 等生成等价 logical records。
3. 增加生成/校验工具：CI 比较生成 projection 与现有手写定义；任何差异先作为 blocker，不自动覆盖生产文件。
4. 迁移 route-policy owner 和 Host command compiler 消费 typed registry；保持旧 IDs 不变，证明 operation digest、approval identity 和产物合同无漂移。
5. 迁移 runner manifest 为 deployment binding，启动时要求 logical contract digest 精确匹配；locator 仍留 runner 私有配置。
6. 将 adapter/engine/core 的重复字段 tuple 改为共享 schema validator，同时保留每层 closed reconstruction 和 negative corpus tests。
7. 让 campaign prerequisite 使用 logical `toolchain_id -> expected image digest`，execution attestation 同时证明 contract digest 和实际 image digest；对历史 bundle 使用 versioned legacy verifier。
8. 审计所有外部调用方和 operator tooling；确认无依赖旧 JSON/环境变量覆盖后，分别退役平行定义，禁止双写择优成功。

## Compatibility and rollback

- 第一阶段只 shadow-compare，不改变 runner command、route choice 或 operation identity。
- 旧 RunSpec/manifest 可由显式 legacy adapter 读取，但标记 legacy/non-cutover；不得在新 registry 失败时静默回退。
- IDs 与 digest 算法一旦进入 sealed bundle 即不可原地改语义；合同变化使用新 version 或 major schema。
- 回滚到旧执行实现不删除 registry records，也不重写历史 operation/artifact；只切换明确的 deployment epoch，并保持 NO-GO 直到重新证明。
- private locator 迁移不应改变 logical contract digest；镜像 bytes 改变必须改变 observed image digest 和 campaign prerequisites。

## Risks

- 共享包演变为新的全局上帝对象：限定其只拥有 immutable schema/digest，不拥有 session、scheduler、runner lifecycle 或 artifact locator。
- 代码生成掩盖差异：生成物必须可审阅、deterministic，并由 drift test 对照，不在运行时自动修复。
- deployment binding 泄露：registry public API 不加载 runner-private locator；错误和事件只返回 opaque identity。
- legacy 与新 registry 双源竞争：迁移阶段只允许 shadow compare；切换后 registry mismatch 直接失败，不选择“能跑”的一侧。
- schema validator 共享导致单点 bug：各信任边界继续 closed reconstruction，并保留独立恶意 extra-field/path/secret tests。

## Acceptance criteria

- CD-HIT、MAFFT、hmmbuild、hmmalign 从一个 logical contract record 可确定生成 route、template、runner validation 和 verifier expected identity，CI drift 为零。
- 改动任一 logical contract 字段都会稳定改变 contract digest，并在 Host/runner/operation/verifier 任一不匹配处 fail closed。
- 改动仅 private locator 不改变 logical contract digest，也不会进入 public operation、workspace、event、report 或 bundle。
- SSH execution attestation 能证明实际 SIF digest；Slurm 在 job 内 attestation 未实现前继续缺失并被 cutover verifier 拒绝。
- caller 注入 locator、runtime request、runtime identity、mutable image tag 或环境变量 override 的测试全部失败。
- 历史 bundle 仍由其 schema/version 的离线 verifier 复核；新 bundle 不接受 legacy projection。
- agent 能观察 capability unavailable、contract drift 和 prerequisite mismatch 的稳定结构化原因，但无需接触部署命令或路径。
