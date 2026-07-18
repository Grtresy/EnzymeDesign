# Deferred: runner-owned typed HPC command compiler and plan attestation

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 Goal 继续接收 Host 已编译的 canonical `bash -lc` payload，并由 runner 对已知 AOX templates 做严格 direct `apptainer exec`、single SIF token、entrypoint 与 shell segment validation，再插入 pre/post hash。这个局部方案对 trusted Host 闭集可以 fail closed，但仍是“解析并改写 shell text”。

未来让 runner 从 typed intent 自己编译 executable plan，会改变 Host-runner protocol、command-template ownership、RunSpec compatibility、launcher、attestation schema和调用方迁移，属于独立大架构调整。本轮只记录，不实施；也不以本提案放宽当前 strict parser。

per-run immutable SIF bytes 与 hash-to-open TOCTOU 由 `immutable-hpc-sif-execution-snapshot.md` 单独处理。本提案只负责 typed intent、runner-owned compilation、launcher plan与plan attestation。

## Current implementation evidence

1. `packages/openzyme-tools/src/openzyme_tools/command_templates.py` 当前在Host/package侧把领域参数编译成最终shell-oriented command template。
2. `apps/mcp-hpc-runner/src/mcp_hpc_runner/server.py::_bind_runner_toolchain_contract()` 能验证caller的tool/adapter/template与runner manifest匹配，但仍接收`RunSpec.command`作为最终执行形状。
3. `apps/mcp-hpc-runner/src/mcp_hpc_runner/ssh_runner.py::_command_with_toolchain_attestation()` 通过exact image token、`.sif`计数、正则、分隔符、字符串位置与entrypoint prefix识别一个direct `apptainer exec`，随后splice attestation shell text。
4. `apps/mcp-hpc-runner/src/mcp_hpc_runner/remote.py::make_remote_shell_command_with_env()` 再把argv、cwd与environment normalization包进remote `bash -lc`。验证语义、字符串serialization与最终shell解释跨越多层。
5. `apps/mcp-hpc-runner/tests/test_toolchain_attestation.py` 对当前闭集提供必要negative corpus，但每增加合法option ordering、wrapper、composite pipeline或tool template，都必须扩张shell parser与tests。

## Problem: parse-and-rewrite command grammar

当前strict parser没有已知可利用绕过，本提案也不把“架构脆弱”误报成现实漏洞。长期问题是：runner必须从已经失去类型信息的shell string反推image、entrypoint、segment与metacharacter语义，然后改写另一份shell string交给解释器。

- 合法quoting、option ordering、login-shell setup或wrapper演进可能被误拒绝，使agent看到的capability不稳定。
- parser与shell解释器对grammar的理解一旦漂移，可能出现“验证的结构”与“实际执行的结构”不同。
- 新工具或composite operation容易通过逐例放宽正则扩张attack surface，而不是由schema按构造限制。
- Host command template、runner manifest与attestation逻辑共同拥有command identity，长期易产生多源漂移。
- runner只能在字符串中寻找private locator，难以证明validation、approval和launcher消费的是同一个canonical plan。

## Impact on agent autonomy and trust

- agent 应提交领域工具与typed参数，不应猜测shell quoting、separator或runner parser接受的字符串形状。
- harness 应结构化展示supported contract/version、normalized plan summary、resource/output约束与stable compiler error，而不是泄露raw command。
- compiler必须忠实实现approved intent，不添加隐藏fallback、额外network step、native binary downgrade或未批准mount。
- `EXECUTION_PLAN_UNSUPPORTED`、`EXECUTION_ARGUMENT_INVALID`、`EXECUTION_PLAN_DIGEST_MISMATCH`等错误应允许agent调整策略，但不能要求agent修复runner-private shell。
- 相同typed intent、contract与deployment输入应得到deterministic plan digest；operator内部实现变化若改变语义，必须显式产生compiler/contract drift。
- command compilation不能成为固定agent策略或拓扑；它只把已批准能力意图映射到世界真实执行约束。

## Non-goals

