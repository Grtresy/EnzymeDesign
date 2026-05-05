#!/usr/bin/env python3
"""
UniProt API 示例代码

本脚本演示如何使用 UniProt REST API 访问蛋白质数据。
包括：获取蛋白质信息、搜索蛋白质、获取序列、ID 映射。

运行要求：pip install requests
"""

import time
import requests
from typing import Dict, List, Optional

# UniProt REST API 基础 URL
BASE_URL = "https://rest.uniprot.org/uniprotkb"


def get_protein_info(uniprot_id: str, format: str = "json") -> Dict:
    """
    根据 UniProt ID 获取蛋白质详细信息

    参数:
        uniprot_id: UniProt 登录号 (例如 "P00533")
        format: 返回格式 (json, xml)

    返回:
        包含蛋白质信息的字典
    """
    url = f"{BASE_URL}/{uniprot_id}"
    params = {"format": format}

    response = requests.get(url, params=params)
    response.raise_for_status()

    if format == "json":
        return response.json()
    return response.text


def search_proteins(
    query: str,
    size: int = 10,
    fields: Optional[List[str]] = None,
    format: str = "json"
) -> Dict:
    """
    搜索蛋白质

    参数:
        query: 搜索查询
        size: 返回结果数量
        fields: 指定返回字段列表
        format: 返回格式

    返回:
        包含搜索结果的字典
    """
    url = f"{BASE_URL}/search"
    params = {
        "query": query,
        "size": size,
        "format": format
    }

    if fields:
        params["fields"] = ",".join(fields)

    response = requests.get(url, params=params)
    response.raise_for_status()

    if format == "json":
        return response.json()
    return response.text


def get_protein_sequence(uniprot_id: str) -> str:
    """
    获取蛋白质序列（FASTA 格式）

    参数:
        uniprot_id: UniProt 登录号

    返回:
        FASTA 格式的蛋白质序列
    """
    url = f"{BASE_URL}/{uniprot_id}.fasta"
    response = requests.get(url)
    response.raise_for_status()
    return response.text


def get_protein_tsv(
    uniprot_ids: List[str],
    fields: List[str]
) -> str:
    """
    批量获取指定字段的蛋白质信息（TSV 格式）

    参数:
        uniprot_ids: UniProt ID 列表
        fields: 字段列表

    返回:
        TSV 格式的数据
    """
    # 使用 POST 请求批量获取
    url = f"{BASE_URL}/search"
    query = " OR ".join([f"accession:{uid}" for uid in uniprot_ids])
    params = {
        "query": query,
        "fields": ",".join(fields),
        "format": "tsv",
        "size": len(uniprot_ids)
    }

    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.text


def map_ids(
    ids: List[str],
    from_db: str = "UniProtKB_AC-ID",
    to_db: str = "PDB"
) -> Dict:
    """
    ID 映射（将 UniProt ID 映射到其他数据库）

    参数:
        ids: 要映射的 ID 列表
        from_db: 源数据库
        to_db: 目标数据库

    返回:
        映射结果
    """
    # 提交映射任务
    url = "https://rest.uniprot.org/idmapping/run"
    data = {
        "from": from_db,
        "to": to_db,
        "ids": ",".join(ids)
    }

    response = requests.post(url, data=data)
    response.raise_for_status()
    job_info = response.json()
    job_id = job_info["jobId"]

    # 等待任务完成
    status_url = f"https://rest.uniprot.org/idmapping/status/{job_id}"
    for _ in range(30):  # 最多等待30秒
        status_response = requests.get(status_url)
        status_response.raise_for_status()
        status_data = status_response.json()

        if "results" in status_data:
            return status_data
        elif "error" in status_data:
            raise Exception(f"ID 映射失败: {status_data['error']}")

        time.sleep(1)

    raise Exception("ID 映射超时")


def parse_fasta(fasta_text: str) -> Dict[str, str]:
    """
    解析 FASTA 格式序列

    参数:
        fasta_text: FASTA 格式文本

    返回:
        {header: sequence} 字典
    """
    sequences = {}
    current_header = None
    current_seq = []

    for line in fasta_text.split("\n"):
        if line.startswith(">"):
            if current_header:
                sequences[current_header] = "".join(current_seq)
            current_header = line[1:]
            current_seq = []
        else:
            current_seq.append(line)

    if current_header:
        sequences[current_header] = "".join(current_seq)

    return sequences


