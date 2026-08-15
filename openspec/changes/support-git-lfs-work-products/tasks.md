## 1. 前置 change receipts

- [ ] 1.1 用 pure verifier 核验 `establish-project-repository-bindings` change receipt，确认 exact source、durable internal Git/LFS service identity、binding version、ref ACL 与 policy digest 已闭合；缺失或漂移时停止本 change。
- [ ] 1.2 用 pure verifier 核验 `establish-agent-capability-leases` 与 `provision-independent-agent-git-workspaces` change receipts，确认 native Git/LFS/network scope、独立 `.git`、workspace generation 和短期 credential 边界已闭合。
- [ ] 1.3 用 pure verifier 核验 `publish-and-sync-workspace-revisions` change receipt，确认 frozen publication intent、create-only immutable ref、`PublishedRevision`、exact reconciliation 与 whole-tree manifest 已闭合。
- [ ] 1.4 生成并验证本 change 的 prerequisite receipt，绑定上述 receipts、当前 commit、OpenSpec design/spec digests 与 deployment binding；任一 prerequisite 未完成时不得启动 LFS writer、publication validator 或 GC。

## 2. Repository-bound LFS policy 与持久模型

- [ ] 2.1 在 domain 与数据库迁移中加入版本化 LFS endpoint identity、path rules、ordinary-blob threshold、object/workspace/repository quotas、retention classes 和 policy digest，并证明既有 binding row 不可原地修改。
- [ ] 2.2 将 session、workspace credential、LFS transfer 和 publication intent 固定到同一 repository binding version，补 drift/missing/unknown-version fail-closed repository tests。
- [ ] 2.3 建立 durable LFS object metadata、upload session、publication pin 与 private reachability repositories，使用 insert-only receipt/unique constraints，禁止 `/tmp`、Host checkout、cwd 或 agent-facing CAS locator。
- [ ] 2.4 实现 repository/session/agent/workspace-generation scoped LFS bearer credential issuance 与 revocation，证明 OID 存在性和 physical storage locator 不向未授权 project 泄漏。

## 3. 标准 Git LFS protocol 与原生 clients

- [ ] 3.1 在 C1 已验收的 Git LFS Batch API v2/basic transfer service 上增加版本化 policy、quota、retention 与 closure 所需字段和 canonical errors，复用同一 endpoint/object root/repository identity，不建立第二个 LFS server 或 alternate object source。
- [ ] 3.2 将既有 basic upload 路径扩展为受 quota reservation 约束的 streaming size/SHA-256 验证、no-replace install、fsync/atomic commit 和 identical-OID idempotency，错误 bytes 不得进入可读 object closure。
- [ ] 3.3 将既有 basic download 路径扩展为 streaming authoritative object-read probe 与 closure receipt，保证返回 bytes、declared size 和 OID 一致且不暴露底层对象存储路径。
- [ ] 3.4 在版本化 Podman capsule 与 HPC login image 安装并资格验证原生 Git LFS client；增加 compute image/fixture 负向检查，确保 compute 无 Git、Git LFS、repository credential 与 internal-remote access。
- [ ] 3.5 增加 native clone/fetch/checkout/private-push integration，证明 Git/LFS 使用标准 endpoint 且普通 curl/scp/rsync/LFS upload 不创建 `PublishedRevision`、task evidence 或 artifact record。

## 4. Publication closure 与大文件拒绝

- [ ] 4.1 实现 exact commit-tree 遍历、revision-scoped `.gitattributes` 解析与 canonical Git LFS pointer parser，拒绝 malformed pointer、unsupported algorithm、path traversal、symlink/submodule policy drift。
- [ ] 4.2 实现逐对象 authoritative read、actual size/SHA-256 重算和 canonical sorted LFS closure manifest，绑定 normalized path、mode、pointer blob OID、LFS OID 与 size。
- [ ] 4.3 将 closure manifest digest、binding/policy identity 和 object-read receipts 接入 frozen publication intent 与 `PublishedRevision` materialization；任一 missing/corrupt/unauthorized object 时不得创建 shared projection 或替代 publication。
- [ ] 4.4 实现 oversized ordinary Git blob validator，返回全部违规 path/blob OID/size/threshold/rule，证明系统不编辑 `.gitattributes`、不重写 commit、不自动上传 LFS object。
- [ ] 4.5 实现 closure verification cache 的 exact commit/tree/policy/endpoint/authorization key 与 fresh-read gate，证明 cache hit 不能替代当前 object 可读性或 publication proof。
- [ ] 4.6 为 LFS upload 完成但 publication response/DB commit 丢失的窗口接入同一 publication intent/ref reconciliation，禁止分配第二 publication、ref、endpoint 或自动重传未知 effect。

## 5. Retention、quota 与 GC

- [ ] 5.1 在 `PublishedRevision` 成功 materialization 时原子记录完整 Git/LFS closure pins，并增加 update/delete guards，证明 published object 超过 scratch retention 后仍不可 GC。
- [ ] 5.2 实现 private refs、active workspace generations、upload sessions 与 publication pins 的 repository-scoped reachability 计算；private namespace 只有在已验证整代 retirement receipt 后才视为退役，并输出 canonical GC candidate receipt。
- [ ] 5.3 实现先 dry-run receipt、后 exact candidate delete 的 GC worker，删除前重验 whole-generation retirement receipt、reachability、policy/version 与全部 hold，发现 drift 时整批停止且不删除 retained checkpoint 或 published object。
- [ ] 5.4 实现 object/workspace/repository quota accounting 与并发 reservation，覆盖超限、rollback、identical-OID dedup 和跨 repository ACL；quota failure 不得降级为普通 Git blob、CAS 或其他 endpoint。

## 6. 验证、架构文档与 change receipt

- [ ] 6.1 运行 LFS Batch/basic transfer、pointer/closure、oversized blob、quota/GC、cross-repository authorization、native Podman/HPC-login 和 Gitless compute focused tests及 touched Python Ruff，并保存 exact command/source/results。
- [ ] 6.2 同步 `docs/OpenZyme架构设计.md`、相关 `docs/v3/` control-plane/capability/public-interface 文档、`docs/v3/execution-pipeline-docs/README.md` 与 `docs/v3/harness-complexity-audit.md`，明确标准 LFS、无 agent-facing CAS、closure/pin/GC 和 native transfer 非 publication 边界。
- [ ] 6.3 运行 `DO_NOT_TRACK=1 openspec validate support-git-lfs-work-products --strict`、`git diff --check`、文档链接/forbidden-pattern audit 与 `./scripts/check-mainline.sh`，确认不存在 custom pointer、CAS/file gateway、compute Git credential、publication fallback 或 live effect。
- [ ] 6.4 生成并 pure-verify `support-git-lfs-work-products` change receipt，绑定 prerequisite receipts、source commit、schema/migration/policy digests、focused/mainline results、docs digests、closure/GC invariants与 `implementation_complete=true`；receipt 不得授予 publication、HPC 或 scientific authority。
