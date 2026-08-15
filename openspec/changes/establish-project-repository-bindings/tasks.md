## 1. C1 前置 receipt 与 repository service gate

- [x] 1.1 验证 immutable `aox_artifact_cutover_supersession_acceptance@1` receipt、其 source revision 和 C0 scope audit；receipt 缺失、失配或未保持 legacy NO-GO 时停止 C1。
- [x] 1.2 记录 C1 implementation baseline，冻结当前 session schema、repository/migration head、Host deployment configuration、现有 auth surface 与 focused test清单；明确 C1 可与 C2 并行，但 C3/C4 尚不可开始。
- [x] 1.3 建立 durable-root preflight receipt，要求显式配置 bare Git root、LFS object root、HTTPS service identity 与备份/权限 facts，并拒绝 `/tmp`、当前 Host checkout、process cwd、ambient remote 或临时目录。
- [x] 1.4 固定 standard-protocol implementation receipt，证明目标服务为 Host-owned bare repositories、Git smart HTTP v2 over HTTPS、Git LFS Batch API v2/basic transfer，且没有 agent-facing custom file RPC 或 local-directory fallback。

## 2. Binding domain、migration 与 repositories

- [x] 2.1 在 `openzyme-domain` 增加 immutable `ProjectRepositoryBinding`、binding lifecycle/status 与 safe identity types，覆盖 internal Git/LFS service、upstream origin、object format、base ref/exact commit、ref policy、policy version/digest 和 canonical digest。
- [x] 2.2 添加单一 forward SQL migration，创建 project binding versions、project active-version pointer、session binding pin 和必要 unique/FK/index constraints，并为 pre-existing sessions保留显式 `repository_binding_required` 状态。
- [x] 2.3 在 `openzyme-core` 实现 binding repository 的 create-version、get-by-id/version、activate-for-project 与 immutable-read operations，拒绝原地更新 authority-relevant fields。
- [x] 2.4 扩展 session repository，使 session insert 与 exact binding id/version/resolved base commit pin 在同一事务完成，并保持既有 project access control。
- [x] 2.5 实现 canonical binding digest/serialization 与 drift comparator，精确区分 remote、object format、base、namespace、LFS identity 和 policy drift。
- [x] 2.6 为 domain、migration、repository unique/immutability、active-version rollover 与 legacy-unpinned rows 增加 focused unit tests。

## 3. Durable bare Git 与 HTTPS smart HTTP v2

- [x] 3.1 实现 durable bare-repository root manager，按 binding repository identity创建/打开 bare repository，校验 ownership/permissions/object format，并在 durable root缺失或漂移时显式失败。
- [x] 3.2 在 Host service 增加 Git smart HTTP v2 discovery 与 `git-upload-pack` HTTPS read path，绑定 repository identity、scoped bearer credential 和 bounded diagnostics。
- [x] 3.3 增加 `git-receive-pack` HTTPS write path，并将 proposed ref updates送入 server-side ACL validator后再原子更新 refs。
- [x] 3.4 实现 private namespace ACL：agent只可对自己的 `session + agent_member + workspace_generation` refs执行 create或fast-forward，force-update和delete必须拒绝。
- [x] 3.5 实现 Host-only publication create namespace与migration-owner historical namespace ACL，并证明agent credential不能创建、更新或删除publication/historical refs。
- [x] 3.6 将 upstream origin保持为独立配置/authority，拒绝把internal bearer credential用于upstream push/PR/release，也不在internal remote失败时fallback upstream。
- [x] 3.7 增加native Git protocol integration tests，覆盖HTTPS v2 clone/fetch、private create/fast-forward、non-fast-forward、force/delete、cross-agent namespace和publication ACL。
- [x] 3.8 实现独立 retention-owner 的整代 private namespace retirement：只允许 closed workspace generation 在固定 deadline 后、无 active lease/publication/migration/legal/audit/retained-reference hold 时先写 immutable terminal-ref/commit receipt 再删除；测试拒绝 agent deletion、整代提前删除及选择性 checkpoint pruning。

## 4. Standard Git LFS Batch API v2 与 basic transfer