- 不改变顶层session/task/approval/controlled-operation/artifact真状态，也不让compiler自动完成task。
- 不改变AOX科学workflow、motif规则、provider选择或GO reducer。
- 不把任意bash构造成安全AST。registered tools只支持versioned typed plans；无法表达的shell workflow显式unsupported。
- 不让caller选择runner executable、private locator、SSH target、mount root、credential或attestation字段。
- 不在本提案中解决SIF bytes不可变与hash-to-open TOCTOU；compiler只能消费snapshot提案提供的sealed handle，不能自行宣称它不可变。
- 不把logical contract registry、deployment binding与compiler合并为一个全局上帝对象。
- 不在第一阶段强制覆盖Slurm composite scripts；没有node-side typed launcher与plan attestation时，Slurm维持旧scope。

## Target invariants

1. registered HPC tool的caller只提交versioned `TypedToolInvocation`；不得提交最终shell、executable、SIF locator或attestation request。
2. runner根据exact logical contract digest、deployment binding与compiler version生成`RunnerExecutionPlan`；unknown field/version、unsupported option或identity mismatch fail closed。
3. validation与launcher消费同一个immutable plan object/canonical bytes，不允许“验证string A、执行string B”。
4. executable、subcommand、fixed options、entrypoint、env allowlist、cwd、bind policy、resource profile与output contract均由runner contract/compiler拥有。
5. caller参数保持argv element语义，不经过shell interpolation。需要pipeline/redirection时使用versioned composite process graph，不放宽raw shell。
6. staged input/output只以authorized handles进入compiler；runner映射private path，Host/sandbox不提交remote path。
7. plan必须引用approved operation digest、logical contract digest、deployment epoch和exact snapshot/packaging handle；这些字段共同进入plan digest。
8. launcher仅执行已sealed且digest复核通过的plan；不能在plan failure后选择sibling backend、native binary或legacycommand。
9. plan attestation由runner authority在launch/completion边界签发，绑定compiler digest、plan digest、snapshot binding、execution mode与outcome；stdout不能自声明。
10. public plan summary/attestation不含raw command、path、env value、UID、SSH/Slurm config或secret，只含closed safe ids/digests和bounded resource/output facts。
11. compiler不是新的route-policy或approval owner。approved intent漂移必须回到Host产生新operation/approval，runner不能“修正”意图。
12. 历史RunSpec/receipt按原version验证；新@2 plan缺失时不静默回退legacy parser。

## Proposed ownership and object model

```text
TypedToolInvocation (Host -> runner)
  schema_id / operation_id / approved_operation_digest
  tool_id / adapter_id / logical_contract_digest
  typed arguments / input handles / expected output handles
  requested resource class / placement identity

CompilerContractView (runner-owned immutable input)
  logical_contract_digest / command_template_id
  executable + subcommand / allowed option schema
  entrypoint / argument schema / env allowlist
  bind policy / resource policy / output contract
  runtime packaging requirements

RunnerDeploymentBinding (runner-private)
  contract digest / deployment epoch
  executable identity / packaging or snapshot resolver
  login environment policy / target capability

RunnerExecutionPlan
  schema_id / plan_id / compiler_id + compiler_digest
  operation + contract + deployment identities
  executable argv / typed mounts / env projection / cwd
  snapshot lease or packaging handle / resource limits
  output declarations / failure taxonomy / plan_digest

LauncherReceipt (runner-private)
  plan_id / plan_digest / resolved executable identity
  resolved snapshot binding / process identity / timestamps
  exit + output validation facts

ExecutionPlanAttestationProjection
  schema / tool + adapter + template ids
  contract + compiler + plan digests
  snapshot/packaging digest / execution mode + scope
  bounded outcome / runner contract digest
```

compiler拥有pure deterministic mapping，不拥有session、approval、job lifecycle或artifact bytes。launcher拥有process mechanics但不能修改sealed plan。registry提供logical schema，deployment view提供private executable/packaging，snapshot service提供sealed image handle。

## Typed compilation and launcher protocol

