# CORE API 文档

CORE 是全球最大的开放获取论文聚合平台，汇集了来自全球数千个数据源的数百万篇开放获取研究论文。CORE API 提供对这些论文的搜索、元数据获取和全文下载功能。

## 概述

### 功能定位

- **开放获取聚合**: 整合全球开放获取资源
- **全文下载**: 提供论文全文 PDF 下载
- **批量操作**: 支持批量搜索和获取
- **丰富元数据**: 提供完整的论文元数据

### 适用场景

- 批量下载开放获取论文全文
- 搜索特定领域的开放获取资源
- 获取论文的完整元数据
- 构建开放获取论文数据集

## 认证方式

### 可匿名访问，注册后更高额度

CORE 当前官方文档页将 API 说明指向 **API v2 Swagger**。公开说明里包含匿名可用额度；如果你有注册凭证或 API Key，通常会拿到更高额度和更稳定的服务。

```bash
# 可选：如果你有 CORE_API_KEY，可放到环境变量里
export CORE_API_KEY="your-api-key-here"
```

## 速率限制

| 类型 | 限制 | 说明 |
|------|------|------|
| 单请求 | 5 次 / 10 秒 | 如单次搜索、单篇获取 |
| 批量请求 | 1 次 / 10 秒 | 如批量搜索 / 批量获取 |

**建议**: 以当前 Swagger 和响应头为准，不要把旧版日配额表当成稳定契约。

## 核心端点

### 基础 URL

官方当前文档页展示的是 **API v2 Swagger**，请优先以 Swagger 中列出的路径、请求体和鉴权说明为准。

### Single Search - 单条搜索

| 属性 | 值 |
|------|-----|
| URL | `/search/{query}` |
| 方法 | GET |
| 认证 | 可匿名 |

**核心参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `query` | string | ✅ | 搜索关键词 |

**搜索语法**:

| 语法 | 说明 | 示例 |
|------|------|------|
| `title:` | 标题搜索 | `title:enzyme` |
| `description:` | 摘要搜索 | `description:engineering` |
| `authors:` | 作者搜索 | `authors:Smith` |
| `year:` | 年份过滤 | `year:2024` |
| `doi:` | DOI 搜索 | `doi:10.1234/example` |
| `AND` | 与运算 | `enzyme AND engineering` |
| `OR` | 或运算 | `lipase OR esterase` |
| `NOT` | 非运算 | `enzyme NOT inhibitor` |

**示例请求**:
```
GET /search/enzyme%20engineering
```

### Batch Search - 批量搜索

| 属性 | 值 |
|------|-----|
| URL | `/search` |
| 方法 | POST |
| 认证 | 可匿名 |

批量搜索适合一次提交多条查询，但速率限制比单请求更严格。

### Article by CORE ID - 获取单篇论文

| 属性 | 值 |
|------|-----|
| URL | `/articles/get/{coreId}` |
| 方法 | GET |
| 认证 | 可匿名 |

**示例请求**:
```
GET /articles/get/12345678
```

### Download PDF - 下载全文

| 属性 | 值 |
|------|-----|
| URL | `/articles/get/{coreId}/download/pdf` |
| 方法 | GET |
| 认证 | 可匿名 |

**功能**: 直接下载论文 PDF 文件。

**示例请求**:
```
GET /articles/get/12345678/download/pdf

# 响应: PDF 二进制内容
```

### Similar Works - 相似论文

| 属性 | 值 |
|------|-----|
| URL | `/articles/similar` |
| 方法 | POST |
| 认证 | 可匿名 |

**功能**: 获取与指定论文相似的其他论文。

## 返回字段

字段集合会随 Swagger 演进。常见字段仍包括标题、作者、年份、DOI、摘要、下载地址和数据源。

## 酶设计场景示例

### 搜索酶工程开放获取论文

```python
query = "enzyme engineering"
results = search_works(query)

for work in results["results"]:
    print(f"{work['title']}: {work.get('downloadUrl', 'No PDF')}")
```

### 批量下载论文全文

```python
# 搜索并下载
query = "protein engineering directed evolution"
results = search_works(query)

for work in results.get("results", []):
    if work.get("downloadUrl"):
        pdf_content = download_work(work["id"])
        with open(f"{work['id']}.pdf", "wb") as f:
            f.write(pdf_content)
```

### 获取论文全文内容

```python
work = get_work("12345678")

if work.get("fullText"):
    full_text = work["fullText"]
    print(f"全文长度: {len(full_text)} 字符")
```

## 使用说明

### 运行示例代码

```bash
# 运行示例
cd docs/API/core
python examples.py

# 如有 API Key，可额外注入
CORE_API_KEY=your-key python examples.py

# 运行 mock 测试
pytest examples.py -v
```

### 依赖要求

```bash
pip install httpx pytest responses
```

## 注意事项

1. **先看 Swagger**: CORE 文档近期有版本迁移，落地前以 Swagger 中的路径和 schema 为准
2. **注意速率限制**: 单请求和批量请求限速不同
3. **全文可用性**: 并非所有论文都有全文或 PDF
4. **版权限制**: 下载的论文请遵守版权规定

## 参考链接

- [CORE API 文档](https://core.ac.uk/documentation/api)
- [CORE 服务页](https://core.ac.uk/services/api/)
- [CORE 搜索语法](https://core.ac.uk/documentation/search/)
- [使用条款](https://core.ac.uk/terms/)
