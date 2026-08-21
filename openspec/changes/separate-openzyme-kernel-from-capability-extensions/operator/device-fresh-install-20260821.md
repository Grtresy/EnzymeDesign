# 2026-08-21 本机 fresh-install 操作证据

## 权限与范围

用户明确授权永久删除旧 `control-plane.sqlite3`、同名 `-wal`/`-shm` 和整棵旧
`/home/grtresy/.local/share/openzyme/repository-service`，并在原数据库路径按最新协议 fresh bootstrap。源码
checkout、`.git`、OpenSpec 历史和其他用户目录不在范围内；删除不可恢复。没有启动 Provider、SSH、Slurm、
HPC、容器、浏览器或 live campaign。

## 删除前观察

- 数据库：device `65024`、inode `33816859`、mode `0600`、size `3170304`、digest
  `sha256:a7e48fb773729e21b649f141e3e175490a6b0d374f13ae08d954c212946a8cd8`；
- WAL：inode `33816860`、size `0`、digest
  `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`；
- SHM：inode `33816862`、size `32768`、digest
  `sha256:fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb`；
- repository-service root：device `65024`、inode `33200626`；树内没有 symlink、mount boundary、FIFO、
  socket 或设备文件；
- SQLite 只读 inventory 为 `fresh_empty_candidate`：Session、continuation、unsettled operation、active lease、
  workspace pin、HPC qualification 和全部业务 owner rows 均为零；
- 没有上述文件的打开句柄，也没有识别到 OpenZyme Host/runner writer。

命令在 mutation 前重新核对三个文件的 device/inode/content digest、repository root device/inode、特殊文件和
打开句柄；只删除四个绝对目标并检查路径不存在。没有 backup 或 rollback 副本。

## Fresh EnzymeDesign bootstrap

- Distribution：`enzymedesign@0.1.0`；manifest
  `sha256:2be0633d46e82f6dce8cd8656e9d8f302a82d9a1216e61fe20b382a93d0eccf1`；
- 最终 31-wheel closure：`sha256:0f6ba72188879b52a0741897c273301f8b7ce619d75aae5ee1ece1f5179dc095`；
- Host wheel：`sha256:12876519c89bed6e4af2d6e2f2717fdf87e67d23966738186639a0571c18c775`；
- Client wheel：`sha256:15d452dfbcae95de00d70a9c5f93ac649206d4f54b17566b68940aefc10da3b9`；
- epoch `enzymedesign_fresh_20260821_3`，sequence `1`，actor `operator_local`；
- schema `openzyme_store_sqlite_composite@3`，SQLite `user_version=3`；schema manifest
  `sha256:26c135f9a1eab037aef054d77e1737d3d1af4f2304c7355fac4f3600eab1b48f`；
- bootstrap receipt `sha256:85949e0a6f2bb66e7eef7953bb47f94fea784d353c8dbeb137153e64d1a88d1b`；
- deployment proof `sha256:7fd0df1d4278229db3fc8afd83619cf8c83b454115078ba547f639ce8239e874`；
- activation `sha256:b5120ec4a2f8e82370cf387aec1460bb73c67dfdfc6619ad6fd975580a54f476`；
- extension bundle `sha256:b4817f91222ba786eca64c800a532ea43877091ceac771852ba15fe5a67cb9dc`；
- workspace backend `sha256:99bb32be534b0ca9e1e7ea15102c1b35342ca3591d324c0364135a278c7a08b3`。

最终数据库 inode `33816860`、mode `0600`、size `3649536`，digest
`sha256:f493b7ee6560cbe4da4a019c585b8beb4c77ba12601562215b4e58571945f7a4`；WAL/SHM 不存在。156 张应用表
全部为零行，legacy schema/storage 标志均为 `false`。

repository-service 重新建立为 owner-only 空根：service、Git、LFS 和独立 backup root 均为 `0700`，Adapter
writable/fsync/delete preflight 通过。没有创建 bare repository、binding、ref、LFS object 或 Session pin；后续
必须经显式 project binding 创建，不能恢复旧 service。

## 独立验证

最终 exact 31 wheels 在隔离 Python 环境安装并完成 no-external-I/O import probe。另一个使用该隔离 wheel 环境的
immutable/read-only SQLite 进程重建同一 seed，得到相同 activation，且 `quick_check=ok`、
`query_only_total_changes=0`、`session_count=0`、`application_row_count=0`，deployment variant 为
`fresh_install_complete`。

## 不能补造的 reset receipt 边界

删除发生时，文档所称的 Store-owned `@2` reset executor 实际缺失：旧 Core 模块已删除，但新 owner 尚未落地。
因此本次删除虽有精确顶层 identity、无句柄、post-delete absence 和独立 fresh-bootstrap 证据，却没有在第一次
mutation 前生成完整 `device_fresh_install_reset_inventory@2` 与逐路径 durable occurrence log。

实现缺口随后已在 `openzyme_store_sqlite.device_fresh_reset` 修复，并补 `@2` owner/Distribution/exclusion/receipt
字段和测试。为使最终数据库绑定包含该修复的 wheel，后续空数据库替换已完整经过 frozen inventory
`sha256:36876be5272d5023f040a22b361f80e9d4514e29af81b83cb4e517aa5f3501fe`、quiescence
`sha256:9969bcc7960cabe6edcf48485f9f16bfe686bfa39330e1cc34221c1534868e0f`、durable occurrence、fresh bootstrap
和 zero scan，并生成有效 reset receipt
`sha256:97596780ae6fe6ac9918ea8200209135aebcabc6b22e7a19da33422125b64b89`。

该正式 receipt 只覆盖后续空数据库替换，不能追认最初已删除的旧 repository 子项；本文件也不能转化为那次
原始删除的 receipt。最终 fresh-bootstrap/deployment proof 与后续数据库 reset receipt 有效且可独立复算，但完整
原始 device reset receipt 仍未证明，task 18.9 保持未勾选。
