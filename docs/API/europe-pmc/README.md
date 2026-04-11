# Europe PMC API 文档

Europe PMC 是欧洲生命科学文献数据库，提供对 PubMed、PubMed Central、BioRxiv 等多个来源的统一访问。特别适合获取开放获取全文和文献注释数据。

## 概述

### 功能定位

- **多源聚合**: 整合 PubMed、PMC、bioRxiv、CrossRef 等多个来源
- **全文获取**: 提供开放获取全文 XML，以及文章级链接和数据库交叉引用
- **注释 API**: 获取文献中的基因、蛋白质、化学物质等注释
- **数据链接**: 文献与数据库记录（如 UniProt、PDB）的关联

### 适用场景

- 获取开放获取全文内容
- 提取文献中的生物学实体注释
- 查询文献与数据库的关联
- 获取结构化的文献元数据

## 认证方式

**无需认证**: Europe PMC API 是完全开放的，不需要 API Key。

## 速率限制

**适度使用**: 无明确限制，但建议：
- 请求间隔 ≥ 0.2 秒
- 避免并发大量请求
- 缓存结果避免重复请求

## 核心端点

### 基础 URL

```
https://www.ebi.ac.uk/europepmc/webservices/rest/
```

### Search - 文献搜索

| 属性 | 值 |
|------|-----|
| URL | `/search` |
| 方法 | GET |
| 认证 | 无需 |

**核心参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `query` | string | ✅ | 搜索关键词 |
| `resultType` | string | ❌ | 结果类型：`lite`, `core`, `idlist` |
| `cursorMark` | string | ❌ | 分页游标（首次用 `*`） |
| `pageSize` | int | ❌ | 每页结果数（默认 25，最大 1000） |
| `format` | string | ❌ | 返回格式：`json`（推荐）, `xml`, `atom` |
| `sort` | string | ❌ | 排序字段 |

**常用搜索字段**:

| 字段 | 说明 | 示例 |
|------|------|------|
| `TITLE` | 标题 | `TITLE:lipase` |
| `ABSTRACT` | 摘要 | `ABSTRACT:engineering` |
| `AUTH` | 作者 | `AUTH:Smith` |
| `JOURNAL` | 期刊 | `JOURNAL:Nature` |
| `YEAR` | 发表年份 | `YEAR:2024` |
| `DOI` | DOI | `DOI:10.1234/example` |
| `PMID` | PMID | `PMID:38123456` |
| `PMCID` | PMCID | `PMCID:PMC1234567` |
| `HAS_PB` | 有 PDB 链接 | `HAS_PB:Y` |
| `HAS_UNIPROT` | 有 UniProt 链接 | `HAS_UNIPROT:Y` |
| `OPEN_ACCESS` | 开放获取 | `OPEN_ACCESS:Y` |

**示例请求**:
```
GET /search?query=TITLE:enzyme+AND+ABSTRACT:engineering&resultType=core&pageSize=10&format=json
```

**响应格式**:
```json
{
  "version": "4.0",
  "hitCount": 5234,
  "request": {
    "query": "TITLE:enzyme AND ABSTRACT:engineering",
    "resultType": "core"
  },
  "resultList": {
    "result": [
      {
        "id": "38123456",
        "source": "MED",
        "pmid": "38123456",
        "doi": "10.1016/j.jbiotec.2024.01.001",
        "title": "Engineering of thermostable enzymes...",
        "authorString": "Smith J, Zhang L, Wang M.",
        "journalTitle": "Journal of Biotechnology",
        "pubYear": "2024",
        "isOpenAccess": "Y",
        "pmcid": "PMC1234567",
        "abstractText": "This study presents..."
      }
    ]
  }
}
```

### Article - 获取文章详情

| 属性 | 值 |
|------|-----|
| URL | `/article/{source}/{id}` |
| 方法 | GET |
| 认证 | 无需 |

**参数说明**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `source` | string | ✅ | 来源：`MED`, `PMC`, `PAT`, `ETH`, `HIR`, `CTX`, `CBA`, `AGR` |
| `id` | string | ✅ | 文献 ID（PMID 或 PMCID） |
| `format` | string | ❌ | 常用为 `json` 或 `xml` |

