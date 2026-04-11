#!/usr/bin/env python3
"""
RCSB PDB API 示例代码

本脚本演示如何使用 RCSB PDB API 访问蛋白质结构数据。
包括：获取结构信息、搜索结构、下载 PDB 文件、获取配体信息。

运行要求：pip install requests
"""

import time
import requests
from typing import Dict, List, Optional

# RCSB PDB API 基础 URLs
DATA_API_URL = "https://data.rcsb.org/rest/v1/core"
SEARCH_API_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
FILES_URL = "https://files.rcsb.org/download"


def get_entry_info(pdb_id: str) -> Dict:
    """
    获取 PDB 结构的基本信息

    参数:
        pdb_id: PDB ID (例如 "1IEP")

    返回:
        包含结构信息的字典
    """
    url = f"{DATA_API_URL}/entry/{pdb_id}"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def get_pubmed_info(pdb_id: str) -> Dict:
    """
    获取与 PDB 结构关联的 PubMed 摘要信息

    参数:
        pdb_id: PDB ID

    返回:
        包含 PubMed 信息的字典
    """
    url = f"{DATA_API_URL}/pubmed/{pdb_id}"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def get_polymer_entity(pdb_id: str, entity_id: int = 1) -> Dict:
    """
    获取 PDB 结构中指定聚合物实体的信息（蛋白质链等）

    参数:
        pdb_id: PDB ID
        entity_id: 实体编号（从1开始）

    返回:
        聚合物实体信息字典
    """
    url = f"{DATA_API_URL}/polymer_entity/{pdb_id}/{entity_id}"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def search_by_full_text(
    query_value: str,
    return_type: str = "entry",
    limit: int = 10
) -> Dict:
    """
    使用全文搜索 PDB 结构

    参数:
        query_value: 搜索关键词
        return_type: 返回类型 (entry, polymer_entity 等)
        limit: 返回结果数量限制

    返回:
        包含搜索结果的字典
    """
    query = {
        "query": {
            "type": "terminal",
            "service": "full_text",
            "parameters": {
                "value": query_value
            }
        },
        "return_type": return_type,
        "request_options": {
            "paginate": {
                "start": 0,
                "rows": limit
            }
        }
    }

    response = requests.post(SEARCH_API_URL, json=query)
    response.raise_for_status()
    return response.json()


def search_by_attribute(
    attribute: str,
    operator: str,
    value,
    return_type: str = "entry",
    limit: int = 10
) -> Dict:
    """
    按属性搜索 PDB 结构

    参数:
        attribute: 属性名称 (例如 "rcsb_entry_info.resolution_combined")
        operator: 操作符 (exact_match, less_or_equal, greater 等)
        value: 比较值
        return_type: 返回类型
        limit: 返回结果数量限制

    返回:
        包含搜索结果的字典
    """
    query = {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": attribute,
                "operator": operator,
                "value": value
            }
        },
        "return_type": return_type,
        "request_options": {
            "paginate": {
                "start": 0,
                "rows": limit
            }
        }
    }

    response = requests.post(SEARCH_API_URL, json=query)
    response.raise_for_status()
    return response.json()


def download_pdb_file(pdb_id: str, format: str = "pdb") -> str:
    """
    下载 PDB 文件

    参数:
        pdb_id: PDB ID
        format: 文件格式 (pdb, cif)

    返回:
        PDB 文件内容（文本）
    """
    ext = "pdb" if format == "pdb" else "cif"
    url = f"{FILES_URL}/{pdb_id}.{ext}"
    response = requests.get(url)
    response.raise_for_status()
    return response.text


def get_chemcomp_info(chemcomp_id: str) -> Dict:
    """
    获取化学组分（配体）信息

    参数:
        chemcomp_id: 化学组分 ID (例如 "ATP", "HEM")

    返回:
        包含化学组分信息的字典
    """
    url = f"{DATA_API_URL}/chemcomp/{chemcomp_id}"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def example_1_get_structure_info():
    """
    示例1: 按 PDB ID 获取结构信息
    """
    print("=" * 60)
    print("示例1: 按 PDB ID 获取结构信息")
    print("=" * 60)

    pdb_id = "1IEP"  # c-Abl 激酶与 STI-571 (伊马替尼) 复合物
    print(f"查询 PDB ID: {pdb_id}")

    # 获取基本信息
    entry_info = get_entry_info(pdb_id)

    # 提取关键信息
    title = entry_info.get("struct", {}).get("title", "N/A")

    # 获取实验信息
    exptl = entry_info.get("exptl", [{}])[0]
    method = exptl.get("method", "N/A")
    resolution = exptl.get("resolution", [None])[0]

    # 获取发布日期
    release_date = entry_info.get("rcsb_accession_info", {}).get(
        "initial_release_date", "N/A"
    )

    print(f"\n标题: {title[:80]}..." if len(title) > 80 else f"\n标题: {title}")
    print(f"实验方法: {method}")
    if resolution:
        print(f"分辨率: {resolution} Å")
    print(f"发布日期: {release_date}")

    return pdb_id


def example_2_get_publication_info(pdb_id: str):
    """
    示例2: 获取与结构关联的文献信息
    """
    print("\n" + "=" * 60)
    print("示例2: 获取文献信息")
    print("=" * 60)

    print(f"查询 PDB ID: {pdb_id}")

    try:
        # 从 entry 端点获取主要引用信息
        entry_info = get_entry_info(pdb_id)
        citation = entry_info.get("rcsb_primary_citation", {})

        title = citation.get("title", "N/A")
        authors = citation.get("rcsb_authors", [])
        journal = citation.get("journal_abbrev", "N/A")
        year = citation.get("year", "N/A")

        print(f"\n文献标题: {title}")
        print(f"作者: {', '.join(authors[:5])}{'...' if len(authors) > 5 else ''}")
        print(f"期刊: {journal}")
        print(f"年份: {year}")
    except Exception as e:
        print(f"获取文献信息失败: {e}")


