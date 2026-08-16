## Why

用户选择本轮物理删除历史 artifact 数据结构，因此必须先把所有仍需保留的 bytes、lineage 和引用迁入可验证的 Git/LFS 历史空间。删除与迁移必须分开验收，避免“表已删但历史字节或映射尚未闭合”。

## What Changes

- 枚举所有 legacy artifact rows、storage objects、materialization/scientific/report/research/HPC references，并在迁移开始前冻结 current artifact writers。
- 按 project/session 建立 Host-managed immutable historical-import refs；每个 legacy artifact 映射到 exact commit/path、Git blob 或 LFS OID/size，并保存原 id、kind、digest、owner 和 lineage manifest。
- 真实读取每个源 object，重算 digest，写入 Git/LFS 后再次读取验证；缺失、损坏或冲突立即使整个受影响 migration unit 失败。
- 将仍需保留的 control-plane foreign references 更新为 typed revision/path/result/scientific refs，并生成可重复核验的一次性 migration receipt。
- superseded AOX bytes 迁入只读 historical namespace，明确标记 non-adoptable；迁移不产生 current `PublishedRevision`、fresh evidence 或 GO。
- 迁移期不 dual-write，不以 placeholder、空文件、metadata-only row 或 silent skip 代替缺失 bytes。

## Capabilities

### New Capabilities
- `historical-artifact-git-lfs-migration`: 定义 legacy artifact bytes/lineage 到 immutable Git/LFS history 的完整迁移与删除前证明。

### Modified Capabilities

## Impact

影响 legacy artifact repositories/storage、所有 FK consumer、Git/LFS migration tooling、AOX historical verifier、database migration/backup runbook 和删除 gate。该 change 只迁移，不删除旧表或源 bytes。
> 连续源码迁移阶段受
> `operator/source-only-historical-migration-gate.json` 约束：只实现可审计的
> migration machinery，不读取或写入 remote Git/LFS、不执行 reference rewrite，也不
> 删除 legacy source。
