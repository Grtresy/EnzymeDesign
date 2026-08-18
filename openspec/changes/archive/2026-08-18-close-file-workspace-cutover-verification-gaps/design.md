## Context

本 change 收口十四个连续的 file/revision cutover changes。当前代码已经把主要产品路径迁移到 agent Git workspace、published revision、workspace job、file-native scientific deliverable 和 file-workspace public contract，但任务完成状态与可执行证据之间仍有实质差距：

- `apps/mcp-hpc-runner` 的 closed cancellation receipt 不包含 `receipt_id`，Host 和 domain 却要求该字段并把它纳入 digest；因此当前 cancel 成功响应不存在可被三方共同接受的形状。
- runner 的 dispatch replay 直接返回本地 handle JSON，没有重新执行 exact-handle validator。
- `migration_assets._verify_final_schema()` 没有读取 `deployment_schema_state.removal_receipt_digest`，也没有验证 offline ledger；被篡改或根本不存在的 removal proof 仍可通过启动。
- workspace publication 在 dispatch/reconcile 边界捕获任意异常后只保留 `in_doubt` 结果，丢弃具体原因；agent Git workspace recovery 把任意 observation exception 永久分类为 Git corruption；revision-path handoff cleanup 捕获任意异常后静默返回。
- `FailureObservation` 已经提供 failure class、recoverability、effect certainty、retry eligibility 和 private diagnostic digest，但当前 API exception 与多个业务 service 没有统一消费这一语义。
- `apps/mcp-hpc-runner` 当前是零依赖包；`openzyme-domain` 同样无第三方或 workspace 依赖，因此可以提供一个窄、可执行的 wire contract，而不把 Host/core/runtime 引入 runner。
- 当前 final SQLite bootstrap 同时具有 `fresh_install_complete`、`offline_removal_complete` 两种状态以及 `legacy_removal_ledger`，但两种 proof 尚未形成显式 tagged union。
- 本设备将按用户决定重建为 fresh install。旧 OpenZyme 数据、运行记录、legacy storage、旧 receipts、缓存和备份最终全部删除；Git/OpenSpec 历史、源码、current repository Git/LFS truth 和非 OpenZyme 数据不属于删除 authority。

十四个目标 changes 仍保持 active；另有 `establish-v3-executable-architecture-qualification` 等独立 active changes。qualification 是本收口的验收依赖，但不会被不加区分地并入十四项归档批次。

## Goals / Non-Goals

**Goals:**

- 让规范、代码、测试、部署状态和 source-bound receipts 对 file/revision/publication/job 单一产品真值达成一致。
- 建立详细、可操作且不会泄密的统一失败诊断，保留最早具体 cause 与真实 effect certainty。
- 让 HPC cancellation、dispatch replay、restart 和 reconciliation 共享可执行 wire contract，并消除三份手写 schema 漂移。
- 让 fresh install 和 offline removal 通过带类型的 proof 分支接受同一严格启动 verifier；所有拒绝都只读、fail-closed、可诊断。
- 纠正十四个 changes 中被当前证据反证的完成标记，重建行为级 qualification 和最终 clean-HEAD receipts。
- 在软件 gate 全部通过后，以精确清单、quiescence 和零残留验证完成本设备 OpenZyme fresh-install 重建。

**Non-Goals:**

- 不恢复 generic artifact catalog、runner staging、declared/expected outputs 或 artifact-era compatibility mode。
- 不删除 authority、approval、lease/fencing、effect certainty、idempotency、provenance、secret/path 或 HPC supervisor 边界。
- 不把 LangGraph/LangChain、runner journal、Git commit、文件树或诊断日志提升为新的顶层产品真状态。
- 不进行与本收口无关的全仓模块拆分；超大模块只抽取本 change 必需的 contract、verifier 和 error mapping。
- 不运行 live provider、真实 HPC、外部消息、push 或 PR。
- 不把 test double 的成功、名称扫描、枚举成员或 green focused subset 描述为完整架构验收。

