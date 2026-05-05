# UniProt API 文档

UniProt（Universal Protein Resource）是全球最全面的蛋白质序列和功能注释数据库，由 EMBL-EBI、SIB 和 PIR 共同维护。通过 UniProt API 可以程序化地访问蛋白质序列、功能注释、亚细胞定位等信息。

## API 概述

UniProt 提供多种 API 接口：

| API | 基础 URL | 功能 |
|-----|---------|------|
| REST API | `https://rest.uniprot.org/` | 获取蛋白质信息 |
| ID Mapping | `https://rest.uniprot.org/idmapping/` | ID 转换 |
| Proteomes | `https://rest.uniprot.org/proteomes/` | 蛋白质组数据 |

## 基础信息

- **认证**: 无需认证
- **速率限制**: 适度使用，建议添加延时
- **返回格式**: JSON（默认）、XML、TSV、FASTA、GFF

## 请求格式

### 获取蛋白质信息

```
GET https://rest.uniprot.org/uniprotkb/{uniprot_id}
```

**参数**:
- `format`: 返回格式（json, xml, tsv, fasta, gff）
- `fields`: 指定返回字段（TSV 格式时使用）

**示例请求**:
```
GET https://rest.uniprot.org/uniprotkb/P00533?format=json
```

**返回格式** (JSON):
```json
{
  "primaryAccession": "P00533",
  "secondaryAccessions": [],
  "organism": {
    "scientificName": "Homo sapiens",
    "taxonId": 9606
  },
  "proteinDescription": {
    "recommendedName": {
      "fullName": {
        "value": "Epidermal growth factor receptor"
      }
    }
  },
  "sequence": {
    "value": "MRPSGTAGA...",
    "length": 1210,
    "molWeight": 134277
  },
  "genes": [
    {
      "geneName": {
        "value": "EGFR"
      }
    }
  ]
}
```

### 搜索蛋白质

```
GET https://rest.uniprot.org/uniprotkb/search
```

**参数**:
- `query`: 搜索查询
- `format`: 返回格式
- `size`: 返回结果数量
- `fields`: 指定返回字段
- `cursor`: 分页游标

**示例请求**:
```
GET https://rest.uniprot.org/uniprotkb/search?query=gene:BRCA1&format=json&size=10
```

**返回格式** (JSON):
```json
{
  "results": [
    {
      "primaryAccession": "P38398",
      "genes": [{"geneName": {"value": "BRCA1"}}],
      "organism": {"scientificName": "Homo sapiens"}
    }
  ],
  "total": 1
}
```

### 获取蛋白质序列

```
GET https://rest.uniprot.org/uniprotkb/{uniprot_id}.fasta
```

**返回格式**:
```
>sp|P00533|EGFR_HUMAN Epidermal growth factor receptor OS=Homo sapiens OX=9606 GN=EGFR PE=1 SV=2
MRPSGTAGAALLALLAALCPASRALEEKKVCQGTSNKLTQLGTFEDHFLSLQRMFNNCEV
...
```

### ID 映射

```
POST https://rest.uniprot.org/idmapping/run
```

**请求体**:
```
from=UniProtKB_AC-ID&to=PDB&ids=P00533,P15056
```

**返回**:
```json
{
  "jobId": "1234567890"
}
```

检查结果:
```
GET https://rest.uniprot.org/idmapping/status/{jobId}
GET https://rest.uniprot.org/idmapping/results/{jobId}
GET https://rest.uniprot.org/idmapping/results/stream/{jobId}
```

推荐流程是先轮询 `status`，完成后再取 `results`；需要大结果流式下载时使用 `results/stream/{jobId}`。

## 常用搜索查询语法

### 按基因名搜索
```
query=gene:BRCA1
```

### 按生物体搜索
```
query=organism_id:9606
```

### 按蛋白质名搜索
```
query=protein_name:kinase
```

### 按功能注释搜索
```
query=cc_function:"DNA binding"
```

### 组合查询
```
query=gene:EGFR AND organism_id:9606 AND reviewed:true
```

### 按序列长度搜索
```
query=length:[100 TO 500]
```

## 常用字段

| 字段 | 描述 |
|------|------|
| `accession` | UniProt 登录号 |
| `gene_primary` | 基因名 |
| `protein_name` | 蛋白质名 |
| `organism_name` | 生物体名 |
| `organism_id` | 分类 ID |
| `length` | 序列长度 |
| `mass` | 分子量 |
| `cc_function` | 功能注释 |
| `cc_subcellular_location` | 亚细胞定位 |
| `ft_domain` | 结构域 |
| `xref_pdb` | PDB 交叉引用 |

## 使用建议

1. **使用 reviewed 过滤**: `reviewed:true` 仅返回 Swiss-Prot（人工审核）条目
2. **指定字段**: 使用 `fields` 参数减少返回数据量
3. **分页处理**: 使用 cursor 分页处理大量结果
4. **缓存结果**: 蛋白质信息不常变化，建议缓存

## 示例代码

可运行的 Python 示例代码请参见 [examples.py](./examples.py)。

## 参考链接

- [UniProt REST API 文档](https://www.uniprot.org/help/api_queries)
- [UniProt 搜索语法](https://www.uniprot.org/help/query-fields)
- [UniProt ID 映射](https://www.uniprot.org/help/id_mapping)
