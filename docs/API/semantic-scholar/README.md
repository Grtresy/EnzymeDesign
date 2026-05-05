# Semantic Scholar API 文档

Semantic Scholar 是由 Allen Institute for AI 开发的学术搜索引擎，利用 AI 技术提供智能文献检索和分析功能。特别适合进行高影响力论文发现和引用网络分析。

## 概述

### 功能定位

- **AI 增强摘要**: 自动生成 TLDR（Too Long; Didn't Read）短摘要
- **引用分析**: 完整的引用网络和影响力指标
- **领域分类**: 论文自动归类到学术领域
- **批量操作**: 支持批量查询和获取

### 适用场景

- 发现高影响力的酶工程论文
- 分析特定研究方向的引用网络
- 获取论文的 AI 生成摘要
- 追踪作者的研究轨迹

## 认证方式

### API Key 配置

API Key 是可选的，但强烈推荐使用以获得更高的速率限制。

```bash
# 环境变量方式
export SEMANTIC_SCHOLAR_API_KEY="your-api-key-here"

# Python 代码中设置
import os
API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
```

### 获取 API Key

1. 访问 [Semantic Scholar API](https://www.semanticscholar.org/product/api)
2. 注册账号
3. 在 API Dashboard 创建 Key

## 速率限制

| 认证状态 | 限制 | 每 5 分钟请求数 |
|---------|------|---------------|
| 无 API Key | 100/5分钟 | ~0.33 次/秒 |
| 有 API Key | 5000/5分钟 | ~16.7 次/秒 |
| 研究伙伴计划 | 更高 | 联系官方 |

**建议**: 即使有 API Key，也建议在连续请求间添加 0.1-0.2 秒延迟。

## 核心端点

### 基础 URL

```
https://api.semanticscholar.org/graph/v1/
```

### Paper Search - 论文搜索

| 属性 | 值 |
|------|-----|
| URL | `/paper/search` |
| 方法 | GET |
| 认证 | 可选 |

**核心参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `query` | string | ✅ | 搜索关键词 |
| `limit` | int | ❌ | 返回结果数量（默认 10，最大 100） |
| `offset` | int | ❌ | 分页偏移量 |
| `fields` | string | ❌ | 返回字段（逗号分隔） |
| `year` | string | ❌ | 发表年份范围（如 `2020-2024`） |
| `venue` | string | ❌ | 期刊/会议名称 |
| `openAccessPdf` | string | ❌ | 过滤开放获取 PDF：`any` |

**常用字段**:

| 字段 | 说明 |
|------|------|
| `paperId` | 论文唯一标识 |
| `title` | 标题 |
| `abstract` | 摘要 |
| `year` | 发表年份 |
| `authors` | 作者列表 |
| `citationCount` | 被引次数 |
| `referenceCount` | 参考文献数 |
| `tldr` | AI 生成短摘要 |
| `openAccessPdf` | 开放获取 PDF 链接 |
| `journal` | 期刊信息 |
| `fieldsOfStudy` | 研究领域 |

**示例请求**:
```
GET /paper/search?query=enzyme+engineering&limit=10&fields=title,year,citationCount,tldr
```

**响应格式**:
```json
{
  "total": 5234,
  "offset": 0,
  "data": [
    {
      "paperId": "abc123",
      "title": "Engineering of thermostable enzymes...",
      "year": 2024,
      "citationCount": 45,
      "tldr": {
        "model": "tldr@v2.0.0",
        "text": "This paper presents a novel approach..."
      }
    }
  ]
}
```

### Paper by ID - 获取单篇论文

| 属性 | 值 |
|------|-----|
| URL | `/paper/{paper_id}` |
| 方法 | GET |
| 认证 | 可选 |

**paper_id 格式**:
- S2 Paper ID: `abc123def456`
- DOI: `DOI:10.1234/example`
- ArXiv: `ARXIV:2101.12345`
- PMID: `PMID:38123456`

**示例请求**:
```
GET /paper/DOI:10.1016/j.jmb.2024.01.001?fields=title,abstract,citationCount,tldr
```

### Paper Batch - 批量获取

| 属性 | 值 |
|------|-----|
| URL | `/paper/batch` |
| 方法 | POST |
| 认证 | 可选 |

**请求体**:
```json
{
  "ids": ["abc123", "def456", "PMID:38123456"],
  "fields": "title,year,citationCount"
}
```

### Author Search - 作者搜索

| 属性 | 值 |
|------|-----|
| URL | `/author/search` |
| 方法 | GET |
| 认证 | 可选 |

**核心参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `query` | string | ✅ | 作者姓名 |
| `limit` | int | ❌ | 返回结果数量 |

### Author by ID - 作者详情

| 属性 | 值 |
|------|-----|
| URL | `/author/{author_id}` |
| 方法 | GET |
| 认证 | 可选 |

**核心参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `fields` | string | ❌ | 返回字段；如果需要作者论文，可请求 `papers.title,papers.year,papers.citationCount` 等嵌套字段 |

## 高级搜索功能

### 领域过滤

```python
# 先取回领域字段，再在客户端过滤
paper = get_paper("DOI:10.1038/s41586-024-12345", fields="title,fieldsOfStudy,s2FieldsOfStudy")
```

### 引用排序

```python
# 按引用数排序（需要在客户端处理）
results = search_papers("lipase engineering")
sorted_results = sorted(results["data"], key=lambda x: x["citationCount"], reverse=True)
```

### 开放获取过滤

```python
# 只返回有开放获取 PDF 的论文
params = {
    "query": "protein engineering",
    "openAccessPdf": "any",
    "fields": "title,openAccessPdf"
}
```

## 酶设计场景示例

### 查找高影响力酶工程论文

```python
# 搜索并按引用数排序
query = "enzyme engineering directed evolution"
fields = "title,year,citationCount,tldr,authors"
results = search_papers(query, limit=20, fields=fields)

# 过滤高引用论文
high_impact = [p for p in results["data"] if p["citationCount"] > 100]
```

### 获取论文 TLDR 摘要

```python
# 获取 AI 生成的短摘要
paper = get_paper("DOI:10.1038/s41586-024-12345", fields="title,tldr,abstract")

if paper.get("tldr"):
    print(f"TLDR: {paper['tldr']['text']}")
```

### 追踪作者研究

```python
# 查找作者
GET /author/search?query=Frances+Arnold&limit=5

# 获取作者详情，并把论文字段一并展开
GET /author/1741101?fields=name,homepage,paperCount,papers.title,papers.year,papers.citationCount
```

## 使用说明

### 运行示例代码

```bash
# 直接运行（无需 API Key）
cd docs/API/semantic-scholar
python examples.py

# 使用 API Key 运行（更高限制）
SEMANTIC_SCHOLAR_API_KEY=your-key python examples.py

# 运行 mock 测试
pytest examples.py -v
```

### 依赖要求

```bash
pip install httpx pytest responses
```

## 参考链接

- [Semantic Scholar API 文档](https://api.semanticscholar.org/)
- [API Dashboard](https://www.semanticscholar.org/product/api)
- [字段参考](https://api.semanticscholar.org/api-docs/graph#tag/Paper/operation/get_graph_paper_search)
- [研究伙伴计划](https://www.semanticscholar.org/research-program)
