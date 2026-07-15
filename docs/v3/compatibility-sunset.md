# V3 Compatibility Caller Evidence and Sunset Gates

本文件记录 V3 当前兼容边界的退役证据与禁止误判的规则。可重复执行的仓库内证据由：

```bash
uv run python scripts/audit-v3-compat-callers.py
```

生成；日常 gate 可追加 `--summary` 只输出计数和错误。输出 schema 是 `openzyme.v3.compat-caller-audit.v1`；出现 parse error、已退役 seam 的 production caller，或声明为 active/compat 的实现路径消失时命令非零退出。审计覆盖 Python AST、前端/配置源码、TOML entrypoint 与受控文档，不读取 secret，也不把“仓库内零 caller”伪装成“外部零 caller”。

`scripts/check-mainline.sh` 在默认 pytest 和前端 gate 前执行该审计；任何已退役 surface 的 production 回流会直接阻断主线验证。

## 决策语义

- `KEEP`：当前 production composition、公开入口或 authoritative implementation 仍依赖，不能删除。
- `DEPRECATE`：新代码不得扩张，现有迁移面继续受测试和文档约束；外部 caller 仍未知，尚无删除授权。
- `RETIRE-BLOCKED`：仓库内可能只剩 re-export/test 或已无 production read，但它是已发布 Python/CLI surface；必须取得外部调用方证据后才能做 breaking removal。
- `RETIRED`：产品面已经不存在；审计器只做防回归，不代表要删除归档证据。

## 2026-07-16 checkout 结论

| 边界 | 决策 | 当前事实 |
|---|---|---|
| `PodmanPipelineSandboxRunner` | KEEP | Host 仍为迁移 `execution.pipeline.*` composition，engine re-export/tests 仍在；不能当成无 caller legacy 删除 |
| `RuntimeFoundation`、`ExecutionAdapter` | KEEP | Host foundation 与 execution adapter 的 active shared seam |
| `openzyme-tools` catalog/registry | KEEP | Host foundation 与 execution implementation 的 authoritative caller |
| `HpcRunnerExecutionAdapter` | KEEP | Host foundation 的 runner adapter；opaque run id 只收紧生命周期参数，没有消除 adapter |
| runtime `RepoBackedHpcCatalogProvider` shim | RETIRE-BLOCKED | 主实现已在 `openzyme-tools`，runtime 仍公开 re-export；外部 import 状态 unknown |
| `LegacyFunctionToolRuntime` | RETIRE-BLOCKED | core router 仍包装未迁移的 function handlers，不能提前删除 |
| `DesignTool` / `DesignToolContext` | RETIRE-BLOCKED | 仓库 production 只剩公开 re-export，但外部 import 状态 unknown |
| `ToolSpec.to_openai_tool` | RETIRE-BLOCKED | provider compatibility catalog 仍有 production call |
| `execution.pipeline.start` | DEPRECATE | sandbox-first 是稳定 authoring path，但 engine runtime、migration/eval/projection 仍持有显式兼容语义 |
| `ExecutionOutcome.remote_run_dir` | DEPRECATE | DTO 构造仍写入；不得把该字段重新变成 agent/runner 授权边界 |
| `ExecutionOutcome.job_id` | RETIRE-BLOCKED | 仓库无 production read，但公开 DTO 的外部 caller 状态 unknown |
| raw runner `job_id` / `remote_run_dir` / `runspec` lifecycle call shape | RETIRED | active production caller 为零；opaque server handle 是唯一产品生命周期授权 |
| Host `/v1` / `/v2` product routes | RETIRED | active app/package route registration 为零；不得恢复旧产品面 |
| `legacy/v1` active workspace/import | RETIRED | 不在 root uv workspace，active app/package import 为零；归档树本身 KEEP |
| `openzyme`、`mcp-hpc-runner` entrypoint | KEEP | 当前公开主入口 |
| `enzyme` CLI alias | DEPRECATE | installed alias 仍存在且外部 caller 状态 unknown |

## 外部 caller 清零门槛

任何 `DEPRECATE` 或 `RETIRE-BLOCKED` 项都不能只凭本脚本的零结果升级为 removal。执行 breaking retirement 前，变更工件必须附上：

1. 已知部署清单、容器/服务启动命令、operator automation 与下游仓库的检索范围、时间和结果；
2. 若 surface 可观测，覆盖一个约定观察窗的调用 telemetry 或明确说明为何不可观测；
3. package/CLI/API owner 对下游名单和迁移通知的确认；
4. 删除前的反例测试、release note、替代路径和 rollback/恢复说明；
5. 重新运行本审计，确认 production caller 为零且 `external_status` 有可审计 evidence reference，不再是 `unknown`。

当前 checkout 没有可证明的外部 caller inventory 或 telemetry，因此本轮不删除任何 `DEPRECATE` / `RETIRE-BLOCKED` surface。允许纠正性 breaking change 不等于可以虚构外部清零证据。
