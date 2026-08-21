# enzymedesign-bio-providers

该产品插件拥有 UniProt、RCSB PDB 与 InterPro 的产品能力身份、路由和运行时桥接，
但不拥有 HTTP 实现。实际网络访问由显式选择的
`enzymedesign.bio-provider-http` Adapter 实现。

插件只返回 Provider 事实或私有下载载荷；它不会发布 revision、采纳科学证据或
完成 Task，也不会自动重试、切换 Provider 或选择替代 route。
