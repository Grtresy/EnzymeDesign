# InterPro API 文档

InterPro 是由 EMBL-EBI 维护的蛋白质家族、结构域和功能位点综合数据库，整合了多个签名数据库（如 Pfam、SMART、PROSITE、CDD 等）的预测结果。通过 InterPro API 可以程序化地访问蛋白质家族注释、结构域信息等。

## API 概述

InterPro 提供统一的 REST API 接口。当前最常用的是 `entry` 资源，以及按 UniProt 蛋白质反查 InterPro 注释的组合路径。

| API | 基础 URL | 功能 |
|-----|---------|------|
| Entry API | `/entry/` | 查询 InterPro 条目和成员数据库条目 |
| Entry-by-Protein | `/entry/InterPro/protein/uniprot/{accession}` | 查询 UniProt 蛋白质的 InterPro 注释 |
| Taxonomy / Proteome / Structure | 见官方 API | 做分类、蛋白质组和结构关联查询 |

**基础 URL**: `https://www.ebi.ac.uk/interpro/api`

## 基础信息

- **认证**: 无需认证
- **速率限制**: 适度使用，建议添加延时
- **返回格式**: JSON（默认）
- **分页**: 使用 cursor-based 分页

## 请求格式

### 获取 InterPro 条目

```
GET https://www.ebi.ac.uk/interpro/api/entry/InterPro/{accession}
```

**参数**:
- `page_size`: 每页返回数量（默认 20，最大 200）
- `cursor`: 分页游标

**示例请求**:
```
GET https://www.ebi.ac.uk/interpro/api/entry/InterPro/IPR000001
```

**返回格式** (JSON):
```json
{
  "metadata": {
    "accession": "IPR000001",
    "name": "Kringle domain",
    "source_database": "interpro",
    "type": "domain",
    "go_terms": [
      {
        "identifier": "GO:0005509",
        "name": "calcium ion binding",
        "category": {
          "code": "M",
          "name": "molecular_function"
        }
      }
    ]
  }
}
```

### 获取蛋白质的 InterPro 注释

```
GET https://www.ebi.ac.uk/interpro/api/entry/InterPro/protein/uniprot/{accession}
```

**示例请求**:
```
GET https://www.ebi.ac.uk/interpro/api/entry/InterPro/protein/uniprot/P00533
```

**返回格式** (JSON):
```json
{
  "count": 15,
  "results": [
    {
      "metadata": {
        "accession": "IPR000719",
        "name": "Protein kinase domain",
        "type": "domain",
        "go_terms": [...]
      },
      "proteins": [
        {
          "accession": "P00533",
          "protein_length": 1210,
          "entry_protein_locations": [
            {
              "fragments": [{"start": 712, "end": 979}]
            }
          ]
        }
      ]
    }
  ]
}
```

### 分页列出 InterPro 条目

```
GET https://www.ebi.ac.uk/interpro/api/entry/InterPro?page_size=20
```

**参数**:
- `page_size`: 每页返回数量
- `cursor`: 分页游标（从响应的 `next` 字段获取）

### 按类型过滤条目

```
GET https://www.ebi.ac.uk/interpro/api/entry/InterPro?type=domain
```

**可用的类型过滤器**:
- `type=domain` - 结构域
- `type=family` - 蛋白质家族
- `type=repeat` - 重复序列
- `type=site` - 功能位点

## 常用查询语法

### 按成员数据库查询

```
GET /api/entry/pfam/PF00069      # Pfam 条目
GET /api/entry/smart/SM00220     # SMART 条目
GET /api/entry/prosite/PS50011   # PROSITE 条目
```

### 常见筛选

```
GET /api/entry/InterPro?type=domain&page_size=20
GET /api/entry/InterPro?search=kinase&page_size=20
```

### 组合查询

```
GET /api/entry/InterPro/protein/uniprot/P00533?extra_fields=short_name
```

## 常用字段

| 字段 | 描述 |
|------|------|
| `accession` | InterPro 登录号 (IPRxxxxxx) |
| `name` | 条目名称 |
| `type` | 类型 (domain, family, repeat, site) |
| `description` | 详细描述 |
| `go_terms` | 关联的 GO 术语 |
| `member_databases` | 成员数据库交叉引用 |
| `counters` | 统计信息（蛋白质数量等） |

## 使用建议

1. **使用分页**: InterPro 数据量大，建议使用 `page_size` 和 `cursor` 分页
2. **指定字段**: 使用 `extra_fields` 参数减少返回数据量
3. **缓存结果**: 条目信息相对稳定，建议本地缓存
4. **合理延时**: 批量查询时添加适当延时（建议 0.5-1 秒）

## InterPro 与成员数据库

InterPro 整合了以下签名数据库的预测结果：

| 数据库 | 类型 | 说明 |
|--------|------|------|
| Pfam | HMM | 蛋白质家族和结构域 |
| SMART | HMM | 信号蛋白结构域 |
| PROSITE | Pattern/Profile | 蛋白质位点模式 |
| CDD | HMM | NCBI 保守结构域 |
| PANTHER | HMM | 蛋白质家族和亚家族 |
| TIGRFAMs | HMM | 蛋白质家族 |
| SUPERFAMILY | HMM | SCOP 超家族 |
| Gene3D | HMM | CATH 结构域 |

## 与其他 API 的关联

- **UniProt**: 通过 `/api/entry/InterPro/protein/uniprot/{accession}` 获取 UniProt 蛋白质的 InterPro 注释
- **PDBe**: 通过 `entries` 字段中的 `pdbe_domain` 获取结构信息
- **GO**: 通过 `go_terms` 字段获取功能注释

## 示例代码

可运行的 Python 示例代码请参见 [examples.py](./examples.py)。

## 参考链接

- [InterPro 官网](https://www.ebi.ac.uk/interpro/)
- [InterPro API 文档](https://github.com/ProteinsWebTeam/interpro7-api)
- [InterProScan](https://github.com/ebi-pf-team/interproscan) - 本地序列注释工具
- [InterPro 帮助文档](https://www.ebi.ac.uk/interpro/help/)
