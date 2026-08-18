# 本设备 fresh-install reset 证据

日期：2026-08-18（Asia/Hong_Kong）

本证据只证明当前设备维护操作，不授予 task、scientific、runtime、publication 或 repository mutation authority。逐 occurrence 的私有 inventory、quiescence、exclusion、deletion、permission、zero-scan、fresh proof 与 reset receipt 保存在 `/tmp/codex-device-fresh-reset-20260818/`；仓库只记录可公开摘要，不提交 token、private path payload 或旧记录内容。

## 冻结范围与排除项

- inventory schema：`device_fresh_install_reset_inventory@1`
- inventory digest：`sha256:3c4cb46cf8bcf032fd62332709bbfda56dc5b1c1ebeb4c4c935d38085138aaae`
- 目标：旧 state database/config/secret/TLS/receipts/backups，精确 MICU ledger 及其两个 sidecar，以及 discovery 时实际存在的 172 个 `/tmp` 顶层 OpenZyme runtime/test/receipt roots。
- 展开后：27,902 个 item，其中 27,901 个 deletion occurrence，约 511,470,490 bytes；`unresolved_targets=[]`，全部 `recoverable=false`。
- 显式排除：当前 source `.git`、`openspec/`、`apps/`、`packages/`、`docs/`、`scripts/`，以及 current repository-service Git/LFS truth。
- preserved Git：33 files，5 refs，file-set digest `sha256:9cc1564dbd7a5476daa876ab79f018e43cb98ef112dacfa020ee34f6b1120ae5`，`git fsck --full --no-dangling` 通过。
- preserved LFS：1 object，file-set digest `sha256:146bcbed8937ea9ca3448b85614127a1b2c4ef00930f899ec9b8cbcd4fc87617`。
- exclusion evidence digest：`sha256:093f40fc9f0bce60ba1a40a6535ea93ba2baac8dda3051ed19b9af989cf33ab0`。

## Quiescence

- 发现一个自 08:44 起卡住约五小时的 architecture-qualification pytest（PID 2941381）；其父 sandbox chain 为 2941352/2941379/2941380，均属于本次旧 gate，不持有 DB/Git/LFS。向精确 PID 发送 `SIGTERM` 后整个 chain 退出。
- 宿主机 exact `lsof` 对旧 control-plane DB、MICU ledger 和 repository Git 无打开文件。
- Podman container/volume 均为空；`openzyme*`/`mcp-hpc*` user units 为零。
- 另一个 repository 的 `nucpred.portal.api` uvicorn 被明确识别为 non-OpenZyme exclusion，未停止、未修改。
- 两次 state snapshot 的 device/inode/size/mtime/digest 与 top-level set 相同。
- 旧 DB 只读 `integrity_check=ok`、`foreign_key_check=[]`、journal=`delete`、user_version=1；无 WAL/SHM，mutation writer/lease owner 为零。
- quiescence digest：`sha256:4884af2f0ab410a880fece9dda25e6c64394c7f5f3322db068ed1c56adf73d51`。

## 删除与故障语义

- 首次执行在 legacy sealed directory（directory 0555/file 0444，均由当前用户拥有）得到 `PermissionError errno=13`。operator 返回 `reset_delete_failed`，包含 exact identity、phase、expected/observed、operator action、`mutation_applied=true`、`fallback_performed=false` 和 chained cause；未静默跳过。
- 停止时已有 5,456 个 fsync-backed occurrences。新增 typed permission-adjustment ledger 后，只对 frozen inventory 内、owner 为当前有效用户、待删除的 read-only directory 增加 owner `wx`，不放宽 inode/device/content/symlink/mount/exclusion 检查。
- permission adjustments：63，set digest `sha256:019dfe503fe87be9166e5fc01bc8b62e62b21c9e54504629ff80255ff071b989`。
- deletion occurrences：27,901/27,901，set digest `sha256:2b1c288def922e17889b9e47c619ff1657de95a275f2f4f6b3fcbf37141e43f4`。
- 删除不可恢复；没有创建仍需再次删除的 rollback backup。

## 零残留与 fresh bootstrap

- 在创建新 DB 前，旧 state root 为空；所有 172 个 frozen `/tmp` OpenZyme roots、MICU ledger/sidecars、old binding inventory、secret/TLS/backups、cache/config 均不存在。
- fresh DB 使用相同 deployment locator，但 old inode `33852188` 已删除，new inode 为 `33816859`；typed replacement verifier 要求 new inode 不同且 fresh content digest 精确匹配，其他 reappearance 仍 fail closed。
- final schema generation：`openzyme_file_workspace_final@2`
- final manifest：`sha256:107b9a5eabdf72f9855b06a8a2b3864f6d5b70332b07d8484ffee0c7d8be6eb5`
- deterministic fresh receipt：`sha256:467279b20fe91d405a5e23497f29a18e63114f817e2b9675c9e35b916c673e9a`，stored 与 independently recomputed 相同。
- fresh DB product row total=0，legacy removal ledger/items=0，forbidden schema objects=[]，`integrity_check=ok`，`foreign_key_check=[]`。
- Host lifespan 使用 production durable supervisor 成功进入并退出。裸 stale client 返回 `409 stale_file_workspace_contract`；当前 contract client 在没有新 epoch 时返回 `503 file_workspace_public_epoch_inactive`。没有为获得 200 而恢复旧 release 或启用 fallback。
- fresh DB content digest：`sha256:a7e48fb773729e21b649f141e3e175490a6b0d374f13ae08d954c212946a8cd8`
- fresh DB identity digest：`sha256:012cb44921eaf4b5bfeff3fd0af1e7a9cbe4732232ecec0c4b505a140981a6a9`
- zero-scan digest：`sha256:8606a03cf2e8b15eea58069fe528e739b0e0d3efc5e0b7c877b991a875e3c7cc`
- provisional reset receipt digest：`sha256:6d089147f5551f3270305859c423c438e34e9348204a3f215958ce8c12c730ec`。

该 receipt 是 provisional，因为本证据、task checkbox、resource manifest 和最终 receipt chain 仍会改变 source identity。第 12 组必须在全部 source edits 固定后重跑 authoritative gates，并用相同 immutable inventory/occurrence/zero/fresh facts 重签最终 `DeviceFreshInstallResetReceipt`。