**示例请求**:
```
# 获取 JSON 元数据
GET /article/MED/38123456?format=json

# 获取 XML 元数据
GET /article/PMC/PMC1234567?format=xml

# 获取开放获取全文 XML
GET /PMC1234567/fullTextXML
```

### Annotations - 文献注释

| 属性 | 值 |
|------|-----|
| URL | `/annotations_api/annotationsByArticleIds` |
| 方法 | GET |
| 认证 | 无需 |

**功能**: 获取文献中自动提取的生物学实体注释（基因、蛋白质、化学物质、疾病等）。

**示例请求**:
```
GET /annotations_api/annotationsByArticleIds?articleIds=PMC:PMC1234567&format=json
```

**响应格式**:
```json
{
  "version": "1.0",
  "pmcid": "PMC1234567",
  "annotations": [
    {
      "exact": "lipase",
      "prefix": "expression of",
      "suffix": "enzyme",
      "id": "http://purl.obolibrary.org/obo/CHEBI_28593",
      "type": "Chemical",
      "section": "abstract",
      "provider": "Chemical Entities of Biological Interest"
    }
  ]
}
```

### Database Links - 数据库链接

| 属性 | 值 |
|------|-----|
| URL | `/{source}/{id}/databaseLinks` |
| 方法 | GET |
| 认证 | 无需 |

**支持的数据库名称**:
- `UNIPROT` - UniProt 蛋白质
- `PDB` - Protein Data Bank
- `EMBL` - EMBL 核酸序列
- `CHEBI` - ChEBI 化学物质
- `INTACT` - IntAct 相互作用
- `INTACT_COMPLEX` - IntAct 复合物

**示例请求**:
```
GET /PMC/PMC1234567/databaseLinks?format=json
```

**响应格式**:
```json
{
  "version": "1.0",
  "pmcid": "PMC1234567",
  "hasDbLinks": "Y",
  "dbCrossReferenceList": {
    "dbCrossReference": [
      {
        "dbName": "UNIPROT",
        "accession": "P00533",
        "info": "Epidermal growth factor receptor"
      }
    ]
  }
}
```

## 搜索语法

### 布尔运算

```bash
# AND（默认）
enzyme engineering  # 等同于 enzyme AND engineering

# OR
(TITLE:lipase OR TITLE:esterase)

# NOT
enzyme NOT inhibitor

# 短语匹配
TITLE:"directed evolution"
```

### 字段组合

```bash
# 多字段组合
TITLE:enzyme AND ABSTRACT:engineering AND YEAR:2024

# 开放获取过滤
enzyme engineering AND OPEN_ACCESS:Y

# 有数据库链接
enzyme AND HAS_UNIPROT:Y AND HAS_PB:Y
```

## 酶设计场景示例

### 搜索开放获取的酶工程文献

```python
query = "TITLE:enzyme AND ABSTRACT:engineering AND OPEN_ACCESS:Y"
GET /search?query=TITLE:enzyme+AND+ABSTRACT:engineering+AND+OPEN_ACCESS:Y&resultType=core&pageSize=20&format=json
```

### 获取文献全文 XML

```python
GET /search?query=lipase+engineering+AND+OPEN_ACCESS:Y&resultType=core&pageSize=1&format=json
GET /PMC1234567/fullTextXML
```

### 获取文献中的蛋白质注释

```python
GET /PMC/PMC1234567/databaseLinks?format=json
```

### 查找与 PDB 关联的文献

```python
GET /search?query=enzyme+structure+AND+HAS_PB:Y&resultType=core&format=json
```

## 使用说明

### 运行示例代码

```bash
# 直接运行（无需 API Key）
cd docs/API/europe-pmc
python examples.py

# 运行 mock 测试
pytest examples.py -v
```

### 依赖要求

```bash
pip install httpx pytest responses
```

## 参考链接

- [Europe PMC REST API 文档](https://europepmc.org/RestfulWebService)
- [搜索语法指南](https://europepmc.org/help#search)
- [Annotations API](https://europepmc.org/AnnotationsApi)
- [Database Links API](https://europepmc.org/DatabaseLinksWebservice)
