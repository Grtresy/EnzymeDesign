# Phase 0 Legacy Baseline and Shadow Closure

测量日期：2026-07-29。本文只记录 repository/operator-plane 性能与 coverage 证据，
不授予 merge、architecture admission、AOX、live campaign 或 scientific evidence
authority。测量期间 `scripts/check-mainline.sh` 保持字节不变。

## Identity

- source commit：`1582f86552292e20fe77560ef232f8bea84622f5`
- exact source identity：
  `sha256:c7300429b826fa49880ef1130e54932f44dfe3ecf3265bf1071089f54eecb382`
- tracked diff：空；tracked dirty paths：`0`；相关 untracked source：`24`
- host fingerprint：
  `sha256:764a70cf3a44ad5d35c053abac6aaef76bb9e932ca2d937dafac7189e0d7f110`
- host：Linux `6.1.0-30-amd64`、x86_64、16 logical CPUs、33,582,260,224 bytes
  memory
- toolchain：CPython `3.13.9`、Node `v24.12.0`、uv `0.9.5`、npm `11.10.0`
- cache control：`process_only`；没有声称清空 OS page cache

## Five Paired Legacy Samples

每个样本都从新的 process group 和 checkout 外 no-replace output root 启动，并直接执行
当前 `./scripts/check-mainline.sh`。十次运行全部 functional green，五对 source、host、
toolchain、command 和 collection identity 全部闭合。

| Distribution | Median | MAD | Min | Max |
| --- | ---: | ---: | ---: | ---: |
| cold | 860.138 s | 0.451 s | 858.631 s | 861.029 s |
| warm | 859.741 s | 0.754 s | 858.725 s | 862.140 s |

warm median 只比 cold median 快 `0.398s`，约 `0.05%`。当前长耗时不是一次性
Python/OS cache cold start。

## Stage Attribution

同 source 的 exact-command diagnostic stage run 总计 `863.015s`：

| Stage | Wall time | Cold-median share |
| --- | ---: | ---: |
| Ruff source | 0.032 s | 0.004% |
| Ruff audit script | 0.032 s | 0.004% |
| compatibility audit | 22.957 s | 2.669% |
| architecture qualification `premerge_subset` | 110.800 s | 12.882% |
| general non-live pytest | 728.814 s | 84.732% |
| Web UI tests | 0.214 s | 0.025% |
| Web UI build | 0.166 s | 0.019% |

pytest 自报 `727.41s`，进程级额外开销约 `1.40s`。qualification report 内部记录
collection + harness `41.772s`、13 个 selected scenarios 合计 `52.071s`。

## Exact Collection and Duplicate Cost

五次独立 closed shadow collection 得到完全相同的 canonical digests：

- `G = 2690`
- `Qh = 81`
- `Qs = 13`
- `Qh ∩ Qs = ∅`
- `Qh ∪ Qs ⊂ G`
- legacy execution multiset：`2784` entries
- distinct required set：`2690` nodes
- structural duplicates：`94` nodes
- general collection：
  `sha256:be9caf6d2db453dcfef8b492cde855886002c9a8582bbfdc92a77e1fd6082eac`
- distinct coverage：
  `sha256:37108a619089d0915911531b1ea7895346248909187d0acb27c96b741981ca32`

一次同 source 的 observed general run 执行 `2690/2690` nodes，全部 pass，墙钟
`727.055s`，node durations 合计 `723.751s`。94 个 qualification-owned 节点在 general
run 中合计占 `91.684s`：

- 81 个 harness nodes：`39.703s`
- 13 个 scenario nodes：`51.980s`

因此 same-invocation exact node-id dedup 的串行直接收益估计为 `91.684s`
（cold median 的 `10.659%`）；qualification 的严格执行与 canonical report 仍保留。

## Critical Paths and Lower Bounds

当前最慢节点包括：

1. `test_v3_local_eval_covers_cutover_design_path`：`57.272s`
2. `test_current_compatibility_decisions_are_evidence_backed`：`22.728s`
3. `test_v3_glm51_default_window_budget_boundaries_via_message_loop`：`13.810s`
4. `test_v3_background_runtime_runs_teammate_and_master_followup_without_manual_drain`：
   `8.924s`
5. qualification boundary-scale scenario：`8.562s`

按测试模块累计，`apps/openzyme-host-api/tests/test_api.py` 为 `136.938s`，
`test_evals.py` 为 `58.127s`，`test_aox_cutover_live.py` 为 `52.262s`，
`test_sandbox_runtime.py` 为 `38.574s`。

Phase 0 得出的边界：

- 仅 exact dedup 的串行投影约 `768.455s`（12分48秒）。
- 即使把 compatibility audit 的 `22.957s` 全部视为可消除，理论投影仍约
  `745.498s`（12分25秒）。
- `25%` 首次 authority cutover 阈值是 `645.104s`；dedup 后仍差 `123.351s`。
- 五次 shadow planning median 为 `4.851s`，占 legacy cold median `0.564%`，
  低于设计的 `5%` overhead ceiling。
- 因此 audit single-pass 与 exact dedup 必须做，但不能单独达到 `25%`，更不可能达到
  `5–7` 分钟；resource-audited fixed parallelism 和真实串行热点修复是必要后续。

## Evidence

- legacy paired summary：
  `sha256:e79b8579bbcbb32adeaa299ed6af0a72ac732bf0ad53849c3959201ded7eb1f1`
- stage attribution：
  `sha256:34e3804fe7f87fb4ab2d41f5e33d9d1a5479f3ef748c0479870868766bf89e00`
- observation binding：
  `sha256:f80b28a0e977013d0654d5a506d1aac4907ee46c9cc104e10edc3166dabf6b3e`
- closed Phase 0 report：
  `sha256:42881d95a50f592f9448618b548d4a0c241b65ef79768fa36878a920cf03dcd8`
- raw evidence root：`/tmp/openzyme-test-gate-*20260729*`

这些 host-local raw artifacts 只能验证上述 exact source invocation；源码、配置、toolchain
或 collection 改变后不得复用为新基线。
