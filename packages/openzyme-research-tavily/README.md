# openzyme-research-tavily

这是 `openzyme.research.provider@1` 的 Tavily Adapter，不增加 Research canonical schema。

- manifest 的 `required_contracts` 显式绑定 owning `openzyme.research@1` 和 Provider Port；
- 配置只保存 `secret_locator`，secret material 由注入的 credential resolver 在 dispatch 时取得；
- 单次 provider dispatch 绑定 ControlledOperation identity；timeout/response loss 为
  `dispatch_in_doubt`，不得自动重发或改用 Browser；
- 公开 receipt 只包含安全 provider/operation/digest/source facts，不包含 API key；
- EnzymeDesign Distribution 将该 Adapter 作为 `required = false` 的显式选择。wheel 安装或 entry point
  discovery 本身不会启用它。

`TavilyResearchAdapter` 实现 Research Provider Port；Plugin runtime 只消费 `ResearchProviderPort`，不依赖
Adapter package。Distribution/Session 是否选择该 optional route 由 exact composition/binding 决定；本 change
没有执行 live Tavily。