1. runner接收`TypedToolInvocation`，closed-validate schema、operation/contract identity、typed params、authorized handles与resource/output bounds；caller extra/private field直接拒绝。
2. runner解析exact `CompilerContractView`和deployment epoch，不根据“当前能跑什么”选择sibling tool/backend。
3. compiler把typed参数映射为argv element。option ordering、boolean flags、repeated values、input/output handles与entrypoint全部由versioned schema决定。
4. image字段只能接收snapshot service签发的sealed handle或明确versioned packaging handle；不能接收path/string locator。compiler把handle identity纳入plan digest。
5. mount使用typed `{source_handle, target, mode, purpose}` record，target normalizes/beneath allowlist；environment只允许contract key，value来自runner deployment或typed non-secret input。
6. 若单process不能表达需求，使用`CompositeExecutionPlan`显式列process nodes、argv和pipe/file edges；禁止任意shell fragment、redirection string或command substitution。
7. compiler canonical-serialize plan并签发`plan_digest`；validation与launcher共享read-only typed plan，不重新从display string解析。
8. launcher在execution前复核plan digest、approval binding、snapshot lease、resource policy和output destinations，再以argv/execve等无shell路径启动。平台必须使用login shell时，由runner生成固定不可参数化wrapper，并把wrapper digest纳入compiler identity。
9. completion后launcher验证declared outputs与exit/failure taxonomy，生成private receipt；runner从receipt closed-project public attestation。

示意单process plan：

```text
ApptainerExecutionPlan
  executable = /usr/bin/apptainer
  argv = [apptainer, exec, --cleanenv, <sealed_snapshot>, mafft, --auto, <input_handle>]
  mounts = typed allowlisted records
  environment = contract-owned allowlist
  shell = none
```

## Relationship to adjacent proposals

- `single-source-hpc-toolchain-contract-registry.md` 回答logical contract的唯一owner。compiler消费其typed projection；registry不拥有per-run plan或launcher lifecycle。
- `immutable-hpc-sif-execution-snapshot.md` 回答实际SIF bytes。compiler只引用sealed snapshot lease/digest；它不能通过plan digest弥补mutable locator TOCTOU。
- compiler可以先shadow生成plan并与现有Host template做semantic diff；snapshot也可独立shadow。任一单独落地都不能宣布完整@2 execution identity。
- 组合切换时plan digest绑定snapshot id/digest/fencing；最终attestation同时绑定contract、compiler、plan和snapshot，且launcher receipt证明实际消费该plan/snapshot。
- 若registry尚未完成，可使用冻结runner manifest投影作为临时CompilerContractView；需要drift tests，不能形成永久第三套常量。

## Migration plan

1. **冻结legacy grammar。** 固定当前AOX direct Apptainer parser、negative corpus和@1 attestation scope；只做安全修复，不再为新功能任意扩张shell grammar。
2. **盘点command ownership。** 对Host command templates、runner manifest、route policy、RunSpec、remote wrapper与verifier做字段/option/entrypoint drift report。
3. **定义typed invocation与plan schemas。** 固定canonical serialization、compiler identity/digest、single-process和composite-plan边界；先不改变执行。
4. **shadow compiler。** 对CD-HIT、MAFFT、hmmbuild、hmmalign从现有typed inputs生成plan，与legacy template在argv、inputs、outputs、resources和packaging上semantic compare；差异是blocker，不自动选一侧。
5. **launcher canary。** 对一个allowlisted SSH tool执行shadow plan，仍使用当前approved packaging；比较真实argv、output和failure mapping。一个operation只允许一个实际launcher。
6. **接入immutable snapshot。** 将plan image field从legacy locator切到active snapshot handle，把snapshot lease/digest纳入plan与attestation；未完成snapshot的target不能声称组合@2。
7. **切换Host-runner protocol。** registered tools不再发送最终command，只发送typed invocation、logical contract与authorized handles；breaking change显式发布major schema。
8. **迁移projection/verifier。** adapter、engine、core与cutover verifier closed-reconstructplan attestation；extra field、path、secret、mode与digest drift均fail closed。
9. **扩展composite/Slurm。** 逐contract增加typed graph和compute-node launcher；无法证明node-side plan的Slurm继续legacy/non-cutover。
10. **退役parser。** 审计外部调用方后停止new registered tools的legacy RunSpec writer，删除active shell parser/rewrite；历史reader与fixture永久versioned保留。

## Compatibility and rollback

- legacy RunSpec与typed invocation使用显式schema/route，不能在typed compile/launch失败后静默回退legacy command。
- shadow阶段只有legacy或typed其中一个实际执行；另一侧只产生不可用于GO的comparison artifact。
- IDs和digest算法进入sealed bundle后不原地改语义；compiler/plan变化发布新version或major schema。
- canary回滚关闭typed route并让要求@2的campaign保持NO-GO，不把旧parser升级解释为typed proof。
- 历史@1 bundle继续由legacy verifier按原scope验证；@2 verifier拒绝缺compiler/plan/snapshot binding。
- Host API、engine和operator调用方在确认无旧schema依赖前保留显式legacy adapter；不允许双写择优成功。

