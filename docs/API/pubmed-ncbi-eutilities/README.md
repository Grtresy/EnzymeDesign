# PubMed E-utilities API 文档

PubMed 是由美国国家医学图书馆（NLM）维护的生物医学文献数据库，包含超过 3500 万篇文献引用。通过 NCBI E-utilities API 可以程序化地访问 PubMed 数据。

## 概述

### 功能定位

- **生物医学权威**: 最全面的生物医学和生命科学文献索引
- **MeSH 术语**: 支持医学主题词（Medical Subject Headings）精确检索
- **EC 号检索**: 可按酶分类号（EC Number）检索相关文献
- **批量操作**: 支持批量获取文献元数据和摘要

### 适用场景

- 搜索特定酶或蛋白质的相关文献
- 按疾病、药物或生物过程检索研究
- 追踪特定作者或机构的发表记录
- 获取文献引用和被引信息

## 认证方式

### API Key 配置

NCBI API Key 是可选的，但强烈推荐使用以提高速率限制。

```bash
# 环境变量方式
export NCBI_API_KEY="your-api-key-here"

# Python 代码中设置
import os
API_KEY = os.environ.get("NCBI_API_KEY")
```

### 获取 API Key

1. 访问 [NCBI 账号页面](https://www.ncbi.nlm.nih.gov/account/)
2. 登录或注册账号
3. 在 Settings → API Key Management 创建 Key

## 速率限制

| 认证状态 | 限制 | 建议 |
|---------|------|------|
| 无 API Key | 3 次/秒 | 请求间隔 ≥ 0.34 秒 |
| 有 API Key | 10 次/秒 | 请求间隔 ≥ 0.1 秒 |

**注意**: 超过限制会导致 HTTP 429 错误，建议在代码中添加重试逻辑。

## 核心端点

### 基础 URL

```
https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
```

### ESearch - 文献搜索

| 属性 | 值 |
|------|-----|
| URL | `/esearch.fcgi` |
| 方法 | GET |
| 认证 | 可选 |

**核心参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `db` | string | ✅ | 数据库名称，固定为 `pubmed` |
| `term` | string | ✅ | 搜索关键词 |
| `retmax` | int | ❌ | 返回结果数量（默认 20，最大 100000） |
| `retstart` | int | ❌ | 起始位置（用于分页） |
| `sort` | string | ❌ | 排序方式：`relevance`, `pub_date`, `FirstAuth` 等 |
| `retmode` | string | ❌ | 返回格式：`json` 或 `xml` |
| `datetype` | string | ❌ | 日期类型：`pdat`（发表日期）, `edat`（录入日期） |
| `mindate` | string | ❌ | 起始日期（YYYY/MM/DD） |
| `maxdate` | string | ❌ | 结束日期（YYYY/MM/DD） |

**示例请求**:
```
GET /esearch.fcgi?db=pubmed&term=lipase+enzyme+engineering&retmax=10&retmode=json
```

**响应格式**:
```json
{
  "header": {"type": "esearch", "version": "0.3"},
  "esearchresult": {
    "count": "5234",
    "retmax": "10",
    "retstart": "0",
    "idlist": ["38123456", "38123455", ...],
    "querytranslation": "lipase[All Fields] AND enzyme[All Fields]..."
  }
}
```

### EFetch - 获取文献详情

| 属性 | 值 |
|------|-----|
| URL | `/efetch.fcgi` |
| 方法 | GET/POST |
| 认证 | 可选 |

**核心参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `db` | string | ✅ | 数据库名称，固定为 `pubmed` |
| `id` | string | ✅ | PMID，多个用逗号分隔（最多 200 个） |
| `retmode` | string | ❌ | 返回格式：`xml`, `text` |
| `rettype` | string | ❌ | 返回类型：`abstract`, `medline`, `full` |

**示例请求**:
```
GET /efetch.fcgi?db=pubmed&id=38123456,38123455&retmode=xml
```

### ESummary - 获取简要信息

| 属性 | 值 |
|------|-----|
| URL | `/esummary.fcgi` |
| 方法 | GET |
| 认证 | 可选 |

**核心参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `db` | string | ✅ | 数据库名称，固定为 `pubmed` |
| `id` | string | ✅ | PMID，多个用逗号分隔 |
| `retmode` | string | ❌ | 返回格式：`json`（推荐） |

**响应格式**:
```json
{
  "result": {
    "uids": ["38123456"],
    "38123456": {
      "uid": "38123456",
      "title": "Engineering of thermostable lipase...",
      "authors": [{"name": "Smith J"}, {"name": "Zhang L"}],
      "fulljournalname": "Journal of Biotechnology",
      "pubdate": "2024 Jan 15",
      "doi": "10.1016/j.jbiotec.2024.01.001"
    }
  }
}
```

### ELink - 获取相关文献

| 属性 | 值 |
|------|-----|
| URL | `/elink.fcgi` |
| 方法 | GET |
| 认证 | 可选 |

**核心参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `db` | string | ✅ | 目标数据库 |
| `dbfrom` | string | ✅ | 源数据库 |
| `id` | string | ✅ | PMID |
| `cmd` | string | ❌ | 命令类型：`neighbor`（相关文献） |

### EPost / History Server - 大结果集工作流

当 PMID 很多、或你想把 `ESearch` 结果交给后续 `EFetch` / `ESummary` 分批消费时，优先使用 History Server。

**常见参数**:

| 参数 | 说明 |
|------|------|
| `usehistory=y` | 让 `ESearch` 把结果写入 History Server |
| `WebEnv` | History Server 会话标识 |
| `query_key` | 当前结果集标识 |

**示例请求**:
```bash
# 先把检索结果写入 History Server
GET /esearch.fcgi?db=pubmed&term=lipase+engineering&usehistory=y&retmax=0&retmode=json

# 再通过 WebEnv/query_key 分批拉取
GET /efetch.fcgi?db=pubmed&query_key=1&WebEnv=<webenv>&retstart=0&retmax=200&retmode=xml
```

如果已经有一批 PMID，也可以先用 `EPost` 提交，再交给 `EFetch` / `ESummary`。

## 高级搜索语法

### MeSH 术语

```bash
# 使用 MeSH 术语
"Enzymes/chemistry"[MeSH]

# 带 EC 号限制
"Lipase"[MeSH] AND "EC 3.1.1.3"[All Fields]
```

### 字段限定符

| 限定符 | 说明 | 示例 |
|--------|------|------|
| `[Title]` | 标题 | `lipase[Title]` |
| `[Title/Abstract]` | 标题或摘要 | `engineering[Title/Abstract]` |
| `[Author]` | 作者 | `Smith J[Author]` |
| `[Journal]` | 期刊 | `Nature[Journal]` |
| `[MeSH]` | MeSH 术语 | `Enzymes[MeSH]` |
| `[Year]` | 发表年份 | `2023:2024[Year]` |

### 组合查询

```bash
# AND, OR, NOT 组合
(lipase[Title] OR esterase[Title]) AND engineering[Title/Abstract]

# 日期范围
lipase[Title] AND 2020:2024[Year]

# 物种限制
"lipase"[MeSH] AND "humans"[MeSH]
```

## 酶设计场景示例

### 按 EC 号检索酶文献

```python
# 检索特定 EC 号的文献
ec_number = "3.1.1.3"  # Lipase
query = f'"EC {ec_number}"[All Fields] OR "lipase"[MeSH Terms]'

# 检索酶工程相关文献
query = '"enzyme engineering"[Title/Abstract] AND "directed evolution"[Title/Abstract]'
```

### 检索蛋白质工程方法

```python
# 定向进化
query = '("directed evolution"[MeSH] OR "protein engineering"[MeSH]) AND enzyme'

# 理性设计
query = '"rational design"[Title/Abstract] AND "site-directed mutagenesis"[Title/Abstract]'

# 计算设计
query = '"computational protein design"[Title/Abstract] AND ("Rosetta"[Title] OR "AlphaFold"[Title])'
```

## 使用说明

### 运行示例代码

```bash
# 直接运行（无需 API Key）
cd docs/API/pubmed-ncbi-eutilities
python examples.py

# 使用 API Key 运行
NCBI_API_KEY=your-key python examples.py

# 运行 mock 测试
pytest examples.py -v
```

### 依赖要求

```bash
pip install httpx pytest responses
```

## 参考链接

- [NCBI E-utilities 完整文档](https://www.ncbi.nlm.nih.gov/books/NBK25500/)
- [PubMed 帮助中心](https://pubmed.ncbi.nlm.nih.gov/help/)
- [MeSH 术语浏览器](https://meshb.nlm.nih.gov/)
- [E-utilities 速率限制说明](https://www.ncbi.nlm.nih.gov/books/NBK25497/#chapter2.Usage_Guidelines_and_Requiremen)