## Decisions

### 1. file/revision/publication/job 是唯一当前产品合同

当前规范按以下所有权解释：

- agent workspace 的可变私有真相由 exact Git workspace generation 与 clean/dirty observation 持有；
- shared work product 只有显式 published revision 才成为团队共享真相；
- HPC execution 绑定 exact revision、workspace、cwd、command、target、lease/fence 与可靠 handle；普通结果文件留在 executor workspace，由 agent 自主检查、commit 和 publish；
- scientific deliverable 绑定 published revision/path/blob/LFS identity，并由显式 adoption/finalization 决定科学产品状态；
- task terminal truth 仍只能由显式 `task.finish` 或已文档化机械迁移写入。

`AGENTS.md`、`docs/OpenZyme架构设计.md`、`docs/v3/03-capability-engines.md`、`docs/v3/04-public-interfaces.md`、`docs/v3/07-runtime-hpc-reliability.md`、file-workspace migration 文档与 harness audit 必须同时更新。文档中不得再要求 artifact catalog staging 或 `expected_outputs`，但需要明确 source revision preparation、LFS closure、credential、runner handle、declared command/cwd 和 Host supervision 仍是强约束。

未采用的方案是恢复 artifact catalog/expected-output pipeline。该方案会重新引入已经删除的 domain/storage/public surface，并使 C9-C14 及 fresh-install 决策整体失效。

### 2. 用一个收口 change 管理共同契约，并恢复原任务的事实性

新增 `close-file-workspace-cutover-verification-gaps` 作为共同设计、规格和验收 owner。实现阶段生成一个机器可读的 evidence-gap registry，至少包含：

- owning change 与原 task identity；
- 当前反证及 source location；
- 恢复为未完成的理由；
- 本 change 中的 repair task identity；
- 重新完成所需的 authoritative evidence；
- 最终 evidence digest 与 source identity。

只把已被反证的 checkbox 恢复为 `[ ]`，并附上本 change 的 gap identity；真实完成项保持不变。旧 receipt 或测试路径仍可作为历史说明，但必须标记 `superseded`，不能满足当前完成条件。

未采用的方案是把十四项全部清零或只在新 change 中记录问题而继续保留虚假 `[x]`。前者丢失真实工作，后者继续让状态接口报告错误事实。

### 3. dependency-free domain module 是 workspace job wire contract 的单一可执行来源

在 `openzyme-domain` 中建立窄的 workspace job wire module，包含：

- canonical JSON 编码与 digest 规则；
- exact-object validator；
- `ExternalJobHandle`、cancellation intent、cancellation receipt 及必要 observation/reconciliation wire shape；
- 稳定 schema version 与字段集合；
- 从 mapping 解析和生成 mapping 的单一入口。

`apps/mcp-hpc-runner` 增加对零依赖 `openzyme-domain` 的 workspace dependency，只导入该窄 module。Host adapter 和 domain records 使用相同 parser/serializer；runner 不导入 core/runtime/execution，也不获得 control-plane repository 或产品状态写 authority。

这比新建一个只承载数个 dataclass 的第十一个 workspace package更有界，也比把 validator 复制到 runner/Host/domain 后用测试比较三份实现更可靠。若未来 runner 需要脱离 OpenZyme 单独版本化，再把该纯 module 提取为独立 wire package；本 change 不提前承担该发布复杂度。

### 4. 以 `FailureObservation@2` 为公开安全诊断真相，以 private record 保留完整原因

演进现有 `FailureObservation`，而不是并行建立第二套 failure FSM。当前公共 schema 升级为 `failure_observation@2`，新增：

- `component`、`operation`、`phase`；
- typed `identities`，只允许当前调用方有权观察的 session/task/lane/agent/workspace/execution/operation/dispatch/publication 等 identity；
- `mutation_applied: true | false | unknown`；
- `fallback_performed: false`，当前合同不允许隐藏 fallback；
- 有界、脱敏的 `cause_chain`，每层只保留 stable type/code/safe message/stage；
- `diagnostic_id`，供 operator 查找 private record；
- 明确的 operator/agent next action。

