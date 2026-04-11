# OpenAlex API 文档

OpenAlex 是一个完全开放的学术图谱数据库，由 OurResearch 开发维护。它提供了关于论文、作者、机构和研究概念的全面数据，是替代 Microsoft Academic Graph 的开放解决方案。

## 概述

### 功能定位

- **开放学术图谱**: 论文、作者、机构、概念的完整关联
- **概念标签**: 自动为论文分配研究概念/主题
- **开放获取**: 完全免费，无需 API Key
- **高级搜索**: 支持复杂的过滤和排序

### 适用场景

- 构建学术引用网络
- 发现研究概念和主题关联
- 分析作者和机构的研究方向
- 获取开放获取论文全文

## 认证方式

### 无需认证

OpenAlex API 是完全开放的，不需要 API Key。

### Polite Pool（礼貌池）

添加 `mailto` 参数可进入礼貌池，获得更高的速率限制和更快的响应。

```bash
# 基础 URL 添加 mailto
https://api.openalex.org/works?mailto=your-email@example.com
```

## 速率限制

| 模式 | 限制 | 说明 |
|------|------|------|
| 标准池 | 10 次/秒 | 无 mailto 参数 |
| 礼貌池 | 100 次/秒 | 添加 mailto 参数 |
| 大结果集 | 使用 cursor 分页 | 不依赖未文档化的 POST 批量端点 |

## 核心端点

### 基础 URL

```
https://api.openalex.org/
```

### Works - 论文查询

| 属性 | 值 |
|------|-----|
| URL | `/works` |
| 方法 | GET |
| 认证 | 无需 |

**核心参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `search` | string | ❌ | 全文搜索 |
| `filter` | string | ❌ | 过滤条件（多个用逗号分隔） |
| `sort` | string | ❌ | 排序字段 |
| `per_page` | int | ❌ | 每页结果数（默认 25，最大 200） |
| `page` | int | ❌ | 页码 |
| `cursor` | string | ❌ | 游标分页，批量遍历大结果集时优先使用 |
| `select` | string | ❌ | 返回字段 |
| `group_by` | string | ❌ | 聚合统计 |
| `mailto` | string | ❌ | 邮箱地址（礼貌池） |

**常用过滤器**:

| 过滤器 | 说明 | 示例 |
|--------|------|------|
| `title.search` | 标题搜索 | `title.search:enzyme` |
| `abstract.search` | 摘要搜索 | `abstract.search:engineering` |
| `default.search` | 默认搜索 | `default.search:lipase` |
| `authorships.author.id` | 作者 ID | `authorships.author.id:A123456` |
| `authorships.institution.id` | 机构 ID | `authorships.institution.id:I123456` |
| `concepts.id` | 概念 ID | `concepts.id:C123456` |
| `publication_year` | 发表年份 | `publication_year:2024` |
| `type` | 文献类型 | `type:article` |
| `is_oa` | 开放获取 | `is_oa:true` |
| `cited_by_count` | 被引次数 | `cited_by_count:>100` |

**示例请求**:
```
GET /works?search=enzyme+engineering&per_page=10&sort=cited_by_count:desc
```

**响应格式**:
```json
{
  "meta": {
    "count": 5234,
    "db_response_time_ms": 45,
    "page": 1,
    "per_page": 10
  },
  "results": [
    {
      "id": "https://openalex.org/W123456789",
      "doi": "https://doi.org/10.1016/j.jbiotec.2024.01.001",
      "title": "Engineering of thermostable enzymes...",
      "display_name": "Engineering of thermostable enzymes...",
      "publication_year": 2024,
      "cited_by_count": 45,
      "is_oa": true,
      "open_access": {
        "is_oa": true,
        "oa_status": "gold",
        "oa_url": "https://..."
      },
      "authorships": [
        {
          "author_position": "first",
          "author": {
            "id": "https://openalex.org/A123456",
            "display_name": "John Smith"
          }
        }
      ],
      "concepts": [
        {
          "id": "https://openalex.org/C123456",
          "display_name": "Enzyme engineering",
          "score": 0.85
        }
      ]
    }
  ]
}
```

### Work by ID - 获取单篇论文

| 属性 | 值 |
|------|-----|
| URL | `/works/{id}` |
| 方法 | GET |
| 认证 | 无需 |

