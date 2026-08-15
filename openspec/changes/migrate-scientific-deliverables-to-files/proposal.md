## Why

scientific materialization、selection、attempt closure 和 AOX 17-role bundle 仍以 artifact id/kind/catalog publication 为身份；只迁普通 research/report 会留下第二套顶层文件真相。科学语义必须在不削弱 attempt/selection/verification 的前提下迁到 exact revision/path/LFS bytes。

## What Changes

- 新增 `ScientificDeliverableRef`，绑定 project repository、published revision、normalized path、Git blob 或 LFS OID/size、role、producer operation/attempt、selection 和 digest。
- AOX 17 件 deliverables、candidate/finalizer、bundle manifest 和 offline verifier 改为从 Git/LFS bytes 重算，不再创建或读取 current artifact records。
- scientific attempt closure、selection/adoption、cross-attempt reuse guard、approval 和 GO/NO-GO 语义保持不变；文件迁移不能机械关闭 task/attempt。
- current superseded AOX campaign 的 migrated legacy bytes 只能作为 historical import，不能满足 fresh workflow pin、attempt authority 或 cutover evidence。
- 新 AOX cutover 必须在本 change 完成后建立 fresh OpenSpec、fresh source/config pin 和 fresh live authorization。
- 不保留 dual writer、artifact compatibility projection 或按扩展名猜 kind 的 fallback。

## Capabilities

### New Capabilities
- `file-scientific-deliverable`: 定义科学交付物的 revision/path/LFS identity、lineage、selection、closure 与 offline verification。

### Modified Capabilities

## Impact

影响 scientific domain/repositories/migrations、AOX finalizer/validators/evidence export、provider/HPC output integration、task evidence、Host API/evals 和稳定 AOX 文档。
