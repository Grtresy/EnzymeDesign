#!/usr/bin/env python3
"""
InterPro API 示例代码

本脚本演示如何使用 InterPro REST API 访问蛋白质家族和结构域数据。
包括：获取条目信息、查询蛋白质注释、分页遍历、按类型过滤。

运行要求：pip install requests
"""

import time
import requests
from typing import Dict, List, Optional, Generator

# InterPro REST API 基础 URL
BASE_URL = "https://www.ebi.ac.uk/interpro/api"


def get_entry(accession: str, extra_fields: Optional[List[str]] = None) -> Dict:
    """
    获取 InterPro 条目详细信息

    参数:
        accession: InterPro 登录号 (例如 "IPR000001")
        extra_fields: 额外返回字段列表

    返回:
        包含条目信息的字典
    """
    url = f"{BASE_URL}/entry/InterPro/{accession}"
    params = {}

    if extra_fields:
        params["extra_fields"] = ",".join(extra_fields)

    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def get_protein_annotations(
    uniprot_id: str,
    extra_fields: Optional[List[str]] = None
) -> Dict:
    """
    获取 UniProt 蛋白质的 InterPro 注释

    参数:
        uniprot_id: UniProt 登录号 (例如 "P00533")
        extra_fields: 额外返回字段列表

    返回:
        包含蛋白质注释的字典（包含 results 列表和 count）
    """
    # 正确的端点是 /api/entry/InterPro/protein/uniprot/{accession}
    url = f"{BASE_URL}/entry/InterPro/protein/uniprot/{uniprot_id}"
    params = {}

    if extra_fields:
        params["extra_fields"] = ",".join(extra_fields)

    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def list_entries(
    page_size: int = 20,
    entry_type: Optional[str] = None,
    cursor: Optional[str] = None
) -> Dict:
    """
    分页列出 InterPro 条目

    参数:
        page_size: 每页返回数量 (最大 200)
        entry_type: 条目类型 (domain, family, repeat, site)
        cursor: 分页游标

    返回:
        包含条目列表和分页信息的字典
    """
    url = f"{BASE_URL}/entry/InterPro"
    params = {"page_size": min(page_size, 200)}

    if entry_type:
        params["type"] = entry_type

    if cursor:
        # cursor 是完整的 URL
        url = cursor
        params = {}

    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def search_entries(query: str, page_size: int = 20) -> Dict:
    """
    搜索 InterPro 条目

    参数:
        query: 搜索关键词
        page_size: 每页返回数量

    返回:
        包含搜索结果的字典
    """
    url = f"{BASE_URL}/entry/InterPro"
    params = {
        "page_size": min(page_size, 200),
        "search": query
    }

    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def iterate_all_entries(
    page_size: int = 200,
    entry_type: Optional[str] = None,
    max_pages: Optional[int] = None
) -> Generator[Dict, None, None]:
    """
    遍历所有 InterPro 条目（生成器）

    参数:
        page_size: 每页返回数量
        entry_type: 条目类型过滤器
        max_pages: 最大页数限制（用于测试）

    生成:
        单个条目字典
    """
    url = f"{BASE_URL}/entry/InterPro"
    params = {"page_size": min(page_size, 200)}

    if entry_type:
        params["type"] = entry_type

    page_count = 0

    while url:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        # 生成当前页的条目
        for entry in data.get("results", []):
            yield entry

        # 获取下一页 URL
        url = data.get("next")
        params = {}  # 后续请求 URL 已包含参数

        page_count += 1
        if max_pages and page_count >= max_pages:
            break

        # 添加延时避免请求过快
        time.sleep(0.5)


