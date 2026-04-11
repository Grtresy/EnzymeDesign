# CrossRef API 文档

CrossRef 是 DOI（数字对象标识符）注册机构，提供权威的学术元数据服务。通过 CrossRef API 可以获取 DOI 对应的文献元数据、引用信息和出版商数据。

## 概述

### 功能定位

- **DOI 元数据权威**: 获取 DOI 对应的标准元数据
- **引用信息**: 获取文献的参考文献列表
- **出版商数据**: 查询期刊和出版商信息
- **批量遍历**: 支持 cursor 深分页获取大量记录

### 适用场景

- 根据 DOI 获取标准引用格式
- 批量获取文献元数据
- 查询期刊影响因子和出版信息
- 构建引用网络

## 认证方式

**无需认证**: CrossRef API 是完全开放的，不需要 API Key。

**推荐做法**: 在请求头中添加邮箱地址，有助于问题排查和获得更好的服务。

```python
headers = {
    "User-Agent": f"MyApp/1.0 (mailto:{email})"
}
```

## 速率限制

**适度使用**: 无明确限制，但建议：
- 请求间隔 ≥ 0.05 秒（~50ms）
- 批量操作使用合理延迟
- 遵守 "礼貌池"（Polite Pool）规范

**礼貌池**: 添加 `mailto` 参数可进入礼貌池，获得更稳定的响应。

## 核心端点

### 基础 URL

```
https://api.crossref.org/
```

### Works - 文献查询

| 属性 | 值 |
|------|-----|
| URL | `/works` |
| 方法 | GET |
| 认证 | 无需 |

**核心参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `query` | string | ❌ | 搜索关键词 |
| `filter` | string | ❌ | 过滤条件（多个用逗号分隔） |
| `rows` | int | ❌ | 返回结果数（默认 20，最大 1000） |
| `offset` | int | ❌ | 分页偏移量 |
| `sort` | string | ❌ | 排序字段 |
| `order` | string | ❌ | 排序方向：`asc`, `desc` |
| `select` | string | ❌ | 返回字段 |

**常用过滤器**:

| 过滤器 | 说明 | 示例 |
|--------|------|------|
| `from-pub-date` | 起始年份 | `from-pub-date:2020` |
| `until-pub-date` | 结束年份 | `until-pub-date:2024` |
| `type` | 文献类型 | `type:journal-article` |
| `has-references` | 有参考文献 | `has-references:true` |
| `is-open-access` | 开放获取 | `is-open-access:true` |
| `publisher-name` | 出版商 | `publisher-name:Elsevier` |

**示例请求**:
```
GET /works?query=enzyme+engineering&rows=10&sort=is-referenced-by-count&order=desc
```

**响应格式**:
```json
{
  "status": "ok",
  "message-type": "work-list",
  "message": {
    "total-results": 5234,
    "items": [
      {
        "DOI": "10.1016/j.jbiotec.2024.01.001",
        "type": "journal-article",
        "title": ["Engineering of thermostable enzymes..."],
        "author": [
          {"given": "John", "family": "Smith"},
          {"given": "Li", "family": "Zhang"}
        ],
        "container-title": ["Journal of Biotechnology"],
        "published": {"date-parts": [[2024, 1, 15]]},
        "is-referenced-by-count": 45,
        "references-count": 62
      }
    ]
  }
}
```

### Work by DOI - 按 DOI 获取

| 属性 | 值 |
|------|-----|
| URL | `/works/{doi}` |
| 方法 | GET |
| 认证 | 无需 |

**示例请求**:
```
GET /works/10.1016/j.jbiotec.2024.01.001
```

### Cursor Deep Paging - 深分页

Crossref 的常见批量拉取方式是对 `GET /works` 使用 cursor，而不是 `POST /works` 批量提交 DOI。

**示例请求**:
```
GET /works?filter=from-pub-date:2024-01-01&rows=1000&cursor=*
```

首次请求使用 `cursor=*`，后续使用响应中的 `next-cursor`。

### Members - 出版商查询

| 属性 | 值 |
|------|-----|
| URL | `/members` |
| 方法 | GET |
| 认证 | 无需 |

**核心参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `query` | string | ❌ | 搜索出版商名称 |
| `rows` | int | ❌ | 返回结果数 |

### Journals - 期刊查询

| 属性 | 值 |
|------|-----|
| URL | `/journals` |
| 方法 | GET |
| 认证 | 无需 |

**核心参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `query` | string | ❌ | 搜索期刊名称 |
| `issn` | string | ❌ | 按 ISSN 过滤 |

**示例请求**:
```
GET /journals?query=Nature&rows=10
```

### Journal Works - 某期刊下的文献

| 属性 | 值 |
|------|-----|
| URL | `/journals/{issn}/works` |
| 方法 | GET |
| 认证 | 无需 |

**示例请求**:
```
GET /journals/1476-4687/works?filter=from-pub-date:2024-01-01&rows=20
```

### Types - 文献类型

| 属性 | 值 |
|------|-----|
| URL | `/types` |
| 方法 | GET |
| 认证 | 无需 |

**常用类型**:
- `journal-article`
- `book-chapter`
- `proceedings-article`
- `dissertation`
- `preprint`

## 返回字段

### 完整字段列表

| 字段 | 说明 |
|------|------|
| `DOI` | DOI 标识符 |
| `title` | 标题 |
| `author` | 作者列表 |
| `container-title` | 期刊/书籍名称 |
| `published` | 发表日期 |
| `type` | 文献类型 |
| `abstract` | 摘要（部分有） |
| `URL` | DOI 解析 URL |
| `is-referenced-by-count` | 被引次数 |
| `references-count` | 参考文献数 |
| `publisher` | 出版商 |
| `ISSN` | 期刊 ISSN |
| `subject` | 主题分类 |
| `license` | 许可证信息 |
| `link` | 全文链接 |

## 酶设计场景示例

### 根据 DOI 获取引用格式

```python
doi = "10.1016/j.jbiotec.2024.01.001"
work = get_work_by_doi(doi)

# 生成 APA 格式引用
authors = ", ".join([f"{a['family']}, {a['given'][0]}." for a in work["author"]])
year = work["published"]["date-parts"][0][0]
title = work["title"][0]
journal = work["container-title"][0]

citation = f"{authors} ({year}). {title}. {journal}."
```

### 按条件批量拉取 DOI 元数据

```python
GET /works?filter=from-pub-date:2024-01-01,until-pub-date:2024-12-31,type:journal-article&rows=1000&cursor=*
```

### 查询高被引论文

```python
results = search_works("enzyme engineering", rows=20)

for work in results["message"]["items"]:
    print(f"{work.get('is-referenced-by-count', 0)} citations: {work['title'][0]}")
```

## 使用说明

### 运行示例代码

```bash
# 直接运行（无需 API Key）
cd docs/API/crossref
python examples.py

# 运行 mock 测试
pytest examples.py -v
```

### 依赖要求

```bash
pip install httpx pytest responses
```

## 参考链接

- [CrossRef REST API 文档](https://api.crossref.org/)
- [CrossRef API 指南](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [过滤条件参考](https://api.crossref.org/rest-api-docs/rest-api.html#filter-names)
- [礼貌池说明](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/)
