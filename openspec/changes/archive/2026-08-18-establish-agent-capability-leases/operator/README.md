# C2 agent capability lease operator contract

本目录为 `establish-agent-capability-leases` 提供只读 prerequisite、authority、policy、scope
与最终 acceptance 的证据边界。最终发布前不预置 `acceptance-receipt.json`；源码冻结并通过
权威 mainline 后，只能由本目录生成器新增该 receipt。这里的测试 readiness、profile declaration
或矩阵均不是 production workspace、capsule、network、transfer、publication、remote HPC 或 job
proof。

## Canonical documents

- `prerequisite-bindings.json`：绑定已发布 C0/C1 acceptance receipts。C0 必须继续保持
  `legacy_no_go`；C1 的 `c1_acceptance_only` assertion/hold 必须继续声明
  `production_capability_lease_issuance_proven=false`。
- `authority-matrix.json`：闭合 capability、runtime、execution、mutation、approval 与
  scientific authority 的 owner/lifecycle/cross-product；不存在万能 budget owner。
- `capability-policy-v1.json`：闭合 general/executor profiles、role/profile、allowed-child-profile
  与 safe target-scope policy。ordinary deployment network 不使用 Host destination allowlist，
  但 Host-issued credential 仍严格绑定 exact service/target/protocol audience。
- `scope-boundary.json`：闭合 C2 staged cutover、`provisioning_required` non-runnable window、
  forbidden legacy fallback、deferred false claims 与唯一 production readiness successor C3。
- `verify_agent_capability_lease.py`：只读验证上述 documents；只有显式
  `--require-acceptance` 才要求最终 receipt。
- `capture_final_evidence.py`：在源码冻结、精确 focused tests、Ruff、strict OpenSpec 与
  authoritative mainline 全部通过后，由脚本亲自 collect 并执行冻结的 24 文件 pytest 集合、
  对 `apps` / `packages` / 本 operator 运行 Ruff，再从当前基线差异和该次 mainline 的原始
  plan/receipt 捕获一次性 sealed evidence；输出必须位于仓库外且不得覆盖已有文件。
- `generate_acceptance_receipt.py`：消费上述显式 canonical evidence bundle 生成唯一
  `acceptance-receipt.json`。两个脚本都要求完整 task checklist，不能从旧绿色结果猜测证据。

带自身 digest 的 JSON 都使用同一 canonical preimage：移除自身 digest 字段，以 UTF-8、key
排序、`(',', ':')` 紧凑分隔并设置 `ensure_ascii=false`，然后计算 SHA-256。数组顺序属于合同；
缺字段、额外字段、digest drift 或 prerequisite/source mismatch 直接失败。

## Current verification

验证 prerequisites、matrices 与 scope，不要求尚未生成的最终 receipt：

```bash
uv run python \
  openspec/changes/establish-agent-capability-leases/operator/verify_agent_capability_lease.py
```

在最终 receipt 尚未生成时，验收模式应因缺少 `acceptance-receipt.json` 明确失败；生成后同一
命令必须验证通过：

```bash
uv run python \
  openspec/changes/establish-agent-capability-leases/operator/verify_agent_capability_lease.py \
  --require-acceptance --verify-current-sources
```

最终收口时，先保留 `./scripts/check-mainline.sh` 输出的绝对 evidence root，再执行：

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python \
  openspec/changes/establish-agent-capability-leases/operator/capture_final_evidence.py \
  --mainline-root /tmp/openzyme-mainline-authoritative.EXAMPLE/evidence \
  --issued-at 2026-08-16T00:00:00+08:00 \
  --output /tmp/c2-agent-capability-final-evidence.json
PYTHONDONTWRITEBYTECODE=1 uv run python \
  openspec/changes/establish-agent-capability-leases/operator/generate_acceptance_receipt.py \
  --evidence /tmp/c2-agent-capability-final-evidence.json \
  --output openspec/changes/establish-agent-capability-leases/operator/acceptance-receipt.json
```

生成器写入前和 verifier 提交后都会复验同一 baseline→publication 路径集合、文件摘要、
mainline source identity、嵌入 plan/receipt 自封印及 final-evidence 摘要。路径集合必须精确等于
冻结的 implementation manifest，不再接受宽目录前缀；全部新增 production Python AST 还会审计
successor owner symbol、外部进程/网络/传输调用和 deferred product route。最终回执本身是唯一允许
在 mainline 之后新增的 change-scope 文件。

下面命令只验证 operator 自身实现，不构成 C2 完整 focused receipt：

```bash
uv run pytest -q \
  openspec/changes/establish-agent-capability-leases/operator/test_verify_agent_capability_lease.py
uv run ruff check \
  openspec/changes/establish-agent-capability-leases/operator/verify_agent_capability_lease.py \
  openspec/changes/establish-agent-capability-leases/operator/capture_final_evidence.py \
  openspec/changes/establish-agent-capability-leases/operator/generate_acceptance_receipt.py \
  openspec/changes/establish-agent-capability-leases/operator/test_verify_agent_capability_lease.py
```

完整 focused pytest 与 Ruff 的唯一 canonical evidence owner 是上述 `capture_final_evidence.py`；
它不接受人工 PASS count，collection node identity、JUnit 结果、命令、环境、Ruff 输出和 exact
implementation tree digest 均进入 final evidence。上述命令不创建 session、agent、lease、
credential、provider request、HPC connection、job、publication 或任何 external effect。C2
acceptance 只能在实现、focused validation、稳定文档、strict OpenSpec、authoritative non-live
mainline 与最终 scope audit 全部通过后生成；在此之前不得写 final source/mainline digest，也
不得把 test provisioner readiness 当作 production proof。