private diagnostic record 以 `diagnostic_id` 为键，保存完整 exception type/message/traceback、`__cause__`/`__context__`、errno/return code、bounded stdout/stderr、内部 path/handle（按私有权限）、component source 与 correlation identities，并计算 immutable digest。公开 API、tool result、event 和 projection 不返回 private payload，只返回 diagnostic identity 和安全摘要。

typed boundary exception 持有 observation draft 和原始 `__cause__`。捕获规则是：

1. 只在能增加语义的边界捕获；
2. 先判断实际执行阶段，再确定 effect certainty；不得从 exception class 猜测外部效果；
3. 持久化 private diagnostic 和 public observation；
4. 使用 `raise TypedBoundaryError(...) from exc`，或在已经进入 durable FSM 时返回携带 diagnostic identity 的 typed terminal/in-doubt state；
5. 不自动改写请求、不选择替代 plan、不用新 idempotency key 重试。

主要分类如下：

| 已证明阶段 | effect certainty | retry policy | 行为 |
|---|---|---|---|
| validation/authority/pre-dispatch 失败 | `no_effect` | `terminal` 或显式修正后新请求 | 详细拒绝，不产生外部 effect |
| 外部入口已调用但 acceptance 未知 | `dispatch_in_doubt` | `reconcile_required` | 只 reconcile exact identity，禁止 replacement |
| read-only observe/reconcile 暂不可用 | 保留既有 effect certainty | 同一 identity 的 bounded observe/reconcile | 不伪装为 corruption 或 terminal |
| 已知 effect 成功但本地 materialization/cleanup 失败 | `effect_known`/`terminal_known` | 修复本地记录或 cleanup | 不把 effect 成功回退为 no-effect |
| 内部 invariant/programming failure | 按阶段决定 | 默认 `terminal` | 显式 `internal_invariant_violation` 并告警，不走业务 fallback |

public sanitizer 必须过滤 secret/token/credential、未授权绝对路径、raw remote handle、hostile backend text 和超长 payload；同时保留 stable error code、阶段、允许公开的 identity、expected/observed digest、计数和操作建议。测试同时证明“足够诊断”和“不会泄密”。

### 5. HPC cancellation 和 replay 总是重新验证 exact identity

closed cancellation receipt 的 canonical payload 包含：

- schema version；
- `receipt_id`；
- `cancellation_id`；
- `handle_id`；
- `cancellation_requested=true`；
- `terminal_settlement_proven=false`；
- `backend_receipt_digest`；
- `created_at`；
- 覆盖前述全部字段的 `receipt_digest`。

runner protected wrapper、runner service、Host adapter 和 domain record 全部调用同一 parser。任何 missing/extra field、identity drift、digest drift 或 schema drift 都产生带详细 cause 的 typed error。cancel receipt 只证明 cancellation request 已被 backend 接受，不证明 job terminal；后续仍需 exact-handle observation。

dispatch 发现已有 handle record 时，必须以当前 RunSpec/dispatch intent 调用 canonical handle validator 后再返回。cancel/reconcile/observe replay 同样从 durable bytes 重新验证，不信任文件名命中。response loss 后只允许查询 exact dispatch/cancellation marker；禁止 replacement submit/cancel。

### 6. publication、workspace recovery 和 cleanup 使用不同失败语义

workspace publication 在 remote create-ref 或 read-ref 边界失败时：

- 保持由 dispatch phase 得出的 `NO_EFFECT` 或 `DISPATCH_IN_DOUBT`；
- 记录具体 transport/provider/invariant cause；
- durable execution/event 保存 diagnostic identity；
- public state 继续要求 reconcile exact ref，不暴露 raw credential 或 remote text。