- [x] 4.1 实现 durable LFS object root 与repository-scoped object addressing，校验OID/size、原子promote和read-after-write，禁止把bytes写入bare repo root、`/tmp`或ambient cwd。
- [x] 4.2 实现 authenticated Git LFS Batch API v2 `download` response，返回与binding/repository/token scope一致的basic transfer actions。
- [x] 4.3 实现 authenticated Git LFS Batch API v2 `upload` response及basic upload/verify path，拒绝OID/size mismatch、foreign repository和scope drift。
- [x] 4.4 统一Git与LFS的repository identity、binding version和bearer-token audience，确保一个protocol的credential不能越权到另一project/generation/ref scope。
- [x] 4.5 增加native `git-lfs` integration tests，覆盖batch download/upload、basic transfer、verify、missing object、OID/size tamper、wrong repository/token和durable restart reread。

## 5. Session pinning、credentials 与 Host projection

- [x] 5.1 在Host session creation service中解析唯一active binding、验证exact base commit可由internal remote读取，并在任何workspace provisioning前原子保存session pin。
- [x] 5.2 在session restore、workspace prerequisite、publication prerequisite、HPC prerequisite与historical migration prerequisite中只读取session pin，拒绝project latest或ambient Git state替代。
- [x] 5.3 实现existing-session显式mapping/import command，要求operator提供exact binding version/base并生成immutable mapping receipt；无法闭合的session保持`repository_binding_required`。
- [x] 5.4 实现Host credential broker的Git/LFS scoped bearer issuance，绑定binding、session、agent、workspace generation、capability lease、protocol和ref classes，不把长期secret写入workspace。
- [x] 5.5 增加safe Host API/workspace projection，只公开binding id/version、safe remote identity、object format、exact base、policy digest与allowed ref classes，并隐藏Host roots、service credentials和private endpoints。
- [x] 5.6 对credential expiry/reissue实现显式失败与下一动作重新签发，证明不会自动replay失败的Git/LFS command、切换endpoint或改变binding identity。
- [x] 5.7 增加focused Host tests，覆盖new-session pin、active-version rollover、restore drift、legacy mapping、missing binding/base、credential redaction与无ambient fallback。

## 6. Deployment、恢复与迁移闭合

- [x] 6.1 扩展typed runtime/deployment settings与example configuration，要求HTTPS identity、bare Git root、LFS root、upstream和project binding inventory全部显式提供且路径可持久恢复。
- [x] 6.2 增加Host startup preflight/health checks，分别验证durable roots、bare repositories、exact base commits、HTTPS Git v2、LFS batch/basic和ref ACL配置，失败时不创建临时替代服务。
- [x] 6.3 实现binding version activation/retirement runbook与read-only audit command，确保被session/revision/receipt引用的旧version、refs和objects不可删除或改写。
- [x] 6.4 执行restart/backup-restore rehearsal，证明Host process重启后binding、bare refs、LFS objects、session pins和ACL identity保持一致。

## 7. Focused tests、文档与 C1 验收 receipt

- [x] 7.1 运行domain/core/Host focused tests与真实native-client integration suite，覆盖binding persistence、session pin、HTTPS smart HTTP v2、LFS Batch API v2/basic、durable restart、ACL和全部forbidden fallbacks。
- [x] 7.2 更新 `docs/OpenZyme架构设计.md`、`docs/v3/01-target-architecture.md`、`docs/v3/02-control-plane.md`、`docs/v3/04-public-interfaces.md` 及相关部署文档，记录internal/upstream分离、durable roots、standard protocols、session pin与credential boundary。
- [x] 7.3 运行 `DO_NOT_TRACK=1 openspec validate establish-project-repository-bindings --type change --strict --no-interactive` 并保存通过结果。
- [x] 7.4 运行 `./scripts/check-mainline.sh`，并确认失败不会被live/integration opt-in、临时repository或ambient checkout掩盖。
- [x] 7.5 审计Git diff、migration顺序、配置样例、secret/Host-path projection和change scope，确认未实施C3 clone、C4 publication或upstream effect。
- [x] 7.6 生成 immutable `project_repository_binding_acceptance@1` change receipt，绑定C0 receipt、code/schema/config digests、focused/integration tests、docs、strict OpenSpec、mainline、durable-root/restart proof与`eligible_successor = C3 when C2 receipt also passes`。
