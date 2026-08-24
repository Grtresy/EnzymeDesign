# Vina route/version 决策包（2026-08-23）

## Operator 决策

已批准 **D-V1：显式双 profile**。Diannan HPC 固定 Vina `1.1.2` 与 legacy `--log` 合同；本地固定
`>=1.2,<2` 与 modern CLI/result 合同。禁止自动切换、运行时探测式改写、retry-as-fallback 或 target fallback。

## 决策时事实

- 决策前 `enzymedesign.vina` 的 Plugin、workload contract 和两个 Driver 统一声明 `software.autodock-vina >=1.2,<2`。
- `VinaDriver` 不区分 route kind，统一编译 `vina ... --out <poses> --log <score>`，result contract 要求 `poses_path` 与 `score_path`。
- 本地 repository-owned image 精确为 Vina 1.2.7；首次真实 occurrence 已证明该 CLI 拒绝 `--log`，返回 `Command line parse error: unrecognised option '--log'`。
- Diannan `/home/grtresy/containers/vina.sif` 的只读版本观测为 Vina 1.1.2；它与当前 `>=1.2,<2` 声明不相容，但 legacy CLI 与现有 `--log` workload shape 相容。
- 当前 Podman/Slurm scientific qualification routes 只验证声明的文件产物；Podman 丢弃 bounded stdout，Slurm 把 stdout 写入 scheduler 文件但没有将其投影为 Driver result artifact。因此删掉 `--log` 而不改变 result semantics 只会把“进程失败”变成“score artifact 缺失”。

## D-V1：显式双 profile（推荐）

保留一个产品级 `software.autodock-vina` capability，但把实际执行合同按 exact Driver/route 固定为两个不相交 profile：

| route | exact version policy | argv/result profile |
| --- | --- | --- |
| `enzymedesign.vina.hpc-primary@1` | `==1.1.2` | legacy `--log`；poses + log 均为 required artifact |
| `enzymedesign.vina.local@1` | `>=1.2,<2` | modern，不使用 `--log`；从 poses PDBQT 的 `REMARK VINA RESULT` 形成经过 validator 的 score artifact/fact |

必要实现：

1. Plugin 顶层 requirement 表示被支持版本的闭包，但 route admission 必须采用 Driver-specific version policy；不能只靠较宽的 Plugin range。
2. `VinaDriver` 根据自身 manifest 的 exact `route_kind` 编译固定 profile，绝不根据运行时探测结果猜测或重试另一个 argv。
3. result contract 分离并显式记录 exact `vina_result_profile` 与 `score_semantics`；两类输出都由 Driver validator 校验，不能把 stdout 文本直接当正式结果。
4. qualification compiler、target inventory、subject digest、workload/result contract digest 和 receipts 全部绑定对应 profile。
5. local/HPC 任一路版本或 profile 漂移只产生 `blocked_qualification`；不得自动切换另一路。

优点：不修改 Diannan 已安装工具，也保留本地 modern Vina；版本差异成为显式架构事实。代价：需要 result contract/validator 的受控升级，并重新封存两个 Driver digest。

## D-V2：统一采用 1.1.2

把全局 version requirement 改为 `==1.1.2`，本地 qualification image 也改为固定 1.1.2，两个 route 继续使用 legacy `--log` profile。

优点：workload/result shape 最简单。代价：主动放弃当前本地 1.2.7，扩大 legacy 科学软件依赖；需要新的本地 image preparation authority，且不能把“Diannan 已安装”本身当作降低产品版本要求的充分理由。

## D-V3：统一采用 modern `>=1.2,<2`

保持现有版本下限，由 operator 在 Diannan 私下提供 compatible SIF；同时仍需修改 Driver/result contract，使 modern CLI 不依赖 `--log`，并为本地和 HPC route 都形成正式 score artifact。

优点：版本策略统一。代价：需要外部 target state 变化；在 compatible SIF 出现前 HPC Vina 持续 blocked，并不比 D-V1 少做 modern result semantics。

## 实施与授权边界

源码已按 D-V1 实现 route-owned resource requirements、Kernel exact target/version admission、两个 Driver profile、
分离的 workload/result digests、modern poses remark extractor 和 profile-sensitive terminal validator。该批准只授权
上述仓内合同实现，不授权本地 image rebuild、SSH/Slurm/scientific effect 或 cutover。必须从新的 source seal 生成
effect-free discovery、preparation plan、dry plan 和各自独立 authority；旧 `ae24...b776` plan/authority 永久不可复用。
