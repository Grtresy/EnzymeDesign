#!/usr/bin/env python3
"""
PubMed E-utilities API 请求示例

本脚本演示如何使用 NCBI E-utilities API 访问 PubMed 数据库。
包括：搜索文献、获取文献详情、批量获取文献信息。

运行方式:
    # 真实请求（可选设置 API Key）
    python examples.py

    # 使用 API Key 提高速率限制
    NCBI_API_KEY=your-key python examples.py

    # 仅运行 mock 测试
    pytest examples.py -v
"""

import os
import re
import time
import asyncio
from typing import List, Dict, Optional
import xml.etree.ElementTree as ET

import httpx
import pytest
from pytest_httpx import HTTPXMock


# ============ 配置 ============
API_KEY = os.environ.get("NCBI_API_KEY")
BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# 速率限制延迟（秒）
RATE_LIMIT_DELAY = 0.1 if API_KEY else 0.34


# ============ 异步请求 ============
async def search_pubmed_async(
    query: str,
    retmax: int = 10,
    retstart: int = 0,
    sort: str = "relevance"
) -> Dict:
    """搜索 PubMed 文献（异步版本）"""
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": retmax,
        "retstart": retstart,
        "sort": sort,
        "retmode": "json"
    }
    if API_KEY:
        params["api_key"] = API_KEY

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/esearch.fcgi", params=params)
        response.raise_for_status()
        return response.json()


async def get_article_summaries_async(pmids: List[str]) -> Dict:
    """根据 PMID 获取文献简要信息（异步版本）"""
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "json"
    }
    if API_KEY:
        params["api_key"] = API_KEY

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/esummary.fcgi", params=params)
        response.raise_for_status()
        return response.json()


async def get_article_details_async(pmids: List[str]) -> str:
    """根据 PMID 获取文献详细信息（XML格式，异步版本）"""
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml"
    }
    if API_KEY:
        params["api_key"] = API_KEY

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/efetch.fcgi", params=params)
        response.raise_for_status()
        return response.text


# ============ 同步请求 ============
def search_pubmed(
    query: str,
    retmax: int = 10,
    retstart: int = 0,
    sort: str = "relevance"
) -> Dict:
    """搜索 PubMed 文献（同步版本）"""
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": retmax,
        "retstart": retstart,
        "sort": sort,
        "retmode": "json"
    }
    if API_KEY:
        params["api_key"] = API_KEY

    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/esearch.fcgi", params=params)
        response.raise_for_status()
        return response.json()


def get_article_summaries(pmids: List[str]) -> Dict:
    """根据 PMID 获取文献简要信息（同步版本）"""
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "json"
    }
    if API_KEY:
        params["api_key"] = API_KEY

    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/esummary.fcgi", params=params)
        response.raise_for_status()
        return response.json()


def get_article_details(pmids: List[str]) -> str:
    """根据 PMID 获取文献详细信息（XML格式，同步版本）"""
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml"
    }
    if API_KEY:
        params["api_key"] = API_KEY

    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/efetch.fcgi", params=params)
        response.raise_for_status()
        return response.text


def get_related_articles(pmids: List[str], cmd: str = "neighbor") -> Dict:
    """通过 ELink 获取相关文章"""
    params = {
        "dbfrom": "pubmed",
        "db": "pubmed",
        "id": ",".join(pmids),
        "cmd": cmd,
        "retmode": "json",
    }
    if API_KEY:
        params["api_key"] = API_KEY

    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/elink.fcgi", params=params)
        response.raise_for_status()
        return response.json()


def search_with_history(query: str) -> Dict:
    """使用 History Server 保存大结果集游标"""
    params = {
        "db": "pubmed",
        "term": query,
        "usehistory": "y",
        "retmax": 0,
        "retmode": "json",
    }
    if API_KEY:
        params["api_key"] = API_KEY

    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/esearch.fcgi", params=params)
        response.raise_for_status()
        return response.json()