agent Git workspace recovery 只对明确的 Git integrity/identity observation 结果使用 `CORRUPT_GIT_DIRECTORY`。volume identity drift、Git command 的确定性 corruption、observation infrastructure unavailable、permission/configuration failure和 unexpected internal error采用不同 typed blocker/failure；未知异常不得永久改写 agent/workspace 为 corrupt。

revision-path handoff cleanup 返回结构化结果并检查 return code。若主操作失败且 cleanup 也失败，保留主 cause，并把 cleanup failure 作为有序 secondary cause；若主 effect 已成功而 cleanup 留下临时文件，则返回/记录 `cleanup_incomplete`、`mutation_applied=true` 和精确 temporary identity，要求显式 cleanup，不谎报整体 no-effect。

### 7. deployment proof 是显式 tagged union

`deployment_schema_state.removal_state` 决定 proof 类型，verifier 不使用宽泛“complete state set”跳过分支验证。

**Fresh install proof**

`FreshInstallBootstrapReceipt@1` 是由 final migration source 确定性计算的 canonical payload，至少绑定：

- final schema generation 与 manifest digest；
- current migration id set/digest；
- `fresh_install_complete` mode；
- legacy schema/storage initialization 均为 false；
- deterministic empty legacy object-set digest；
- bootstrap contract/source digest。

receipt 不包含运行时随机时间或 deployment-local secret，因此 SQL seed 与 Python verifier 可独立重算同一 digest。fresh 分支要求 metadata digest 精确等于重算值、final schema manifest 精确一致、forbidden schema scan 为空、foreign-key closure 为空，并拒绝把任意 offline ledger 当作 fresh proof。

**Offline removal proof**

offline 分支要求 `removal_receipt_digest` 精确命中唯一 `legacy_removal_ledger` row，并验证：

- row 为 `complete` 且 `completed_at` 非空；
- schema generation、manifest digest 与 metadata/current binary 一致；
- historical receipt、database/storage backup、quiescence 和 expected object set 均为合法 digest；
- item rows 与 expected/removed/already-absent/error set digests 和 byte totals 闭合；
- error set 为空，所有 expected item 均为 deleted 或 already absent；
- canonical row digest 与 metadata 完全一致。

任何查询错误、缺行、多行、字段/digest/count drift 都抛出 `SQLiteSchemaMismatchError` 的 typed successor，包含 error code、phase、expected/observed facts、`mutation_applied=false` 和 offline operator action，并保留原始 sqlite cause。`_verify_final_schema` 和所有 proof 查询不得执行 INSERT/UPDATE/DDL；测试用 `total_changes`、transaction state 和数据库 bytes/digest 证明拒绝路径无 mutation。

### 8. 本设备 fresh-install reset 是独立、不可逆的 operator phase

reset 不复用 offline removal ledger，也不把事后扫描伪装成历史 deletion receipt。流程产生一份新的 `DeviceFreshInstallResetReceipt@1`，绑定最终 source identity、精确 target inventory、quiescence evidence、每个删除结果与删除后零残留扫描；它是当前维护证据，不进入产品工作流或科学真相。

删除 inventory 只能由当前配置、进程参数、数据库 locator、已知 OpenZyme state roots 和已有 receipts 逐项解析。每个 target 记录：

- canonical absolute path 或数据库 identity；
- target kind 与 owner evidence；
- inode/device/size/digest（适用时）；
- 为什么属于 OpenZyme；
- 是否位于 Git/OpenSpec/source/current repository Git-LFS exclusion 下；
- 删除方式、可恢复性和删除后验证方式。

开始删除前必须证明相关 Host/runner/UI/worker 无存活 owner，数据库无写 transaction，且 inventory 没有 unresolved target。命令使用显式绝对路径，不使用 glob、`~`、`$HOME`、宽泛环境变量或递归 workspace root。先删除已解析的旧 DB/runtime/storage/receipts/cache/backups，随后从空位置启动 final schema，让其生成 fresh bootstrap proof。最终扫描证明旧 paths、legacy schema/storage markers 和旧 process owners 均为零。