def example_3_search_by_keyword():
    """
    示例3: 按关键词搜索结构
    """
    print("\n" + "=" * 60)
    print("示例3: 按关键词搜索结构")
    print("=" * 60)

    keyword = "kinase inhibitor"
    print(f"搜索关键词: {keyword}")

    try:
        result = search_by_full_text(keyword, limit=5)

        total_count = result.get("total_count", 0)
        hits = result.get("result_set", [])

        print(f"\n找到 {total_count} 个结构")
        print("前5个结果:")

        for hit in hits:
            pdb_id = hit.get("identifier", "")
            print(f"  - {pdb_id}")

        return hits
    except Exception as e:
        print(f"搜索失败: {e}")
        return []


def example_4_search_by_resolution():
    """
    示例4: 按分辨率搜索高分辨率结构
    """
    print("\n" + "=" * 60)
    print("示例4: 按分辨率搜索结构 (≤ 1.5 Å)")
    print("=" * 60)

    try:
        result = search_by_attribute(
            attribute="rcsb_entry_info.resolution_combined",
            operator="less_or_equal",
            value=1.5,
            limit=5
        )

        total_count = result.get("total_count", 0)
        hits = result.get("result_set", [])

        print(f"\n找到 {total_count} 个高分辨率结构 (≤ 1.5 Å)")
        print("前5个结果:")

        for hit in hits:
            pdb_id = hit.get("identifier", "")
            print(f"  - {pdb_id}")
    except Exception as e:
        print(f"搜索失败: {e}")


def example_5_download_pdb():
    """
    示例5: 下载 PDB 文件
    """
    print("\n" + "=" * 60)
    print("示例5: 下载 PDB 文件")
    print("=" * 60)

    pdb_id = "1IEP"
    print(f"下载 PDB ID: {pdb_id}")

    try:
        # 下载 PDB 格式
        pdb_content = download_pdb_file(pdb_id, format="pdb")

        # 显示文件前几行
        lines = pdb_content.split("\n")[:10]
        print(f"\n文件前10行:")
        for line in lines:
            print(f"  {line}")

        print(f"\n文件总大小: {len(pdb_content)} 字节")
    except Exception as e:
        print(f"下载失败: {e}")


def example_6_get_chemcomp():
    """
    示例6: 获取化学组分（配体）信息
    """
    print("\n" + "=" * 60)
    print("示例6: 获取化学组分信息")
    print("=" * 60)

    chemcomp_id = "ATP"
    print(f"查询化学组分: {chemcomp_id}")

    try:
        chemcomp_info = get_chemcomp_info(chemcomp_id)
        chem_comp = chemcomp_info.get("chem_comp", {})

        name = chem_comp.get("name", "N/A")
        formula = chem_comp.get("formula", "N/A")
        weight = chem_comp.get("formula_weight", "N/A")

        print(f"\n名称: {name}")
        print(f"分子式: {formula}")
        print(f"分子量: {weight}")
    except Exception as e:
        print(f"获取化学组分信息失败: {e}")


def example_7_get_entity_info(pdb_id: str):
    """
    示例7: 获取聚合物实体信息（蛋白质序列等）
    """
    print("\n" + "=" * 60)
    print("示例7: 获取聚合物实体信息")
    print("=" * 60)

    print(f"查询 PDB ID: {pdb_id}")

    try:
        # 获取实体数量
        identifiers = get_entry_info(pdb_id).get("rcsb_entry_container_identifiers", {})
        entity_ids = identifiers.get("polymer_entity_ids", [])

        print(f"\n共有 {len(entity_ids)} 个聚合物实体")

        # 获取每个实体的信息（最多显示3个）
        for i, eid in enumerate(entity_ids[:3]):
            entity = get_polymer_entity(pdb_id, int(eid))

            entity_type = entity.get("entity_poly", {}).get("type", "未知")
            organism = entity.get("rcsb_entity_source_organism", [{}])[0].get(
                "scientific_name", "未知"
            )
            sequence = entity.get("entity_poly", {}).get("pdbx_seq_one_letter_code_can", "")

            print(f"\n实体 {eid}:")
            print(f"  类型: {entity_type}")
            print(f"  来源: {organism}")
            if sequence:
                print(f"  序列长度: {len(sequence)} 氨基酸")
                print(f"  序列 (前30aa): {sequence[:30]}...")
    except Exception as e:
        print(f"获取实体信息失败: {e}")


def main():
    """
    运行所有示例
    """
    print("RCSB PDB API 示例程序")
    print("=" * 60)
    print("注意: 请适度使用 API，添加适当延时")
    print("=" * 60)

    # 示例1: 获取结构信息
    pdb_id = example_1_get_structure_info()

    time.sleep(0.5)

    # 示例2: 获取文献信息
    example_2_get_publication_info(pdb_id)

    time.sleep(0.5)

    # 示例3: 按关键词搜索
    example_3_search_by_keyword()

    time.sleep(0.5)

    # 示例4: 按分辨率搜索
    example_4_search_by_resolution()

    time.sleep(0.5)

    # 示例5: 下载 PDB 文件
    example_5_download_pdb()

    time.sleep(0.5)

    # 示例6: 获取化学组分信息
    example_6_get_chemcomp()

    time.sleep(0.5)

    # 示例7: 获取实体信息
    example_7_get_entity_info(pdb_id)

    print("\n" + "=" * 60)
    print("示例运行完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