# ============ XML 解析 ============
def parse_article_xml(xml_text: str) -> List[Dict]:
    """解析文献 XML，提取关键信息"""
    articles = []
    root = ET.fromstring(xml_text)

    for article in root.findall(".//PubmedArticle"):
        pmid_elem = article.find(".//PMID")
        pmid = pmid_elem.text if pmid_elem is not None else ""

        title_elem = article.find(".//ArticleTitle")
        title = title_elem.text if title_elem is not None else ""

        abstract_elem = article.find(".//AbstractText")
        abstract = abstract_elem.text if abstract_elem is not None else ""

        authors = []
        for author in article.findall(".//Author"):
            last_name = author.find("LastName")
            fore_name = author.find("ForeName")
            if last_name is not None and fore_name is not None:
                authors.append(f"{last_name.text} {fore_name.text}")
            elif last_name is not None:
                authors.append(last_name.text)

        journal_elem = article.find(".//Journal/Title")
        journal = journal_elem.text if journal_elem is not None else ""

        year_elem = article.find(".//PubDate/Year")
        year = year_elem.text if year_elem is not None else ""

        articles.append({
            "pmid": pmid,
            "title": title,
            "abstract": abstract[:200] + "..." if len(abstract) > 200 else abstract,
            "authors": authors[:5],
            "journal": journal,
            "year": year
        })

    return articles


# ============ 酶设计场景示例 ============
async def search_enzyme_literature(
    enzyme_family: str,
    substrate: Optional[str] = None,
    limit: int = 20
) -> Dict:
    """搜索酶工程相关文献"""
    query = f"{enzyme_family} enzyme engineering"
    if substrate:
        query += f" {substrate} substrate"

    return await search_pubmed_async(query, retmax=limit)


async def search_by_ec_number(ec_number: str, limit: int = 20) -> Dict:
    """按 EC 号检索酶文献"""
    query = f'"EC {ec_number}"[All Fields] OR "EC{ec_number}"[All Fields]'
    return await search_pubmed_async(query, retmax=limit)


async def search_protein_engineering_methods(method: str, limit: int = 20) -> Dict:
    """检索蛋白质工程方法相关文献"""
    query_map = {
        "directed_evolution": '"directed evolution"[MeSH] AND enzyme',
        "rational_design": '"rational design"[Title/Abstract] AND "site-directed mutagenesis"[Title/Abstract]',
        "computational": '"computational protein design"[Title/Abstract] AND ("Rosetta"[Title] OR "AlphaFold"[Title])'
    }
    query = query_map.get(method, method)
    return await search_pubmed_async(query, retmax=limit)


# ============ Mock 测试 (使用 pytest-httpx) ============
def test_search_mock(httpx_mock: HTTPXMock):
    """Mock 测试：搜索文献（无需 API Key）"""
    httpx_mock.add_response(
        url=re.compile(f"{BASE_URL}/esearch\\.fcgi.*"),
        json={
            "header": {"type": "esearch", "version": "0.3"},
            "esearchresult": {
                "count": "100",
                "retmax": "10",
                "retstart": "0",
                "idlist": ["12345678", "12345679", "12345680"]
            }
        },
        status_code=200
    )

    result = search_pubmed("test query")
    assert "esearchresult" in result
    assert "idlist" in result["esearchresult"]
    assert len(result["esearchresult"]["idlist"]) == 3


def test_summary_mock(httpx_mock: HTTPXMock):
    """Mock 测试：获取文献摘要"""
    httpx_mock.add_response(
        url=re.compile(f"{BASE_URL}/esummary\\.fcgi.*"),
        json={
            "result": {
                "uids": ["12345678"],
                "12345678": {
                    "uid": "12345678",
                    "title": "Test Paper Title",
                    "authors": [{"name": "Smith J"}],
                    "pubdate": "2024 Jan 1"
                }
            }
        },
        status_code=200
    )

    result = get_article_summaries(["12345678"])
    assert "result" in result
    assert "12345678" in result["result"]


