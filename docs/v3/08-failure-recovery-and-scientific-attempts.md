# V3 Failure Recovery 与 Scientific Attempts

## Failure 不是单一状态

系统分别记录 occurrence、cause/hypothesis、effect certainty、retry eligibility、recovery disposition 和
terminal proof。一个异常可以阻断当前 observation，但不能自动说明 task、attempt 或 external effect 的终态。

`FailureObservation`、`ExternalEffectCertainty`、`RetryEligibility`、ControlledOperation 纯执行 DTO
和 runtime command 纯协调 DTO 的 canonical code owner 是 `openzyme-contracts`。Kernel application
service 决定写入与状态转换，Store Adapter 负责持久化；Plugin 只通过 `FailureApplicationService` 提交
安全 observation，不能写 raw diagnostic table。

非空失败采用一一对应的公开/私有 pair：公开 `FailureObservation` 必须携带私有记录的 exact digest，私有
`PrivateDiagnosticRecord` 必须回指同一 failure/diagnostic/source identity。Kernel 在拥有业务状态的同一个 fenced
Unit of Work 内同时写 pair 与 terminal/blocked owner；若业务事务本身因 stale/collision 在零部分写后拒绝，则只
允许另一个稳定、幂等的诊断 occurrence 记录拒绝事实。缺半边、digest 冲突或用新时间重写同一 occurrence 都
fail closed；公开投影永远不序列化私有记录。

目标 SQLite Store 对 extension participant、CAS、budget、authorizer 和 event/outbox 冲突采用同一
fail-closed 规则：公开错误保留 stable code、phase、safe observed identity、`mutation_applied=false` 与
`fallback_performed=false`，底层 SQLite cause 通过 exception chaining 留在私有诊断。任一 participant
失败会回滚同一短事务中的 Core mutation、extension state、event 和 outbox；系统不得在失败后绕过该
participant 另行提交，也不得把未提交的 receipt 或临时 target health 写成 release proof。

## Effect certainty

- `no_effect`：证明外部动作未发生，可在同 phase/identity 下进行有界恢复；
- `effect_known` / `terminal_known`：有 durable receipt 支持已知结果；
- `dispatch_in_doubt`：动作可能已发生，只能 reconcile，禁止 replay；
- unknown：证据不足，保持 blocked。

timeout、missing response、process exit 或 stale lease 不得提升 certainty。

LLM provider 调用不是可据此改变 Task/Science 的业务 effect。目标 Runtime Adapter 的 provider failure
固定记录 exact provider/backend/config identity、stable code、phase、retry eligibility、
`mutation_applied=false`、`fallback_performed=false`；原始异常、credential 和私有 URL 只进入 private
diagnostic。显式 retry budget 只可重试同一 provider/backend，禁止自动换模型、Provider 或 base URL。

Runtime outcome consumption 必须在一个 fenced Store Unit of Work 中写完整 outcome、ordered assistant/tool
conversation、public `FailureObservation`、signal settlement 与 outbox。exact duplicate 只返回原 receipt；同一
command 的不同 outcome、message/failure collision、stale runtime fence、workflow epoch 或 exposure identity
在任何部分写入前失败。provider failure 不能只留在进程日志，也不能因 transcript 写入失败而把 signal伪装成
已成功消费；下一 turn 与公开 projection必须读取同一 canonical transcript。

顶层 runtime command 的 worker failure 使用同一规则：`RuntimeCommandRecord(FAILED)`、公开 failure 与私有
diagnostic 在同一个 command claim/fence 下原子结算，且 status API 只返回安全 ID 与 effect facts。structured
context 缺失、legacy command、identity drift 或超界在 provider/tool/list/revalidation 前失败；provider generic
exception exactly once，不自动 retry、换 backend 或 fallback。workflow registry 在 message admission 前失败时，
message/binding/inbox/signal/link 保持不存在，另一个同 ingress authority 的诊断事务保存 pair 与原始 cause。

远端 Workspace Runtime 还要求 response identity 回绑 exact operation/request digest。SSH/SFTP/rsync 请求发出后
响应丢失时，Adapter 返回 `dispatch_in_doubt`，`mutation_applied=null` 且无 result payload；后续只允许通过同一
opaque workspace、generation、target qualification 和 operation identity reconcile，禁止重新执行命令、切换
target/provider 或回退为本地操作。

Slurm 也遵守相同规则：raw scheduler id 只属于 Adapter 私有 ledger，公开 opaque handle 不足以授权 submit 或
cancel；`dispatch_in_doubt` 时只允许用 exact operation/request/credential occurrence reconciliation。login/file
credential 永远不能升级为 scheduler occurrence credential。

## Recovery

recovery disposition 必须绑定 exact occurrence、owner、phase、operation digest、fence 和理由。允许的动作由
machine contract 限定，但 agent 决定何时检查、如何解释和是否请求新的用户授权。不能用“换 backend/参数”
绕开原 approval 或未知 effect。

workspace provisioning 复用同一 certainty 规则。`no_effect`、known terminal failure 或
`dispatch_in_doubt` 都会把 exact `WorkspaceProvisioningIntent@1` 结算为公开 `blocked`；只有同一 claim/intent/
generation 的 verified success receipt 才能由 Kernel 原子激活 workspace binding 与 root lease。unknown effect
只能 reconcile 同一 occurrence，禁止重跑 clone/volume helper、选择另一个 provider、补造 ready observation 或
让 message/runtime route绕过 readiness。恢复或 replacement 必须是显式 operator command，并创建可区分的新
occurrence或 generation。