用户要求备份也删除，因此 destructive phase 一旦完成没有数据 rollback；回滚只存在于删除前。若任何 target owner 不确定，只暂停该 target，其余已证明 target 可继续，但不能签发“全部旧记录已删除”的 reset receipt。

### 9. qualification 必须证明真实关系，而不是只证明测试文件存在

收口矩阵至少包含：

- runner/Host/domain wire round-trip、missing/extra field、tampered digest、replay drift；
- direct 与 Slurm dispatch/observe/cancel/reconcile 的 response loss、restart 和 no-replacement oracle；
- authority/lease/fence stale callback 和 concurrent owner；
- publication pre-effect、dispatch-in-doubt、exact-ref reconcile、cause preservation；
- Git workspace missing/corrupt/infrastructure unavailable/internal invariant 分类；
- cleanup primary/secondary failure 与 post-effect residue；
- fresh/offline proof success，以及 missing/tampered/duplicate/incomplete/mismatched/foreign-key cases的只读拒绝；
- scientific adoption/finalization/AOX fixed bundle 的直接 service tests；
- UI state/view/controller 对 file/revision/publication/job 和 stale contract 的行为测试；
- production composition、declared external ports、restart/fencing/reconciliation 和 cleanup boundaries。

architecture invariant registry 的 `boundary_relations` 和 `external_ports` 必须对应真实 production owner、adapter 和 test id；qualification runner 必须拒绝空集合、simplified fixture 和未声明真实调用。focused tests 只用于定位，最终 acceptance 必须执行 clean-HEAD `./scripts/check-mainline.sh` 和完整的相关 qualification profile。

receipt 生成顺序固定为：代码/文档/tests 固定 → clean source identity → authoritative mainline/qualification → fresh-install reset/bootstrap evidence →逐 change evidence map → release bundle/receipts。任何后续 source change 都使该序列失效并要求重新运行，禁止在中途提前签 receipt。

### 10. 优雅性采用有界抽取，不进行大爆炸重构

本 change 允许抽取：

- dependency-free workspace job wire contract；
- public/private diagnostic model、sanitizer 和 boundary mapper；
- fresh/offline deployment proof verifier；
- cleanup result/compound failure helper；
- qualification scenario fixtures 与 evidence registry loader。

不以文件行数为由重写 repositories、harness、Host app 或 scientific attempts。只有当重复逻辑直接造成当前 contract drift、异常丢失或测试无法表达时才抽取；每个新 abstraction 必须有唯一 owner、单向依赖和直接 tests。

## Risks / Trade-offs

- [runner 增加 `openzyme-domain` 依赖可能扩大耦合] → 只导入零依赖窄 wire module，增加 import-boundary test，禁止 runner 导入 repository/service/control-plane composition。
- [详细 cause 可能泄露 secret、path 或 hostile backend text] → public/private 双记录、allowlisted public fields、长度限制、secret/path/handle sanitizer 与负例测试；完整细节只在 private operator evidence 中。
- [把异常全部结构化可能再次形成包装层堆叠] → 只在 authority、external effect、persistence、process/cleanup 和 public API 边界翻译；纯内部函数让原异常自然传播。
- [fresh deterministic receipt 只能证明 bootstrap contract，不能单独证明设备旧数据已经删除] → 分离 `FreshInstallBootstrapReceipt` 与 `DeviceFreshInstallResetReceipt`，后者绑定精确 inventory/quiescence/zero scan；不得混称。
- [删除旧 DB/storage/cache/backups 后不可恢复] → 所有软件 gate、inventory ownership、quiescence 和 exclusion 先完成；删除 receipt 明确 `recoverable=false`。用户已选择 fresh install，不创建最终仍要删除的临时备份来制造虚假安全感。
- [纠正 checkbox 会让原 changes 从 complete 变回 incomplete] → 这是恢复事实而非回退实现；gap registry 保留原声明、反证、repair owner 和重新完成证据。
- [恢复 qualification 容易把已删除的 artifact-era 测试整体搬回] → 只恢复当前 file/revision contract 的行为和跨边界 oracle，不恢复 legacy artifact product surface。
- [最终 receipt 很容易因后续文档或测试修改再次过期] → receipt generation 永远是最后一个 source phase；签发后只允许核验和归档 rename，不再修改 current source slice。

