# 生物信息学 API 文档索引

本目录提供 OpenZyme 项目使用的生物信息学数据库 API 参考文档和可运行的 Python 示例代码。

## API 概览

### 结构与序列数据库

| API | 用途 | 认证要求 | 速率限制 | 文档链接 |
|-----|------|---------|---------|----------|
| [RCSB PDB](./rcsb_pdb/) | 蛋白质三维结构 | 无需认证 | 适度使用 | [详细文档](./rcsb_pdb/README.md) |
| [UniProt](./uniprot/) | 蛋白质序列与注释 | 无需认证 | 适度使用 | [详细文档](./uniprot/README.md) |
| [InterPro](./interpro/) | 蛋白质家族/结构域 | 无需认证 | 适度使用 | [详细文档](./interpro/README.md) |

### 文献检索 API

| API | 用途 | 认证要求 | 速率限制 | 文档链接 |
|-----|------|---------|---------|----------|
| [PubMed E-utilities](./pubmed-ncbi-eutilities/) | 生物医学文献检索 | 可选 Key | 3/秒 → 10/秒 | [详细文档](./pubmed-ncbi-eutilities/README.md) |
| [Semantic Scholar](./semantic-scholar/) | AI 增强学术搜索 | 可选 Key | 100/5分 → 5000/5分 | [详细文档](./semantic-scholar/README.md) |
| [bioRxiv/medRxiv](./biorxiv-medrxiv/) | 预印本服务器 | 无需认证 | 适度使用 | [详细文档](./biorxiv-medrxiv/README.md) |
| [Europe PMC](./europe-pmc/) | 欧洲文献数据库 | 无需认证 | 适度使用 | [详细文档](./europe-pmc/README.md) |
| [CrossRef](./crossref/) | DOI 元数据权威 | 无需认证 | 适度使用 | [详细文档](./crossref/README.md) |
| [OpenAlex](./openalex/) | 开放学术图谱 | 可选 mailto | 10/秒 → 100/秒 | [详细文档](./openalex/README.md) |
| [CORE](./core/) | 开放获取聚合 | 可匿名 / 注册后更高额度 | 单请求 5/10 秒、批量 1/10 秒 | [详细文档](./core/README.md) |

## 适用场景

### 酶设计文献检索

| 需求 | 推荐 API | 理由 |
|------|----------|------|
| 权威生物医学文献 | PubMed | 最全面的生物医学索引，MeSH 术语支持 |
| 高影响力论文分析 | Semantic Scholar | TLDR 摘要、引用分析、领域过滤 |
| 最新研究进展 | bioRxiv/medRxiv | 预印本，领先正式发表数月 |
| 开放获取全文 | Europe PMC / CORE | 全文 XML/JSON，PDF 下载 |
| DOI 引用信息 | CrossRef | DOI 元数据权威来源 |
| 学术图谱构建 | OpenAlex | 作者、机构、概念关联 |

### 蛋白质结构与功能检索

| 需求 | 推荐 API | 理由 |
|------|----------|------|
| PDB 结构查询 | RCSB PDB | 最权威的蛋白质结构数据库 |
| 蛋白质序列信息 | UniProt | 最全面的蛋白质序列与注释 |
| 蛋白质家族/结构域 | InterPro | 整合多个签名数据库的家族和结构域注释 |

## 快速开始

### 依赖安装

```bash
# 基础依赖（所有示例共用）
pip install httpx pytest responses

# 或使用项目 uv 环境
cd docs/API/<api-name> && uv run python examples.py
```

### 环境变量配置

```bash
# 可选：配置 API Key 以提高速率限制
export NCBI_API_KEY="your-ncbi-api-key"
export SEMANTIC_SCHOLAR_API_KEY="your-s2-api-key"
export OPENALEX_EMAIL="your-email@example.com"  # 用于 Polite Pool

# 可选：CORE 注册用户通常会拿到更高额度
export CORE_API_KEY="your-core-api-key"
```

### 运行示例

```bash
# 结构数据库示例
cd docs/API/rcsb_pdb && python examples.py
cd docs/API/uniprot && python examples.py
cd docs/API/interpro && python examples.py

# 文献检索示例（无需 API Key）
cd docs/API/pubmed-ncbi-eutilities && python examples.py
cd docs/API/semantic-scholar && python examples.py
cd docs/API/biorxiv-medrxiv && python examples.py
cd docs/API/europe-pmc && python examples.py
cd docs/API/crossref && python examples.py
cd docs/API/openalex && python examples.py

# CORE 示例（建议配置 API Key 或先查看当前 Swagger）
cd docs/API/core && python examples.py
```

### 运行 Mock 测试

```bash
# 无需 API Key，使用 mock 数据测试
pytest docs/API/*/examples.py -v
```

## API 对比

### 文献检索 API 功能对比

| 特性 | PubMed | Semantic Scholar | bioRxiv | Europe PMC | CrossRef | OpenAlex | CORE |
|------|--------|-----------------|---------|------------|----------|----------|------|
| 生物医学专精 | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐ | ⭐ |
| AI 增强摘要 | ❌ | ⭐⭐⭐ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 引用分析 | ⭐ | ⭐⭐⭐ | ❌ | ⭐ | ⭐⭐ | ⭐⭐⭐ | ❌ |
| 全文获取 | ❌ | ⭐ | ❌ | ⭐⭐⭐ | ❌ | ⭐ | ⭐⭐⭐ |
| 预印本 | ❌ | ⭐⭐ | ⭐⭐⭐ | ⭐ | ❌ | ⭐⭐ | ⭐ |
| 概念/主题 | MeSH | Fields | ❌ | ❌ | ❌ | Concepts | ❌ |
| 批量查询 | ⭐⭐ | ⭐⭐⭐ | ❌ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ |

### 认证要求对比

| API | 无认证 | 可选认证 | 必需认证 |
|-----|--------|---------|---------|
| PubMed | 3/秒 | 10/秒 (Key) | - |
| Semantic Scholar | 100/5分 | 5000/5分 (Key) | - |
| bioRxiv/medRxiv | ✅ 无限制 | - | - |
| Europe PMC | ✅ 适度使用 | - | - |
| CrossRef | ✅ 适度使用 | - | - |
| OpenAlex | 10/秒 | 100/秒 (mailto) | - |
| CORE | ✅ 有免费额度 | ✅ 注册后更高额度 | - |

## 注意事项

1. **速率限制**: 请遵守各 API 的速率限制，建议在请求间添加适当延迟
2. **网络连接**: 需要能够访问外部网络
3. **数据缓存**: 对于重复查询，建议在本地缓存结果
4. **引用来源**: 使用数据时请引用相应的数据库
5. **API Key 安全**: 不要将 API Key 提交到版本控制系统

## 参考链接

### 结构数据库
- [RCSB PDB API 文档](https://data.rcsb.org/)
- [UniProt REST API 文档](https://www.uniprot.org/help/api_queries)
- [InterPro API 文档](https://github.com/ProteinsWebTeam/interpro7-api)

### 文献检索
- [NCBI E-utilities 官方文档](https://www.ncbi.nlm.nih.gov/books/NBK25500/)
- [Semantic Scholar API 文档](https://api.semanticscholar.org/)
- [bioRxiv API 文档](https://api.biorxiv.org/)
- [Europe PMC API 文档](https://europepmc.org/RestfulWebService)
- [CrossRef REST API](https://api.crossref.org/)
- [OpenAlex API 文档](https://docs.openalex.org/)
- [CORE API 文档](https://core.ac.uk/documentation/api)