def test_fetch_mock(httpx_mock: HTTPXMock):
    """Mock 测试：获取文献详情（XML）"""
    mock_xml = """<?xml version="1.0"?>
    <PubmedArticleSet>
        <PubmedArticle>
            <MedlineCitation>
                <PMID>12345678</PMID>
                <Article>
                    <ArticleTitle>Test Article Title</ArticleTitle>
                    <Abstract>
                        <AbstractText>Test abstract content.</AbstractText>
                    </Abstract>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
    </PubmedArticleSet>"""

    httpx_mock.add_response(
        url=re.compile(f"{BASE_URL}/efetch\\.fcgi.*"),
        text=mock_xml,
        status_code=200
    )

    result = get_article_details(["12345678"])
    assert "Test Article Title" in result

    articles = parse_article_xml(result)
    assert len(articles) == 1
    assert articles[0]["pmid"] == "12345678"


def test_elink_mock(httpx_mock: HTTPXMock):
    """Mock 测试：ELink 相关文章"""
    httpx_mock.add_response(
        url=re.compile(f"{BASE_URL}/elink\\.fcgi.*"),
        json={
            "linksets": [
                {
                    "ids": ["12345678"],
                    "linksetdbs": [{"dbto": "pubmed", "links": ["22334455", "22334456"]}],
                }
            ]
        },
        status_code=200,
    )

    result = get_related_articles(["12345678"])
    assert result["linksets"][0]["linksetdbs"][0]["dbto"] == "pubmed"


def test_history_mock(httpx_mock: HTTPXMock):
    """Mock 测试：History Server"""
    httpx_mock.add_response(
        url=re.compile(f"{BASE_URL}/esearch\\.fcgi.*"),
        json={
            "esearchresult": {
                "count": "5234",
                "retmax": "0",
                "retstart": "0",
                "querykey": "1",
                "webenv": "NCID_1_123456_130.14.22.215_9001_1700000000_1234567890",
            }
        },
        status_code=200,
    )

    result = search_with_history("lipase engineering")
    assert result["esearchresult"]["querykey"] == "1"
    assert "webenv" in result["esearchresult"]


def test_enzyme_search_mock(httpx_mock: HTTPXMock):
    """Mock 测试：酶文献搜索"""
    httpx_mock.add_response(
        url=re.compile(f"{BASE_URL}/esearch\\.fcgi.*"),
        json={
            "esearchresult": {
                "count": "50",
                "idlist": ["11111111", "22222222"]
            }
        },
        status_code=200
    )

    result = search_pubmed("lipase enzyme engineering")
    assert result["esearchresult"]["count"] == "50"


# ============ 主函数 ============
async def main():
    """运行示例"""
    print("=" * 60)
    print("PubMed E-utilities API 示例")
    print("=" * 60)
    print(f"API Key 配置: {'已设置' if API_KEY else '未设置'}")
    print(f"速率限制延迟: {RATE_LIMIT_DELAY} 秒")
    print()

    # 示例 1: 搜索文献
    print("示例 1: 搜索酶工程文献")
    print("-" * 40)
    try:
        result = await search_enzyme_literature("lipase", "p-nitrophenyl", limit=5)
        esearch = result.get("esearchresult", {})
        print(f"总结果数: {esearch.get('count', 'N/A')}")
        print(f"PMID 列表: {esearch.get('idlist', [])}")
    except Exception as e:
        print(f"请求失败: {e}")

    time.sleep(RATE_LIMIT_DELAY)

    # 示例 2: 按 EC 号搜索
    print("\n示例 2: 按 EC 号搜索酶文献")
    print("-" * 40)
    try:
        result = await search_by_ec_number("3.1.1.3", limit=5)
        esearch = result.get("esearchresult", {})
        print(f"EC 3.1.1.3 相关文献数: {esearch.get('count', 'N/A')}")
    except Exception as e:
        print(f"请求失败: {e}")

    print()
    print("=" * 60)
    print("示例运行完成")
    print("运行 mock 测试: pytest examples.py -v")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