## Migration Plan

1. **事实冻结与 OpenSpec 修正**
   - 记录当前 HEAD、worktree、十四个 change status、旧 receipt/source identity 和已知反证。
   - 创建 evidence-gap registry，只恢复被反证 tasks 为未完成。
   - 在任何实现前完成并 strict-validate 本 change 的 proposal/design/specs/tasks。

2. **规范与共享合同**
   - 更新主架构、`AGENTS.md` 与 `docs/v3/`，明确 file/revision/job 模型和保留边界。
   - 演进 FailureObservation/public API/private diagnostic schema。
   - 抽取 workspace job wire contract 和 deployment proof verifier。

3. **实现修复**
   - 修复 cancellation receipt、replay validation 和 Host/domain mapping。
   - 修复 publication、Git recovery、handoff cleanup 的 typed classification/cause preservation。
   - 实现 fresh/offline proof 分支和只读 startup diagnostics。

4. **行为级验证与文档收敛**
   - 增加上述正反例和 restart/fault tests；恢复 scientific/UI 直接覆盖。
   - 重建 production-composition architecture qualification registry 与真实 boundary oracle。
   - 运行 focused tests、全相关非 live suites、strict OpenSpec、retired-surface audit 和 mainline；失败必须保留详细诊断，不能降级验收范围。

5. **本设备 reset preflight**
   - 只读发现 OpenZyme 进程、配置、DB、storage、receipts、cache、backup 和 exclusions。
   - 输出精确 target inventory 与 ownership evidence，验证 quiescence 和无 unresolved target。
   - 在 deletion 前再次确认最终 binary/bootstrap verifier 已通过空数据库测试。

6. **不可逆 fresh-install reset**
   - 使用显式目标逐项删除所有已证明的 OpenZyme 旧记录/storage/cache/receipts/backups。
   - 从空 deployment locator 初始化 final schema，验证 deterministic fresh receipt、manifest、foreign keys、无 retired structures/storage markers。
   - 生成 current reset receipt，报告每个删除 target、不可恢复性和零残留结果。

7. **最终证据与归档**
   - 在最终 clean HEAD 重新运行 authoritative mainline/qualification；任何 source drift 均回到第 4 步。
   - 生成新的 release bundle、逐 change receipts 和 evidence map，旧 evidence 只标记 superseded。
   - 重新勾选有直接证据的原 tasks，逐项核对 14 changes 与本 change。
   - 批量归档十四个目标 changes 与本 change；其他 active changes 单独验证、单独裁决。

代码和 OpenSpec 修改在提交前可按精确文件回退。设备删除 phase 不可回退；如果 preflight 或 reset 中止，不得生成 fresh-install completion receipt，也不得归档。

## Open Questions

产品与架构决策已经由用户完成，没有待定的策略选择。实施时仍需用只读证据回答以下环境事实：

- 本设备当前实际使用的 OpenZyme database locator、state/cache/storage roots 和相关进程 identity 是什么；
- 旧 release/removal receipts 与 backups 是否全部位于已知 OpenZyme roots，是否存在无法证明 owner 的同名路径；
- 当前部署属于 fresh、offline-removal 还是不一致状态，以及是否存在并发写 owner；
- repository-service Git/LFS current truth 的实际 roots 是什么，以便形成明确 exclusion；
- 现有 architecture qualification registry 中哪些 production boundary owners 与 external ports 仍可直接复用，哪些测试已被删除或降级。

这些问题不授权猜测或扩大删除范围；无法证明的环境 target 保持未解决并阻止“全部旧记录已删除”的 completion claim。