## Security, correctness and operability risks

- **compiler成为高权限通用shell：** schema只表达registered tools；raw shell、arbitrary executable、path/env/mount escape默认不可表示。
- **compiler/launcher语义分叉：** 两者消费同一sealed typed plan；launcher不得重新parse display command或补默认option。
- **argument injection：** property tests覆盖spaces、quotes、semicolon、`$()`、newline、Unicode和leading dash，证明它们保持单一argv element或被schema拒绝。
- **mount/env泄露：** source只接受authorized handle，target与key allowlist；public error不回显private resolution或secret value。
- **错误的determinism：** canonical plan排除timestamps/private path，但包含所有语义字段；compiler version和deployment epoch显式进入identity。
- **共享registry变上帝对象：** registry只拥有immutable logical schema；compiler拥有mapping，runner deployment拥有private binding，launcher拥有process lifecycle。
- **composite graph复杂度：** 初始只支持single process；pipe/file edge闭集逐步扩展，禁止为了覆盖罕见workflow开放bash escape hatch。
- **迁移双执行：** shadow mode严格禁止第二次external launch；comparison基于plan，不通过同时运行两个后端验证。
- **性能：** compilation应为pure/bounded并可缓存contract view，但plan必须按operation/snapshot重新digest；cache key不能遗漏approval或lease identity。

## Test strategy

### Unit and property tests

- typed invocation与plan canonical digest稳定；field reorder不变，任一语义字段变化必变。
- unknown/extra/private field、wrong schema/contract/compiler/deployment、unsupported option与resource/output drift fail closed。
- shell metacharacters保持argv literal，不发生interpolation；raw shell/executable/path/env/mount注入不可表示。
- handle解析、mount target、cwd与output path使用normalized beneath/allowlist规则。
- single-process/composite plan schema互斥，graph cycle、undeclarededge或unbounded process count拒绝。

### Differential and negative corpus tests

- 每个现有registered contract都有legacy template与typed plan semantic golden diff；只比较argv语义、inputs/outputs/resources，不比较private display path。
- 当前parser negative corpus转为typed invocation negative corpus，证明安全约束不因去掉parser而丢失。
- caller注入command、locator、alternateentrypoint、extraSIF、HOME/env rebinding、bind override、nested shell和attestation字段全部失败。
- compiler/launcher plan bytes不一致、plan digest tamper、stale snapshot lease和wrongoperation digest全部在external launch前失败。

### Integration and live tests

- CD-HIT、MAFFT、hmmbuild、hmmalign分别通过typed plan执行真实SSH positive，output与declared validation一致。
- runner audit证明launch argv来自sealed plan，不读取caller command；private command只保留受保护diagnostics。
- snapshot组合测试证明plan引用的digest/lease正是Apptainer实际消费的protected object。
- failure mapping覆盖binary unavailable、invalid params、timeout、nonzero exit、missing output与launcher crash，不产生partial trusted attestation。
- Slurm只有compute-node内typed launcher/receipt完成后通过，submit-onlyscript不满足@2。

## Acceptance criteria

- registered AOX tools从typed invocation到launch不解析、拼接或执行caller shell text；实际argv来自sealed `RunnerExecutionPlan`。
- executable、options、entrypoint、mount/env、resource和output合同均可从logical contract+compiler确定，CI drift为零。
- plan digest精确绑定operation、contract、compiler、deployment和snapshot/packaging handle；任一篡改在launch前失败。
- shell injection/property corpus全部通过，合法typed参数不因quoting差异被误拒绝。
- Host/SDK不再发送private locator或finalcommand；public projection无raw command/path/env value/secret。
- typed route失败不回退legacy/sibling/native backend；agent得到稳定、结构化且可行动的compiler failure事实。
- legacy外部调用方审计完成后active parser writer退役，历史@1 reader仍可复核旧bundle。
- 与snapshot的组合验收证明launcher receipt、plan digest和snapshot attestation引用同一active lease/digest；缺任一侧时只得NO-GO，不产生两份竞争的权威identity。
