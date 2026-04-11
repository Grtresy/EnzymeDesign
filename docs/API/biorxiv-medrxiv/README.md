# bioRxiv/medRxiv API 文档

bioRxiv 和 medRxiv 是两个主要的预印本服务器，分别覆盖生物学和健康科学领域。预印本是未经同行评审的研究手稿，能够比传统期刊提前数月发布最新研究成果。

## 概述

### 功能定位

- **预印本首发**: 最新研究成果，领先正式发表数月
- **快速获取**: 无需等待同行评审即可获取研究内容
- **版本追踪**: 追踪论文从预印本到正式发表的完整历程
- **开放获取**: 所有预印本均可免费获取

### 适用场景

- 追踪酶设计方法学的最新进展
- 获取尚未正式发表的研究成果
- 了解特定领域的最新研究方向
- 发现新兴技术和方法

### bioRxiv vs medRxiv

| 平台 | 领域 | 说明 |
|------|------|------|
| bioRxiv | 生物学 | 分子生物学、生物化学、生物信息学等 |
| medRxiv | 健康科学 | 临床研究、流行病学、医学等 |

## 认证方式

**无需认证**: bioRxiv/medRxiv API 是完全开放的，不需要 API Key。

## 速率限制

**无硬性限制**: 但建议遵守以下最佳实践：
- 请求间隔 ≥ 0.5 秒
- 批量操作使用合理延迟
- 缓存结果避免重复请求

## 核心端点

### 基础 URL

```
# bioRxiv
https://api.biorxiv.org/

# medRxiv
https://api.medrxiv.org/
```

### 详情端点 - 获取论文详情或区间元数据

| 属性 | 值 |
|------|-----|
| URL | `/details/{server}/{doi}/na/json` 或 `/details/{server}/{interval}/{cursor}/json` |
| 方法 | GET |
| 认证 | 无需 |

**参数说明**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `server` | string | ✅ | 服务器名：`biorxiv` 或 `medrxiv` |
| `doi` | string | ✅ | DOI（通常写为 bioRxiv/medRxiv 的内部 DOI 片段） |
| `interval` | string | ✅ | 单日或日期范围，如 `2024-01-01/2024-01-31` |
| `cursor` | string | ❌ | 分页游标，首批通常用 `0` |

**示例请求**:
```
# 获取单篇论文详情
GET /details/biorxiv/2024.01.15.123456/na/json

# 获取日期范围内的元数据
GET /details/biorxiv/2024-01-01/2024-01-31/0/json
```

**响应格式**:
```json
{
  "status": "ok",
  "messages": [],
  "collection": [
    {
      "doi": "10.1101/2024.01.15.123456",
      "title": "Engineering of thermostable enzymes...",
      "authors": "Smith J; Zhang L; Wang M",
      "author_corresponding": "Smith J",
      "author_corresponding_institution": "MIT",
      "date": "2024-01-15",
      "version": "1",
      "type": "new_result",
      "license": "cc_by",
      "category": "Biochemistry",
      "jatsxml": "https://www.biorxiv.org/content/10.1101/2024.01.15.123456.source.xml",
      "abstract": "This study presents...",
      "published": "2024-03-15",
      "server": "biorxiv"
    }
  ]
}
```

### 其他常用批量端点

| 属性 | 值 |
|------|-----|
| URL | `/sum/{server}/{interval}` / `/usage/{server}/{interval}` / `/funder/{server}/{funder}/{interval}` |
| 方法 | GET |
| 认证 | 无需 |

**示例请求**:
```
# 获取区间摘要统计
GET /sum/biorxiv/2024-01-01/2024-01-31/json

# 获取区间 usage
GET /usage/biorxiv/2024-01-01/2024-01-31/json
```

**响应格式**:
```json
{
  "status": "ok",
  "messages": [],
  "collection": [
    {
      "doi": "10.1101/2024.01.15.123456",
      "title": "Engineering of thermostable enzymes...",
      "category": "Biochemistry",
      "authors": "Smith J; Zhang L",
      "date": "2024-01-15",
      "version": "1"
    }
  ]
}
```