def get_entry_by_database(
    database: str,
    accession: str
) -> Dict:
    """
    获取成员数据库的条目信息

    参数:
        database: 数据库名 (pfam, smart, prosite, cdd 等)
        accession: 条目登录号

    返回:
        条目信息字典
    """
    url = f"{BASE_URL}/entry/{database}/{accession}"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def example_1_get_entry_info():
    """
    示例1: 查询 InterPro 条目信息
    """
    print("=" * 60)
    print("示例1: 查询 InterPro 条目信息")
    print("=" * 60)

    accession = "IPR000001"  # Kringle domain
    print(f"查询 InterPro ID: {accession}")

    entry = get_entry(accession)

    # 提取元数据
    metadata = entry.get("metadata", {})

    # name 可能是字符串或字典
    name_data = metadata.get("name", "N/A")
    if isinstance(name_data, dict):
        name = name_data.get("name", "N/A")
    else:
        name = name_data

    entry_type = metadata.get("type", "N/A")

    # description 是包含 text 字段的字典列表
    desc_list = metadata.get("description", [])
    if desc_list and isinstance(desc_list[0], dict):
        description = desc_list[0].get("text", "N/A")
        # 去除 HTML 标签
        import re
        description = re.sub(r'<[^>]+>', '', description)
    else:
        description = "N/A"

    print(f"\n登录号: {accession}")
    print(f"名称: {name}")
    print(f"类型: {entry_type}")
    print(f"描述: {description[:200]}{'...' if len(description) > 200 else ''}")

    # 获取 GO 术语
    go_terms = metadata.get("go_terms", [])
    if go_terms:
        print(f"\n关联 GO 术语 ({len(go_terms)} 个):")
        for go in go_terms[:3]:
            go_id = go.get("identifier", "N/A")
            go_name = go.get("name", "N/A")
            print(f"  - {go_id}: {go_name}")

    # 获取成员数据库交叉引用
    member_dbs = metadata.get("member_databases", {})
    if member_dbs:
        print(f"\n成员数据库交叉引用:")
        for db, entries in list(member_dbs.items())[:3]:
            print(f"  - {db}: {list(entries.keys())[:3]}")

    return accession


def example_2_get_protein_annotations():
    """
    示例2: 获取蛋白质的 InterPro 注释
    """
    print("\n" + "=" * 60)
    print("示例2: 获取蛋白质的 InterPro 注释")
    print("=" * 60)

    uniprot_id = "P00533"  # EGFR
    print(f"查询 UniProt ID: {uniprot_id}")

    result = get_protein_annotations(uniprot_id)

    count = result.get("count", 0)
    entries = result.get("results", [])

    print(f"\n找到 {count} 个 InterPro 注释:")

    # 按类型分组
    by_type = {}
    for entry in entries[:10]:
        metadata = entry.get("metadata", {})
        acc = metadata.get("accession", "N/A")
        name = _get_name(metadata)
        entry_type = metadata.get("type", "unknown")

        if entry_type not in by_type:
            by_type[entry_type] = []
        by_type[entry_type].append((acc, name))

        # 获取位置信息
        proteins = entry.get("proteins", [])
        if proteins:
            locations = proteins[0].get("entry_protein_locations", [])
            if locations and locations[0].get("fragments"):
                frag = locations[0]["fragments"][0]
                start = frag.get("start", "?")
                end = frag.get("end", "?")

    for entry_type, items in by_type.items():
        print(f"\n  {entry_type}:")
        for acc, entry_name in items[:3]:
            print(f"    - {acc}: {entry_name[:50]}")

    return uniprot_id


def _get_name(metadata: Dict) -> str:
    """从 metadata 中提取名称（处理字典或字符串格式）"""
    name_data = metadata.get("name", "N/A")
    if isinstance(name_data, dict):
        return name_data.get("name", "N/A")
    return name_data


def example_3_filter_by_type():
    """
    示例3: 按类型过滤条目
    """
    print("\n" + "=" * 60)
    print("示例3: 按类型过滤条目")
    print("=" * 60)

    entry_type = "domain"
    print(f"过滤类型: {entry_type}")

    result = list_entries(page_size=5, entry_type=entry_type)

    results = result.get("results", [])
    count = result.get("count", "N/A")

    print(f"\n总计: {count} 个 {entry_type} 类型条目")
    print("前 5 个结果:")

    for entry in results:
        metadata = entry.get("metadata", {})
        acc = metadata.get("accession", "N/A")
        name = _get_name(metadata)
        print(f"  - {acc}: {name[:60]}")


