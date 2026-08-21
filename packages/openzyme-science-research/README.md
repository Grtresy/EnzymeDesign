# openzyme-science-research

这是显式组合在 `openzyme-research` 与 `openzyme-science` 之上的科学文献能力，拥有 PubMed、
Semantic Scholar 的来源语义和 literature quorum。它不属于 Kernel，也不改变 Research 的通用
request/source/evidence schema。

基础 Research 不会自动调用本插件。Provider 缺失、降级或 schema drift 会形成对应 quorum member；
实现不得把 Tavily、Browser 或其他来源当作隐式替代。fixture 只验证控制流，不能形成 cutover evidence。

UniProt、RCSB 与 InterPro 已不在本包中：其产品 capability/route 由
`enzymedesign-bio-providers` 拥有，稳定 Port/DTO 位于 `enzymedesign-core`，网络机制由
`enzymedesign-bio-provider-adapters` 实现。`legacy_bio` 只保留尚待后续改名的文献 Provider
实现，不再包含任何生物数据库 DTO、HTTP endpoint 或 fixture。