def example_1_get_protein_info():
    """
    示例1: 按 UniProt ID 获取蛋白质信息
    """
    print("=" * 60)
    print("示例1: 按 UniProt ID 获取蛋白质信息")
    print("=" * 60)

    uniprot_id = "P00533"  # EGFR (表皮生长因子受体)
    print(f"查询 UniProt ID: {uniprot_id}")

    protein = get_protein_info(uniprot_id)

    # 提取关键信息
    accession = protein.get("primaryAccession", "N/A")

    # 蛋白质名称
    protein_desc = protein.get("proteinDescription", {})
    rec_name = protein_desc.get("recommendedName", {})
    full_name = rec_name.get("fullName", {}).get("value", "N/A")

    # 基因名
    genes = protein.get("genes", [])
    gene_name = genes[0].get("geneName", {}).get("value", "N/A") if genes else "N/A"

    # 生物体
    organism = protein.get("organism", {})
    organism_name = organism.get("scientificName", "N/A")
    taxon_id = organism.get("taxonId", "N/A")

    # 序列信息
    sequence = protein.get("sequence", {})
    seq_length = sequence.get("length", "N/A")
    mol_weight = sequence.get("molWeight", "N/A")

    print(f"\n登录号: {accession}")
    print(f"蛋白质名: {full_name}")
    print(f"基因名: {gene_name}")
    print(f"生物体: {organism_name} (Taxon: {taxon_id})")
    print(f"序列长度: {seq_length} 氨基酸")
    print(f"分子量: {mol_weight} Da")

    return uniprot_id


def example_2_get_protein_sequence(uniprot_id: str):
    """
    示例2: 获取蛋白质序列
    """
    print("\n" + "=" * 60)
    print("示例2: 获取蛋白质序列")
    print("=" * 60)

    print(f"查询 UniProt ID: {uniprot_id}")

    fasta = get_protein_sequence(uniprot_id)
    sequences = parse_fasta(fasta)

    for header, sequence in sequences.items():
        print(f"\nFASTA 头: {header[:80]}...")
        print(f"序列长度: {len(sequence)}")
        print(f"序列 (前60aa): {sequence[:60]}...")


def example_3_search_by_gene():
    """
    示例3: 按基因名搜索蛋白质
    """
    print("\n" + "=" * 60)
    print("示例3: 按基因名搜索蛋白质")
    print("=" * 60)

    gene_name = "BRCA1"
    print(f"搜索基因: {gene_name}")

    # 仅搜索人工审核的条目
    query = f"gene:{gene_name} AND reviewed:true"
    result = search_proteins(
        query=query,
        size=5,
        fields=["accession", "gene_primary", "protein_name", "organism_name", "length"]
    )

    total = result.get("total", 0)
    results = result.get("results", [])

    print(f"\n找到 {total} 个条目")
    print("前5个结果:")

    for entry in results:
        accession = entry.get("primaryAccession", "N/A")
        gene = entry.get("genes", [{}])[0].get("geneName", {}).get("value", "N/A")
        protein_name = entry.get("proteinDescription", {}).get(
            "recommendedName", {}
        ).get("fullName", {}).get("value", "N/A")
        organism = entry.get("organism", {}).get("scientificName", "N/A")

        print(f"\n  登录号: {accession}")
        print(f"  基因: {gene}")
        print(f"  蛋白质: {protein_name[:50]}...")
        print(f"  生物体: {organism}")


def example_4_search_by_organism():
    """
    示例4: 按生物体搜索蛋白质
    """
    print("\n" + "=" * 60)
    print("示例4: 按生物体搜索蛋白质")
    print("=" * 60)

    organism = "Homo sapiens"
    protein_keyword = "kinase"
    print(f"搜索: {organism} 中的 {protein_keyword}")

    query = f'organism_name:"{organism}" AND protein_name:{protein_keyword} AND reviewed:true'
    result = search_proteins(
        query=query,
        size=5,
        fields=["accession", "gene_primary", "protein_name"]
    )

    total = result.get("total", 0)
    results = result.get("results", [])

    print(f"\n找到 {total} 个条目")
    print("前5个结果:")

    for entry in results:
        accession = entry.get("primaryAccession", "N/A")
        gene = entry.get("genes", [{}])[0].get("geneName", {}).get("value", "N/A")
        print(f"  {accession} - {gene}")


