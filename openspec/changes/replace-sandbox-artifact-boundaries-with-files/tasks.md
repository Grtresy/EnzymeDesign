## 1. 前置 change receipts 与删除准入

- [ ] 1.1 用 pure verifier 核验 `migrate-research-report-and-task-handoffs-to-files` change receipt，确认 research、report、task 与 protocol 的全部 current writer/consumer 已切换到 `RevisionPathRef`、`TaskEvidenceRef` 和显式 publication 边界。
- [ ] 1.2 用 pure verifier 核验 `execute-hpc-jobs-from-workspace-revisions` change receipt，确认 clean revision、Gitless compute、可靠 `ExternalJobHandle`、remote dispatch ledger 以及无 stage/fetch/`expected_outputs` 的 current execution 路径已闭合。
- [ ] 1.3 用 pure verifier 核验 `migrate-scientific-deliverables-to-files` change receipt，确认全部 current scientific writer/consumer 已切换到 immutable revision/path/LFS identity，且 historical import 永久不可供 current workflow adopt。
- [ ] 1.4 枚举 current tool catalog、Host API/callback、sandbox SDK、engine adapter、pipeline worker、prompt、projection、migration 与 continuation 中每个 `artifact.*`、`artifacts.*`、`sandbox.file.*`、source snapshot、catalog materialize/register、`hpc.stage_artifact`、`HpcStageRef`、staging/fetch consumer及writer，并为每项记录新的 file/revision/control-plane owner；任何无已验收 owner 的项都阻止删除。
- [ ] 1.5 生成并 pure-verify deletion-admission receipt，绑定三个直接前置 receipts、传递的repository/lease/workspace/LFS/publication receipts、当前 commit、design/spec digests和完整残余surface inventory；在首次删除前重验所有 identity，禁止提前删除仍被writer依赖的旧接口。

## 2. Current contract epoch 与残余 writer 冻结

- [ ] 2.1 定义并迁移内部 `file_workspace_sandbox@1` contract identity，绑定 sandbox schema、candidate tool catalog、pipeline SDK、Host gateway allowlist和revision execution schema，禁止同一内部 identity 混用artifact/file authoring；不得在本 change 单独激活 `file_workspace_public@1` Host/CLI/UI epoch。
- [ ] 2.2 将所有 current ordinary/research/report/task/protocol/scientific/execution writer指向前置change已经验收的file、revision或control-plane repository，并增加source-bound zero-old-write probe，证明切断前不存在旧artifact/stage writer或未结算旧continuation。
- [ ] 2.3 冻结current artifact、catalog、source-snapshot、stage与output-fetch mutation writer，保留只读historical rows/bytes供后续迁移；current process、recovery、projection或new receipt不得获得historical writer authority。
- [ ] 2.4 为旧tool name、SDK method、request field、schema epoch与continuation payload定义明确versioned unsupported-current-contract错误，拒绝artifact id、Host path、catalog ref、`HpcStageRef`与`expected_outputs`且不推断replacement revision/path。

## 3. Clone-native file workspace 与 capability admission

- [ ] 3.1 将sandbox launch固定到exact `session + agent_member + workspace_generation`独立clone cwd，加入mount qualification，拒绝Host checkout/home/`.ssh`、共享`.git`、linked worktree、ambient cwd和未声明可写路径。
- [ ] 3.2 将capsule原生filesystem、shell、Git、Git LFS、network、upload/download及executor专属SSH/rsync/scp能力绑定到exact active `AgentCapabilityLease` scope与generation；scope内不逐命令调用Host或请求approval，stale/missing scope在process/effect admission前失败。
- [ ] 3.3 资格验证Podman runtime中的native toolchain、DNS/network policy、credential injection/revocation和owner isolation，证明普通Git/LFS/curl/SSH/rsync/scp数据面不经过typed Host transfer gateway，也不创建canonical work-product、publication、task或external-job truth。
- [ ] 3.4 实现same-generation process resume与cross-agent isolation，证明ordinary files、index、branch与LFS state在同一clone持久且不泄漏到其他agent generation；generation replacement只显式切换新clone，不复用旧cwd或credential。
- [ ] 3.5 保留exploration期间dirty/modified/untracked工作面并直接投影Git status；publication与private revision execution继续调用exact clean contract，失败时不stash、clean、commit、snapshot、materialize或选择其他revision。
- [ ] 3.6 让native OS/Git/LFS/network/SSH/rsync/scp process返回真实exit status与bounded stdout/stderr，未知结果由所属operation保留explicit uncertain state，禁止猜path、造input、换endpoint/credential/mode/backend或replacement effect。

## 4. Model、SDK、engine 与 runner surface 一次性删除

