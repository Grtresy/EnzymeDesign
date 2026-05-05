## 1. Runtime Decision State

- [x] 1.1 在 `packages/enzyme-host-runtime` 中定义通俗易懂的终止/暂停语义，至少覆盖 `completed`、`failed`、`needs_input`、`awaiting_approval`、`blocked`、`max_turns_exceeded`、`escalated`
- [x] 1.2 为 agent state 增加结构化进度摘要字段，统一表达“已完成什么、当前卡点、下一步建议、是否需要用户介入”
- [x] 1.3 为关键决策、暂停点和终止点增加双层解释字段，区分简明中文说明与技术解释
- [x] 1.4 扩展 approval / safety policy 输出，补充用户可读的审批说明和信任判断结果，并支持项目级细粒度规则配置

## 2. Shared Runtime Services

- [x] 2.1 让 `HostRuntime` 和相关 snapshot/API 返回新的进度摘要、停止原因、下一步建议和双层解释，并明确首版不包含 ETA 字段
- [x] 2.2 以向后兼容方式把这些新增字段写入 canonical project memory，而不是只存在于 Web 或 CLI 的临时拼装结果里
- [x] 2.3 为自动推进预算耗尽、缺少输入、策略阻断和升级处理补齐统一的状态转换逻辑
- [x] 2.4 为无需审批即可继续的动作保留可解释的策略说明，避免“直接通过但说不清原因”

## 3. Web Host Experience

- [x] 3.1 调整 `apps/enzyme-web-host` 主操作区域，优先展示当前状态、停下原因、下一步建议和是否需要用户介入
- [x] 3.2 为 Web Host 增加“简明说明 + 技术细节”两层解释展示，主区域说人话，调试区域看细节
- [x] 3.3 在审批和阻断场景中显示更直白的原因说明，而不只暴露内部 gate 字段

## 4. CLI Experience

- [x] 4.1 调整 `apps/enzyme-host-cli` 默认状态输出，优先展示简洁的决策状态摘要和下一步建议
- [x] 4.2 扩展 CLI 详细模式，输出技术解释、策略原因和与当前判断相关的关键上下文
- [x] 4.3 确保 CLI 在 `needs_input`、`awaiting_approval`、`blocked`、`max_turns_exceeded` 等状态下给出明确的人类可执行提示

## 5. Verification

- [x] 5.1 为 runtime 增加回归测试，覆盖预算耗尽、等待输入、升级处理、自动放行和待审批等状态语义
- [x] 5.2 为 runtime 增加回归测试，验证 progress summary、中文简明解释和 technical explanation 会被一致写入 canonical state
- [x] 5.3 为 Web Host 增加回归测试，验证主界面优先展示停下原因、下一步建议和简明说明
- [x] 5.4 为 CLI 增加回归测试，验证默认模式和详细模式输出的语义分层

## 6. Documentation

- [x] 6.1 更新相关 README 或开发文档，说明新的终止语义、进度摘要、项目级 trust policy 配置和双层解释字段含义
- [x] 6.2 用通俗语言补充 Host 操作说明，帮助开发者理解“系统为什么停下”和“用户下一步该做什么”
