# enzymedesign-bio-provider-adapters

该 Adapter 实现 `enzymedesign.bio-provider@1`，提供 UniProt、RCSB PDB 与
InterPro 的有界 HTTP 读取。每个请求只向显式 Provider endpoint dispatch 一次；
连接状态不明时显式失败，不自动重试、不切换 Provider，也不写 workspace 或 Core
状态。

`DeterministicBioProviderAdapter` 仅用于 non-live qualification，返回的所有记录都
带 `fixture_non_cutover` 标记，不能成为 cutover 或科学采纳证据。