**ID 格式**:
- OpenAlex ID: `W123456789`
- DOI: `doi:10.1016/j.jbiotec.2024.01.001`
- PMID: `pmid:38123456`

**示例请求**:
```
GET /works/doi:10.1016/j.jbiotec.2024.01.001
```

### Authors - 作者查询

| 属性 | 值 |
|------|-----|
| URL | `/authors` |
| 方法 | GET |
| 认证 | 无需 |

**核心参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `search` | string | ❌ | 搜索作者姓名 |
| `filter` | string | ❌ | 过滤条件 |
| `per_page` | int | ❌ | 每页结果数 |

**常用过滤器**:

| 过滤器 | 说明 | 示例 |
|--------|------|------|
| `display_name.search` | 姓名搜索 | `display_name.search:Smith` |
| `works_count` | 论文数量 | `works_count:>100` |
| `cited_by_count` | 被引总数 | `cited_by_count:>1000` |
| `last_known_institution.id` | 所属机构 | `last_known_institution.id:I123456` |

### Institutions - 机构查询

| 属性 | 值 |
|------|-----|
| URL | `/institutions` |
| 方法 | GET |
| 认证 | 无需 |

**常用过滤器**:

| 过滤器 | 说明 |
|--------|------|
| `display_name.search` | 机构名称搜索 |
| `country_code` | 国家代码（如 `US`, `CN`） |
| `type` | 机构类型 |
| `works_count` | 论文数量 |

### Topics / Keywords - 主题查询

| 属性 | 值 |
|------|-----|
| URL | `/topics` / `/keywords` |
| 方法 | GET |
| 认证 | 无需 |

**功能**: 查询当前推荐使用的主题与关键词分类。

**示例请求**:
```
GET /topics?search=enzyme&per_page=10
```

> `Concepts` 资源仍可见，但官方已标为 deprecated；新接入优先使用 `Topics` 和 `Keywords`。

## 主题与聚合

### 常用主题示例

| 主题 | ID | 说明 |
|------|-----|------|
| Biochemistry | `Txxxxxxx` | 生物化学主题 |
| Molecular biology | `Txxxxxxx` | 分子生物学主题 |
| Enzyme engineering | `Txxxxxxx` | 酶工程相关主题 |

### 常用调用方式

```python
# 搜索与特定主题相关的论文
params = {
    "filter": "primary_topic.id:Txxxxxxx",
    "sort": "cited_by_count:desc"
}
```

```python
# 用 cursor 拉取大结果集
params = {
    "filter": "publication_year:2024",
    "per_page": 200,
    "cursor": "*"
}
```

```python
# 用 group_by 做聚合
params = {
    "search": "enzyme engineering",
    "group_by": "publication_year"
}
```

## 酶设计场景示例

### 搜索酶工程高被引论文

```python
params = {
    "search": "enzyme engineering",
    "filter": "from_publication_date:2020-01-01,is_oa:true",
    "sort": "cited_by_count:desc",
    "per_page": 20,
}
```

### 获取作者的研究方向

```python
# 搜索作者
GET /authors?search=Frances+Arnold&per_page=5

# 再按作者 ID 反查论文
GET /works?filter=authorships.author.id:A1969205032&sort=publication_year:desc&per_page=50
```

### 构建概念网络

```python
# 获取论文的主题/关键词
work = get_work("W123456789")

for topic in work.get("topics", []):
    print(topic["display_name"])
```

### 查找开放获取全文

```python
params = {
    "search": "protein engineering",
    "filter": "is_oa:true",
    "per_page": 20
}
GET /works?search=protein+engineering&filter=is_oa:true&per_page=20
```

## 使用说明

### 运行示例代码

```bash
# 直接运行（无需 API Key）
cd docs/API/openalex
python examples.py

# 使用礼貌池（更高限制）
OPENALEX_EMAIL=your@email.com python examples.py

# 运行 mock 测试
pytest examples.py -v
```

### 依赖要求

```bash
pip install httpx pytest responses
```

## 参考链接

- [OpenAlex API 文档](https://docs.openalex.org/)
- [OpenAlex 网站](https://openalex.org/)
- [过滤条件参考](https://docs.openalex.org/api-entities/works/filter-works)
- [概念层级说明](https://docs.openalex.org/api-entities/concepts)