- [ ] 4.1 从供后继 public cutover 使用的 candidate model-tool registry、tool reflection、capability projection和runtime prompts实现中删除 `artifact.*`、`artifacts.*`、`sandbox.file.*`、`hpc.stage_artifact` 及其aliases/examples，生成exact catalog digest；当前 public activation与旧client disposition由C11统一完成。
- [ ] 4.2 从 `openzyme_pipeline` SDK、sandbox protocol与serialized schemas删除artifact get/register/materialize、source snapshot、file proxy、stage/fetch、`HpcStageRef`和`expected_outputs`类型/方法，重新生成或更新所有current typed clients且不提供compatibility authoring adapter。
- [ ] 4.3 从capability engines、sandbox supervisor、pipeline worker与runner adapters删除artifact publisher、materializer、stager、output fetcher及对应callbacks/phases，证明revision-bound source/result path是唯一current execution file route。
- [ ] 4.4 从 Host 内部 authoring services、event producers、eval fixtures 与 continuation mutation paths 删除旧 writer calls，并为 C11 提供 typed replacement/schema inventory；Host API/CLI/UI projection、restore/event public epoch和旧client disposition仍由C11统一切换，不在本 change 形成第二次 public activation。
- [ ] 4.5 运行source-level reachability审计并删除不再被historical migration owner使用的旧tool/SDK/adapter implementations、imports和dependencies；artifact数据库与historical bytes留给 `remove-artifact-control-plane-and-storage`，本change不物理删除。

## 5. Control-plane-only `SandboxHostGateway`

- [ ] 5.1 将 `SandboxHostGateway` 固定为closed、versioned control-plane operation set，仅保留approval、`workspace.publish`、controlled external job、continuation settlement、protocol/task canonical mutation与bounded runtime inspection等已声明effect。
- [ ] 5.2 从gateway接口、repository factory和mutation registry删除file CRUD、artifact/catalog、source snapshot、network/upload/download、Git/LFS transport、SSH/rsync/scp、HPC stage和output fetch callbacks及其publisher/stage/fetch writers。
- [ ] 5.3 要求每个sandbox control-plane call携带exact `SandboxHostCallContext`和资源类别对应的显式mutation writer，并独立校验session/execution/capability/continuation/generation/fence；任一authority不得替代另一项。
- [ ] 5.4 要求durable execution callback使用匹配controlled-operation write fence的durable-execution context，禁止reflection-bound method、`Callable[..., ...]`、engine creation-time repository或optional `Any` repository选择authority。
- [ ] 5.5 验证native private filesystem/transfer不打开canonical mutation writer，而publication、external-job和protocol/task effect只写各自repository；clone文件或remote shell side effect不能直接改变canonical状态。

## 6. Revision-bound execution、历史隔离与 forward-only cutover

- [ ] 6.1 对current private execution admission只接受exact binding/workspace generation/clean commit/tree/LFS manifest/normalized cwd，对published handoff只验证immutable `PublishedRevision`与path；拒绝mutable path现场copy与producer dirty-tree检查串线。
- [ ] 6.2 删除source snapshot、catalog materialization、HPC stage、declared-output fetch和artifact result的current request/recovery branches，旧字段缺失新revision identity时直接non-resumable或unsupported，禁止dual writer、schema translation和dynamic rollback。
- [ ] 6.3 将historical artifact reader隔离到命名明确的migration/inspection入口并限制为Host-owned read-only authority，证明其row、bytes、digest或alias不能满足current publication、execution、handoff、task/scientific evidence或capability admission。
- [ ] 6.4 实施 quiescent internal readiness gate：重验 zero old writer/process/continuation 与 zero unsettled old external effect，冻结 artifact/stage writer并产出 candidate catalog/schema digest和 activation-ready receipt；不得在 C11 前推进 public contract epoch或宣称旧clients已切换。
- [ ] 6.5 建立 rollback/activation qualification：C11 public activation前只允许回退尚未启用的整套 internal implementation；C11激活后保留已创建Git/LFS revision并只做前向修复，禁止在混合release中恢复单个artifact、sandbox-file、stage/fetch或typed transfer endpoint。

## 7. 验证、架构文档与 change receipt

- [ ] 7.1 运行clone persistence/isolation、native file/network/transfer、lease scope/revocation、dirty-vs-clean boundary、gateway context/mutation fencing、stale tool/schema、historical non-adoption、native error/uncertain effect和no-artifact-write focused tests及touched Ruff/integration fixtures，并保存exact results。
- [ ] 7.2 同步 `docs/OpenZyme架构设计.md`、相关 `docs/v3/` harness/runtime/control-plane/capability/public-interface文档、`docs/v3/execution-pipeline-docs/README.md` 与 `docs/v3/harness-complexity-audit.md`，明确clone-native data plane、control-plane-only gateway、revision execution、历史隔离及无Host typed transfer/artifact/stage surface。
- [ ] 7.3 运行 `DO_NOT_TRACK=1 openspec validate replace-sandbox-artifact-boundaries-with-files --strict`、`git diff --check`、current surface/forbidden writer与dependency reachability audit及 `./scripts/check-mainline.sh`，确认无 `artifact.*`、`artifacts.*`、`sandbox.file.*`、source snapshot、`HpcStageRef`、stage/fetch、typed transfer gateway或current compatibility path。
- [ ] 7.4 生成并 pure-verify `replace-sandbox-artifact-boundaries-with-files` change receipt，绑定全部prerequisite/deletion-admission receipts、internal contract identity、candidate public catalog/schema digest、source/schema/migration/docs digests、focused/mainline results、zero-old-writer与forward-only invariants，标记 `implementation_complete=true`、`public_activation=false`、`eligible_successor=cut-over-workspace-public-interfaces`；receipt 不授予publication、external-job、task或scientific outcome authority。
