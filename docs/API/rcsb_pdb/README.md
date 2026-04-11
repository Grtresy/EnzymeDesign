# RCSB PDB API 文档

RCSB PDB（Protein Data Bank）是全球主要的蛋白质三维结构数据库，由 Rutgers 大学和 UCSD 共同管理。通过 RCSB PDB API 可以程序化地访问蛋白质结构数据和元数据。

## API 概述

RCSB PDB 提供多种 API 接口：

| API | 基础 URL | 功能 |
|-----|---------|------|
| Data API | `https://data.rcsb.org/rest/v1/` | 获取结构元数据 |
| Search API | `https://search.rcsb.org/rcsbsearch/v2/` | 搜索结构 |
| File Download | `https://files.rcsb.org/` | 下载 PDB 文件 |

## 基础信息

- **认证**: 无需认证
- **速率限制**: 适度使用，建议添加延时
- **返回格式**: JSON（Data API 和 Search API）

## 请求格式

### 获取结构入口信息

```
GET https://data.rcsb.org/rest/v1/core/entry/{pdb_id}
```

**示例请求**:
```
GET https://data.rcsb.org/rest/v1/core/entry/1IEP
```

**返回格式** (JSON):
```json
{
  "rcsb_entry_container_identifiers": {
    "entry_id": "1IEP"
  },
  "struct": {
    "title": "晶体结构...",
    "pdbx_descriptor": "蛋白名称"
  },
  "exptl": [
    {
      "method": "X-RAY DIFFRACTION",
      "resolution": [1.8]
    }
  ],
  "rcsb_accession_info": {
    "initial_release_date": "2002-01-23T00:00:00Z"
  }
}
```

### 获取关联文献信息

```
GET https://data.rcsb.org/rest/v1/core/pubmed/{pdb_id}
```

**返回格式** (JSON):
```json
{
  "rcsb_pubmed_container_identifiers": {
    "pdb_id": "1IEP"
  },
  "pubmed": {
    "rcsb_authors": ["作者1", "作者2"],
    "title": "论文标题",
    "journal_name": "期刊名",
    "year": 2002
  }
}
```

### 获取聚合物实体信息

```
GET https://data.rcsb.org/rest/v1/core/polymer_entity/{pdb_id}/{entity_id}
```

**返回格式** (JSON):
```json
{
  "rcsb_polymer_entity_container_identifiers": {
    "entry_id": "1IEP",
    "entity_id": "1"
  },
  "entity_poly": {
    "type": "polypeptide(L)",
    "pdbx_seq_one_letter_code_can": "MVLSE..."
  }
}
```

### 搜索结构（Search API JSON 查询）

```
POST https://search.rcsb.org/rcsbsearch/v2/query
```

**请求体**:
```json
{
  "query": {
    "type": "terminal",
    "service": "text",
    "parameters": {
      "value": "kinase"
    }
  },
  "return_type": "entry",
  "request_options": {
    "results_content_type": ["experimental"],
    "return_all_hits": true
  }
}
```

**返回格式** (JSON):
```json
{
  "result_set": [
    {"identifier": "1IEP"},
    {"identifier": "2ABC"}
  ],
  "total_count": 5000
}
```

### 下载 PDB 文件

```
GET https://files.rcsb.org/download/{pdb_id}.pdb
GET https://files.rcsb.org/download/{pdb_id}.cif
```

**返回**: PDB 或 mmCIF 格式文件内容

### 获取化学组分信息

```
GET https://data.rcsb.org/rest/v1/core/chemcomp/{chem_comp_id}
```

**示例**:
```
GET https://data.rcsb.org/rest/v1/core/chemcomp/ATP
```

**返回格式** (JSON):
```json
{
  "chem_comp": {
    "id": "ATP",
    "name": "ADENOSINE-5'-TRIPHOSPHATE",
    "formula": "C10 H16 N5 O13 P3"
  }
}
```

## 常用查询示例

### 按分辨率搜索

```json
{
  "query": {
    "type": "terminal",
    "service": "text",
    "parameters": {
      "attribute": "rcsb_entry_info.resolution_combined",
      "operator": "less_or_equal",
      "value": 2.0
    }
  },
  "return_type": "entry"
}
```

### 按生物体搜索

```json
{
  "query": {
    "type": "terminal",
    "service": "text",
    "parameters": {
      "attribute": "rcsb_entity_source_organism.taxonomy_lineage.name",
      "operator": "exact_match",
      "value": "Homo sapiens"
    }
  },
  "return_type": "entry"
}
```

## 使用建议

1. **缓存结果**: PDB 数据更新不频繁，建议缓存
2. **批量处理**: 使用 Search API 批量获取结果
3. **选择格式**: mmCIF 格式包含更多信息，推荐用于新项目
4. **检查分辨率**: 对于 X-ray 结构，注意检查分辨率指标

## 示例代码

可运行的 Python 示例代码请参见 [examples.py](./examples.py)。

## 参考链接

- [RCSB PDB Data API 文档](https://data.rcsb.org/)
- [RCSB PDB Search API 文档](https://search.rcsb.org/)
- [PDB 文件格式说明](https://www.wwpdb.org/documentation/file-format)