### 发布信息端点

| 属性 | 值 |
|------|-----|
| URL | `/pub/{server}/{doi}/na/json` 或 `/pubs/{server}/{interval}/{cursor}/json` |
| 方法 | GET |
| 认证 | 无需 |

**功能**: 获取预印本与正式发表论文的映射；单 DOI 用 `pub`，区间列表用 `pubs`。

**响应格式**:
```json
{
  "status": "ok",
  "collection": [
    {
      "preprint_doi": "10.1101/2024.01.15.123456",
      "published_doi": "10.1038/s41586-024-12345",
      "preprint_title": "Original preprint title",
      "published_title": "Final published title",
      "preprint_date": "2024-01-15",
      "published_date": "2024-03-15",
      "embargo_date": "2024-03-15"
    }
  ]
}
```

## 分类系统

### bioRxiv 分类

| 分类 | 说明 |
|------|------|
| Biochemistry | 生物化学 |
| Bioinformatics | 生物信息学 |
| Biophysics | 生物物理 |
| Cancer Biology | 癌症生物学 |
| Cell Biology | 细胞生物学 |
| Developmental Biology | 发育生物学 |
| Ecology | 生态学 |
| Evolutionary Biology | 进化生物学 |
| Genetics | 遗传学 |
| Genomics | 基因组学 |
| Immunology | 免疫学 |
| Microbiology | 微生物学 |
| Molecular Biology | 分子生物学 |
| Neuroscience | 神经科学 |
| Plant Biology | 植物生物学 |
| Structural Biology | 结构生物学 |
| Systems Biology | 系统生物学 |

### 文章类型

| 类型 | 说明 |
|------|------|
| `new_result` | 新研究结果 |
| `confirmatory_result` | 验证性结果 |
| `contradictory_result` | 矛盾结果 |
| `extension` | 研究扩展 |
| `reproduction` | 复现研究 |

## 酶设计场景示例

### 追踪酶工程方法学预印本

```python
# 获取最近 30 天的生物化学预印本
from datetime import datetime, timedelta

end_date = datetime.now()
start_date = end_date - timedelta(days=30)

url = f"https://api.biorxiv.org/details/biorxiv/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}/0/json"

# 然后过滤包含 "enzyme" 或 "protein engineering" 的论文
```

### 检查预印本是否已正式发表

```python
# 使用 pub 端点检查单篇预印本发表状态
preprint_doi = "2024.01.15.123456"
pub_info = requests.get(f"https://api.biorxiv.org/pub/biorxiv/{preprint_doi}/na/json")

if pub_info.json()["collection"]:
    print("预印本已正式发表！")
```

### 获取特定论文的所有版本

```python
# 拉取单篇条目，collection 中会带回不同版本
details = requests.get("https://api.biorxiv.org/details/biorxiv/2024.01.15.123456/na/json").json()

for version in details["collection"]:
    print(f"版本 {version['version']}: {version['date']}")
```

## 使用说明

### 运行示例代码

```bash
# 直接运行（无需 API Key）
cd docs/API/biorxiv-medrxiv
python examples.py

# 运行 mock 测试
pytest examples.py -v
```

### 依赖要求

```bash
pip install httpx pytest responses
```

## 注意事项

1. **预印本性质**: 预印本未经同行评审，使用时需谨慎评估
2. **版本追踪**: 同一论文可能有多个版本，注意使用最新版本
3. **引用规范**: 引用预印本时应明确标注版本和日期
4. **版权限制**: 部分预印本可能有版权限制，使用前检查 license 字段

## 参考链接

- [bioRxiv API 文档](https://api.biorxiv.org/)
- [medRxiv API 文档](https://api.medrxiv.org/)
- [bioRxiv 帮助中心](https://www.biorxiv.org/about/FAQ)
- [预印本引用指南](https://www.biorxiv.org/about/FAQ#citing)
