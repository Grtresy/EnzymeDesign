# Non-live completion evidence contract

## Evidence boundary

本文件是 completion evidence 的仓内覆盖索引，不是运行时 authority，也不保存可复用的绿色
receipt。最终命令的 canonical report/receipt 必须在本文件和 `tasks.md` 固定后从 exact final
source 生成到 checkout 外，并在交付说明中记录其路径与 digest。运行后再修改 source、配置、文档、
OpenSpec 或 manifest 会使这些外部证据过期，必须整组重跑。

2026-08-21 已获单独授权并执行本机旧空数据库/repository-service 删除和 EnzymeDesign fresh bootstrap；
独立 deployment proof 见 `operator/device-fresh-install-20260821.md`。删除先于缺失的 Store-owned `@2`
reset executor 修复，未生成旧 repository 子项的完整逐路径 frozen inventory/occurrence log，不能补造该次
receipt；后续空数据库替换已生成有效 `@2` reset receipt。task `18.9` 仍保持未勾选。Provider、SSH、Slurm、
HPC、容器、浏览器和 live campaign 均未执行。

## Frozen implementation surface

最终 source-bound architecture inventory 必须同时满足：

- 37 个 active components；
- 106 条 active import edges；
- component inventory digest
  `sha256:beeee89137dfa6590ca7de6d27a19bec9c923da68d57a61c7e6988c38ca3c8a7`；
- import graph digest
  `sha256:6554ed007f306d1b2a30a2bce661bacad5ab3d4886bd857dd8d303ba07b293d2`；
- catalog digest
  `sha256:99d6092a80652d4c8a2373f2d0b280771e2c458118aeca3638e316196ef5f518`；
- 147 tables、134 indexes、674 triggers、422 foreign keys；
- table owner digest
  `sha256:7c432ca2af823bbee03725bd1b7223dbad25045e0f5436441bf230d557fb8334`；
- `temporary-reexport-ledger.json.entries == []`，旧 mixed packages 不在 workspace、wheel、entry
  point 或 active import graph；
- generic Kernel/Host/Standard source 中没有 AOX、HMMER、Vina、fpocket、AlphaFold、RDKit、
  Meeko、Biopython、Slurm 或 Tavily 垂直 dependency；
- 当前在线公共合同只有 `file_workspace_public@2`，`@1` 只有显式 offline historical reader，
  不存在 dual-write、online translation、per-Session legacy mode 或 automatic conversion。

## Required final command closure

以下命令必须全部基于同一 final source 成功，且执行顺序中不得插入 source mutation：

1. `python3 scripts/check-openzyme-architecture.py`；
2. `.venv/bin/python scripts/qualify-openzyme-contract-wheels.py`（offline wheelhouse）；
3. `./scripts/check-v3-architecture-qualification.sh diagnostic <new external dir>`，随后以
   `.venv/bin/python scripts/verify-v3-architecture-qualification.py <report>` 独立验证；
4. `./scripts/check-mainline.sh`，随后由脚本自身执行 pure authoritative verifier；
5. `uv run python -m openzyme_host_api.evals`；
6. `openspec validate separate-openzyme-kernel-from-capability-extensions --type change --strict
   --json --no-interactive`。

三 profile qualification 必须是 report schema `openzyme_v3_architecture_qualification_report@4`，
27/27 scenario 为 `satisfied`，27/27 invariant 为 `satisfied`，零 skip/xfail、零 undeclared
external effect、零 not-run、`external_effects_real=false`、`live_campaign_started=false`、
`run_failure=null`。dirty checkout 的 diagnostic report 必须且只能因 `mode_not_admission` 与
`source_not_clean` 不具备 admission authority；这不允许被解释为真实 cutover proof。

wheel qualification 必须在 fresh Python ≥3.12 environments 验证以下闭包：

- Contracts + SPI only；
- Kernel only；
- Plugin-free Standard only；
- runner only；
- EnzymeDesign component set。

mainline 必须让 lint、compatibility audit、premerge architecture qualification、完整 non-live
pytest、Web UI tests 和 Web UI build 全部为 `pass`。OpenSpec strict validation 的 authoritative JSON
必须为 `valid=true`；PostHog telemetry 的网络失败不参与 acceptance。

## Requirement and documentation closure

`requirement-evidence.md` 将 18 个 delta specs 的全部 162 个 requirements 映射到直接 source、test
和 document owner bundle，并固定 12 个 qualification families/27 个 required scenarios。最终审计还必须
确认：

- `docs/OpenZyme架构设计.md`、相关 `docs/v3/`、package/app README 与实际 owner/path/command 一致；
- OpenZyme Standard 是 Distribution，不是语义层；Adapter、Plugin、Driver 与 Distribution 不混用；
- HMMER/Vina 等领域 Plugin 通过 capability requirements 和 resolved route 使用 HPC，不 import
  Slurm/SSH internals；
- Workspace Runtime 由 Kernel 定义 contract/authority/receipt，Local/Podman/SSH 实现位于 Adapter，
  HPC workspace lifecycle 位于 HPC Plugin，scheduler 永久与 login/file authority 分离；
- Agent 保留策略自由；Shell/CRUD 或 job success 不自动形成 publication、Science adoption 或
  `task.finish`。

## Archive condition

只有上述 exact final external evidence 生成并经独立 verifier 验证后，task `18.10` 才可视为完成。
本 change 不在本次实施中 archive，也不因为 OpenSpec artifacts 为 `done`、单一绿色 gate 或旧 receipt
而提前宣称完成。task `18.9` 的 fresh activation 已执行并验证，但 device reset receipt closure 仍未证明；
它不阻止 non-live implementation closure，交付中必须明确区分这两个结论。
