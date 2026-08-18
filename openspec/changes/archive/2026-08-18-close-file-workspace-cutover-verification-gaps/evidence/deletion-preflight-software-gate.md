# 删除前软件 gate 证据

状态：通过。该证据只允许进入本机只读 inventory/quiescence 阶段，不直接授权任何删除或 live effect。

## Source identity

- HEAD：`b841ba01eaa0cd2dc32f8a54dc0adbaae25cdfdf`
- authoritative mainline source identity：`sha256:85dbbadd26a79b16c6d6092e16e0643b5116c74d7940e2fd84c5aed0f7130e0a`
- final schema SQL：`sha256:7c963413c60b7f6791e19c68f5b0e235fee9985f5514baed05e2d158bb74e167`
- startup verifier：`sha256:0ae32b94ba9752ed47fd8e8c8d2f1d4726a4b2f24b0a85996e4114f4061e73a8`
- deployment proof：`sha256:6f489069611e7f87a6ef14eee3176beafada8c35df099aaacec0986cc9f0c99f`
- offline remover：`sha256:5220f50640478e5978197615e659d87b6f007ddf43813c17e65cf166067326ea`
- offline removal contract：`sha256:752c3f3e533cfd3e744283050488f8efabf810866596669cc9a28094a6141b9f`
- test resource manifest：`sha256:8c2c3a75bb350d6d8ac15728be145dff68876aa0556b6397dad783371b9aa325`

本记录生成后对 OpenSpec checkbox/evidence 文本的编辑不改变以上 production/schema/operator 文件
identity。若其中任一文件在设备 reset 前变化，删除前 gate 失效，必须重跑第 10 组。

## Direct behavior

- exact focused Python selection：wire/domain/runner/Host/authority、diagnostics、agent Git recovery、
  publication、handoff cleanup、migration/offline removal、scientific finalization、static audits；
  `154 passed in 49.96s`。
- Web UI：`npm test` 的 client/controller/file_workspace/state/view 五套测试全部通过；`npm run build`
  通过。
- 全量 non-live Python：
  `uv run pytest -q -m "not integration and not live_llm and not live_tavily and not live_hpc and not live_e2e and not seeded_live_smoke and not quality_eval"`；
  `1463 passed, 3 deselected in 211.37s`。
- fresh/offline 独立 proof 六项：deterministic bootstrap、合法非空 restart、variant isolation、complete
  offline ledger、same-ledger partial resume、unknown absence rejection；6/6 通过。

全量首次运行发现 fresh startup 错误地要求产品表永久为空，结果为 `1460 passed, 2 failed, 3
deselected`。修复后 bootstrap-time empty proof 与 restart-time receipt/variant verification 已分离，原
repository restore 两项和全量 gate 均通过；该失败没有被静默忽略。

## Static/OpenSpec/architecture

- `openspec validate --changes --strict --json --no-interactive`：17/17 active changes valid；PostHog
  network noise 不进入结果或 digest。
- retired surface：239 current files，0 violation，0 scan error，report
  `sha256:0915e883f5bc16de027fe9bcbdc8f60f0604cf45079fc81585ae82da05a140f7`。
- production exception：21 cutover modules、45 broad handlers，0 violation，0 scan error，report
  `sha256:3070af36ff75dc90d6f3ebb5ffd8f1c4de8e3bbaa53eaab27d27a55674d634a4`。
- full diagnostic qualification：19 scenarios，通过 pure verifier；payload
  `sha256:a1cc5fb4b299ce5b7af12d1c1676dd7f9e18c7a4373498e6a54adf7bc3095a70`。唯一 rejection 是
  `mode_not_admission`、`source_not_clean`，不声明 admission。
- authoritative mainline：plan
  `sha256:b494384b5f61b7af897c2dc3a38ae6aa03389badf5737097c8af33be3dd26239`，receipt
  `sha256:6fc03bec4490df8bbdb912d8a7dc6116dd944bf3cf4df16d49266b23e5c61892`，
  `terminal_status=pass`，并由同一公开入口独立验证。

mainline 首次在测试前因 `core_bio_research_tools_worker_local` collection digest drift fail closed；根据
当前 1463-node shadow collection 重新生成 19-entry resource manifest，变化仅对应本次修改的 bio、
migration、Host security 三项，资源门禁 19/19 通过后 mainline 才重跑并通过。

## 明确排除

未运行 live provider、真实 SSH/Slurm/HPC、Chrome、AOX campaign、push 或 PR。qualification diagnostic
和 mainline receipt 都不授予这些 authority，也不替代设备 inventory、quiescence、逐项删除或 fresh-reset
receipt。
