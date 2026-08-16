## Why

当前 AOX 等长链科学 workflow 把“实际发生过的 operation 集合”与“agent 最终采用的科学链”绑定为同一个集合：一次已知、可闭合的中间失败也会永久毒化整个 formal attempt。要在不降低最终证据门槛的前提下允许中间试错，control plane 必须保存完整 occurrence universe，并让 agent 显式选择、处置和关闭唯一 adopted chain。

## What Changes

- 增加 append-only、可 CAS 的 scientific chain selection：保留完整 operation universe，同时要求每个 occurrence 有 `adopted`、`superseded`、`failed` 或 `abandoned` disposition。
- 增加同一 formal attempt 内的 effect adoption 与 Host-supervised artifact materialization；只允许采用 effect 已知、bytes 可重验、权限有效的结果，禁止跨 formal attempt、campaign、positive/fault scope 复用。
- 增加独立 attempt closure：只有 selection 完整、全部 operation 已处置、未知 effect/活动进程/未决 authority 已清零且 quiescence receipt 有效时才能 seal；known closed failures 不再自动毒化 attempt。
- 增加 durable fresh-attempt authorization envelope，约束 attempt 数、MICU/成本/时间、effect class、provider/HPC target 和 expiry；agent 可在 envelope 内创建新 formal attempt，越界则请求用户/操作者授权。
- 未知 external effect、未闭合 operation、权限/预算越界仍 fail closed，且不能通过新建 attempt 绕过。

## Capabilities

### New Capabilities

- `scientific-attempt-selection`: operation universe、disposition、effect adoption、artifact materialization、selection revision 与 attempt closure。
- `fresh-attempt-authorization`: durable attempt authority envelope、原子额度消费、expiry 与越界请求语义。

### Modified Capabilities

- `controlled-operation-execution`: controlled execution outcome 必须可被 selection/disposition 引用，并以 effect certainty 限制 adoption、replacement 与 retry。
- `host-quiescence-sealing`: attempt closure 必须消费 scope-bound quiescence receipt，但 quiescence 本身仍不代表科学成功或 task 完成。

## Impact

- 影响 `packages/openzyme-domain`、`packages/openzyme-core` 的 canonical 对象、repository、migration、service、tool、projection 与 consistency audit。
- 影响 artifact boundary 的授权 materialization，以及 Host API/CLI/Web UI 的 attempt authority、selection、disposition、closure 命令和读模型。
- 为 AOX 提供通用 control-plane seam，但不把 AOX branch logic 下沉到 Harness，也不改变 LangGraph/Deep Agents 的顶层所有权边界。
- 需要新增规格、迁移、单元/契约/故障测试，并同步主架构与 `docs/v3/`。