具体而言，`WorkspaceProvisioningReconciliation@1` 是独立durable owner，保存原 intent state-version/digest、
原request/dispatch receipt、attempt/parent、claim fence与settlement receipt。即使它结算READY并激活原reserved
generation，原blocked intent、failure和dispatch receipt也不可改写；若它证明terminal failure，则只有显式
`/workspace/provisioning/successor` 可创建下一generation。reconcile与successor都不授权自动provision、drain、
Task mutation或Adapter fallback。

provisioning Adapter 的 blocked receipt 通过进程内 private sidecar 把原始 cause 交给 Kernel；Kernel 结算时原子
持久化 pair、receipt 与 blocked owner。缺失 sidecar 的 blocked receipt 不会被默认为完整失败，必须转成明确的
harness failure 或被拒绝。`dispatch_in_doubt` 的私有 request/receipt/context 只用于同 occurrence reconcile，
不得进入公开 workspace projection。

workflow authority failure 同样 fail closed。binding/link 缺失、revoked、epoch/digest drift、registry drift 或
causation不成立时，不扫描 latest/all conversation，不从 prompt/task/protocol payload 猜 refs，也不降级为
authority-empty provider turn。tool expansion、approval resolution、continuation 和 manual drain 都不能重开
revoked action或扩大 selection；如果外部 dispatch已经发生，revocation只阻止后续 canonical write，原 effect
仍按 certainty/reconcile合同处理。

deployment/cutover failure 还必须区分发生边界。只读 dry run、quiescence、backup verification 或 startup proof
失败时，`mutation_applied=false`，修复输入后从完整只读序列重跑；不得在失败点继续 mount surface。offline
adoption 的短事务失败由 SQLite 整体 rollback，且不得留下 activation、Session pin、ledger 或 complete receipt 的
部分 authority。只有 activation 前且 post-freeze canonical mutation 为零时，operator 才可恢复 exact verified
database/configuration/storage backups。

一旦 activation epoch 或其他 `@2` canonical mutation 已持久化，恢复状态固定为
`post_activation_forward_only`：停止 exact owner/surface、保留旧 occurrence/Session/authority identity并执行
forward repair。禁止 downgrade、恢复旧 Host reader、重启旧 Plugin、双写或把 backup/reset receipt 当作 current
authority。device reset 第一次删除后同样不可描述为自动可逆；失败只能以同一 frozen inventory 和 durable
occurrence log reconcile，未知 sibling、identity drift 或 lost occurrence 阻止 complete receipt。

## Scientific attempt

`openzyme-science` 是 attempt、selection、disposition、adoption、closure、deliverable、validation receipt、
application services、repositories、workflow registry、tools 和 Plugin routes 的 canonical owner。旧
`openzyme_domain`/Core compatibility modules 已删除。它通过 restricted transaction participant 与 Kernel
application services 组合；代码所有权切换不改变历史物理表名，真实 deployment cutover 仍需离线授权。

formal attempt 由显式 admission/authorization 创建，绑定 campaign、task、workflow/root、scope、budget 和
source identity。attempt 内的 operation universe 不从成功文件反推。

selection lifecycle：

1. `scientific.selection.begin` 固定当前 occurrence universe；
2. 每个 operation 写显式 disposition；
3. 成功 producer effect 通过 adoption 绑定 workflow role；
4. seal selection，拒绝 missing/duplicate/unknown occurrence；
5. finalization 从 immutable published revision 验证 scientific files；
6. attempt close 绑定 selection、adoptions、deliverable receipt、quiescence 和 authority consumption。

attempt close、report publish、task finish 和 master response delivery 仍是独立事实。

Session 必须固定 exact Science extension contract。已创建 Session 不因 wheel 安装、升级或删除而静默
切换 Science 语义；兼容 shim 也不能作为 capability activation proof。跨 Session、attempt、selection
revision、workspace generation 或 authority fence 的 adoption/closure 一律拒绝。

## Scientific files

`ScientificDeliverableRef` 绑定 publication、commit/tree/path、Git blob/LFS identity、content digest/size、
role、format contract 和 producer adoption。finalization fresh-read bytes，验证完整 bundle 后原子写 refs、bundle
和 receipt。

空结果必须是安装的 deterministic calculation 产生的 typed zero receipt，并有明确 empty reason、contract/
implementation digest 和 output digest。未知、缺文件或 provider failure 不是 scientific negative。

## Historical non-adoption

离线迁移生成的 `refs/openzyme/history/*` 和 mapping 永远
`historical_import_non_adoptable`。它们可供审计/verifier 读取，但不能满足 current scientific admission、
effect adoption、deliverable、report claim、task evidence 或 canonical GO/NO-GO。

AOX/HMM 历史 campaign 和旧 cutover receipt 同样不可回填。新的 formal attempt 必须从 current code、workflow
contract、public API、machine authority 和 source-bound evidence 重新建立。

## Fail-closed matrix

以下情况保持 blocked：unknown effect、unsettled occurrence、selection universe drift、producer/result mismatch、
publication/path/LFS drift、format failure、missing adoption、stale authority、quiescence mismatch 或 historical ref。
不存在 automatic negative、best-effort close、manual override 或 hidden fallback。

行为验收必须 fresh-read publication bytes，覆盖 unknown publication、path/blob/LFS drift、role/adoption
mismatch、bundle tamper 和 artifact-era request field rejection。AOX finalizer 测试只能证明 file-native
finalization composition；non-live fixture 不证明真实 provider/HPC 可用，也不授权新 campaign。
