# `f6ea16c` post-preparation packet 失效说明（2026-08-23）

## 被失效的 packet

- source commit：`f6ea16c01a0064139cfd17b8debafcabce4cf57d`
- source identity：`sha256:d1dbb26a8aea73e7badb71fdd8914e4fb3a2ad8b79be9ecc58308566c8b81e86`
- packet：`sha256:d58580d31cfe05e572ba4afffecabf8c4249b970009469e0d9bd2f3fa29db802`
- Batch 1 dry plan：`sha256:56a8acdb256e85e66941bdd994cb2a586039cc174e2817a5bc4371e9485e4aee`
- 原始裁决：`prepared_not_qualified`，`batch_1_authorizable=false`，`qualified=false`，`cutover=false`

## 失效原因

该 packet 已能识别 Diannan Vina `1.1.2` 不满足声明版本，但当时的 effect-free rediscovery 只消费了本地 immutable image digest，没有强制把当前 repository-owned recipe digest 纳入 safe subject identity。因此源码已修改 docking recipe、旧镜像仍存在时，packet 少报了本地 image recipe drift。

## 约束

该 packet 只保留为历史诊断，不得作为任何 preparation 或 qualification occurrence authority 的输入，也不得补强旧镜像。后续必须从包含 recipe-digest 校验的 clean source seal 重新发现；缺失 recipe digest 标记为 `partial`，不一致标记为 `drifted`。需要建设的新 recipe 使用新的 output image ref；禁止覆盖、重标记、删除旧镜像或将其作为 fallback。

本说明不撤销或改写任何历史 terminal occurrence，也不产生新的 live、qualification、adoption 或 cutover authority。