def example_5_get_function_annotation():
    """
    示例5: 获取功能注释
    """
    print("\n" + "=" * 60)
    print("示例5: 获取功能注释")
    print("=" * 60)

    uniprot_id = "P00533"
    print(f"查询 UniProt ID: {uniprot_id}")

    protein = get_protein_info(uniprot_id)

    # 获取功能注释
    comments = protein.get("comments", [])

    # 提取功能注释
    functions = []
    for comment in comments:
        if comment.get("commentType") == "FUNCTION":
            texts = comment.get("texts", [])
            for text in texts:
                value = text.get("value", "")
                if value:
                    functions.append(value)

    if functions:
        print("\n功能注释:")
        for i, func in enumerate(functions[:3], 1):
            print(f"{i}. {func[:200]}{'...' if len(func) > 200 else ''}")
    else:
        print("未找到功能注释")

    # 获取亚细胞定位
    locations = []
    for comment in comments:
        if comment.get("commentType") == "SUBCELLULAR LOCATION":
            locs = comment.get("subcellularLocations", [])
            for loc in locs:
                location = loc.get("location", {}).get("value", "")
                if location:
                    locations.append(location)

    if locations:
        print("\n亚细胞定位:")
        for loc in locations[:3]:
            print(f"  - {loc}")


def example_6_batch_query():
    """
    示例6: 批量查询多个蛋白质
    """
    print("\n" + "=" * 60)
    print("示例6: 批量查询多个蛋白质")
    print("=" * 60)

    uniprot_ids = ["P00533", "P15056", "P04637"]  # EGFR, BRAF, TP53
    print(f"查询 UniProt IDs: {uniprot_ids}")

    fields = ["accession", "gene_primary", "protein_name", "length", "mass"]

    tsv_data = get_protein_tsv(uniprot_ids, fields)

    # 解析 TSV
    lines = tsv_data.strip().split("\n")
    header = lines[0].split("\t")

    print(f"\n字段: {header}")
    print("\n结果:")

    for line in lines[1:]:
        values = line.split("\t")
        if len(values) >= len(header):
            print(f"\n  登录号: {values[0]}")
            print(f"  基因: {values[1]}")
            print(f"  蛋白质: {values[2][:50]}...")
            print(f"  长度: {values[3]} aa")
            print(f"  分子量: {values[4]} Da")


def example_7_search_with_sequence_length():
    """
    示例7: 按序列长度范围搜索
    """
    print("\n" + "=" * 60)
    print("示例7: 按序列长度范围搜索")
    print("=" * 60)

    print("搜索: 长度 100-200 氨基酸的人类蛋白质")

    query = "organism_id:9606 AND length:[100 TO 200] AND reviewed:true"
    result = search_proteins(
        query=query,
        size=5,
        fields=["accession", "gene_primary", "length"]
    )

    total = result.get("total", 0)
    results = result.get("results", [])

    print(f"\n找到 {total} 个条目")
    print("前5个结果:")

    for entry in results:
        accession = entry.get("primaryAccession", "N/A")
        gene = entry.get("genes", [{}])[0].get("geneName", {}).get("value", "N/A")
        length = entry.get("sequence", {}).get("length", "N/A")
        print(f"  {accession} - {gene} ({length} aa)")


def main():
    """
    运行所有示例
    """
    print("UniProt API 示例程序")
    print("=" * 60)
    print("注意: 请适度使用 API，添加适当延时")
    print("=" * 60)

    # 示例1: 获取蛋白质信息
    uniprot_id = example_1_get_protein_info()

    time.sleep(0.5)

    # 示例2: 获取序列
    example_2_get_protein_sequence(uniprot_id)

    time.sleep(0.5)

    # 示例3: 按基因名搜索
    example_3_search_by_gene()

    time.sleep(0.5)

    # 示例4: 按生物体搜索
    example_4_search_by_organism()

    time.sleep(0.5)

    # 示例5: 获取功能注释
    example_5_get_function_annotation()

    time.sleep(0.5)

    # 示例6: 批量查询
    example_6_batch_query()

    time.sleep(0.5)

    # 示例7: 按序列长度搜索
    example_7_search_with_sequence_length()

    print("\n" + "=" * 60)
    print("示例运行完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