def example_4_paginate_entries():
    """
    示例4: 分页遍历条目
    """
    print("\n" + "=" * 60)
    print("示例4: 分页遍历条目")
    print("=" * 60)

    print("获取前 3 页 InterPro 条目...")

    page_count = 0
    total_entries = 0

    # 使用生成器遍历，限制 3 页
    for entry in iterate_all_entries(page_size=20, max_pages=3):
        metadata = entry.get("metadata", {})
        acc = metadata.get("accession", "N/A")
        name = _get_name(metadata)

        if total_entries < 5:  # 只显示前 5 个
            print(f"  {acc}: {name[:50]}")

        total_entries += 1

    print(f"\n共遍历 {total_entries} 个条目")


def example_5_search_entries():
    """
    示例5: 搜索条目
    """
    print("\n" + "=" * 60)
    print("示例5: 搜索条目")
    print("=" * 60)

    query = "kinase"
    print(f"搜索关键词: {query}")

    result = search_entries(query, page_size=5)

    results = result.get("results", [])
    count = result.get("count", "N/A")

    print(f"\n找到约 {count} 个匹配条目")
    print("前 5 个结果:")

    for entry in results:
        metadata = entry.get("metadata", {})
        acc = metadata.get("accession", "N/A")
        name = _get_name(metadata)
        entry_type = metadata.get("type", "N/A")
        print(f"  - {acc} [{entry_type}]: {name[:50]}")


def example_6_member_database():
    """
    示例6: 查询成员数据库条目
    """
    print("\n" + "=" * 60)
    print("示例6: 查询成员数据库条目 (Pfam)")
    print("=" * 60)

    database = "pfam"
    accession = "PF00001"  # 7 transmembrane receptor (rhodopsin family)
    print(f"查询 {database}: {accession}")

    try:
        entry = get_entry_by_database(database, accession)

        metadata = entry.get("metadata", {})
        name = _get_name(metadata)

        # description 是包含 text 字段的字典列表
        desc_list = metadata.get("description", [])
        if desc_list and isinstance(desc_list[0], dict):
            description = desc_list[0].get("text", "N/A")
            # 去除 HTML 标签
            import re
            description = re.sub(r'<[^>]+>', '', description)
        else:
            description = "N/A"

        print(f"\nPfam ID: {accession}")
        print(f"名称: {name}")
        print(f"描述: {description[:150]}...")

        # 获取关联的 InterPro 条目
        intp = metadata.get("integrated", "N/A")
        if intp:
            print(f"关联 InterPro: {intp}")

    except requests.HTTPError as e:
        print(f"请求失败: {e}")


def example_7_get_entry_statistics():
    """
    示例7: 获取条目统计信息
    """
    print("\n" + "=" * 60)
    print("示例7: 获取条目统计信息")
    print("=" * 60)

    # 使用 Protein kinase-like domain (存在且常用)
    accession = "IPR011009"
    print(f"查询 InterPro ID: {accession}")

    try:
        entry = get_entry(accession)

        metadata = entry.get("metadata", {})
        name = _get_name(metadata)

        print(f"\n条目: {name}")

        # 获取计数器信息
        counters = metadata.get("counters", {})
        if counters:
            print("\n统计信息:")
            print(f"  关联蛋白质: {counters.get('proteins', 'N/A')}")
            print(f"  关联结构: {counters.get('structures', 'N/A')}")
            print(f"  关联物种: {counters.get('taxa', 'N/A')}")
            print(f"  关联 Proteome: {counters.get('proteomes', 'N/A')}")
    except requests.HTTPError as e:
        print(f"请求失败: {e}")
        print("跳过此示例...")


def main():
    """
    运行所有示例
    """
    print("InterPro API 示例程序")
    print("=" * 60)
    print("注意: 请适度使用 API，添加适当延时")
    print("=" * 60)

    # 示例1: 查询条目信息
    example_1_get_entry_info()

    time.sleep(0.5)

    # 示例2: 获取蛋白质注释
    example_2_get_protein_annotations()

    time.sleep(0.5)

    # 示例3: 按类型过滤
    example_3_filter_by_type()

    time.sleep(0.5)

    # 示例4: 分页遍历
    example_4_paginate_entries()

    time.sleep(0.5)

    # 示例5: 搜索条目
    example_5_search_entries()

    time.sleep(0.5)

    # 示例6: 查询成员数据库
    example_6_member_database()

    time.sleep(0.5)

    # 示例7: 获取统计信息
    example_7_get_entry_statistics()

    print("\n" + "=" * 60)
    print("示例运行完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
