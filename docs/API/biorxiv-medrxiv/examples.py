#!/usr/bin/env python3
"""
bioRxiv/medRxiv API 请求示例

本脚本演示如何使用 bioRxiv/medRxiv API 获取预印本信息。
包括：获取论文详情、批量获取、检查发表状态。

运行方式:
    # 真实请求（无需 API Key）
    python examples.py

    # 仅运行 mock 测试
    pytest examples.py -v
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import httpx
import pytest
from pytest_httpx import HTTPXMock


# ============ 配置 ============
BIORXIV_BASE_URL = "https://api.biorxiv.org"
MEDRXIV_BASE_URL = "https://api.medrxiv.org"

# 速率限制延迟（秒）
RATE_LIMIT_DELAY = 0.5


# ============ 异步请求 ============
async def get_paper_details_async(
    doi: str,
    server: str = "biorxiv",
    version: Optional[str] = None
) -> Dict:
    """
    获取预印本详情（异步版本）

    参数:
        doi: DOI（不含 10.1101/ 前缀）
        server: 服务器名（biorxiv 或 medrxiv）
        version: 版本号（不指定返回所有版本）

    返回:
        预印本详情
    """
    base_url = BIORXIV_BASE_URL if server == "biorxiv" else MEDRXIV_BASE_URL
    url = f"{base_url}/details/{server}/{doi}/na/json"
    if version:
        url = f"{base_url}/details/{server}/{doi}/{version}/json"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def get_papers_by_date_async(
    start_date: str,
    end_date: str,
    server: str = "biorxiv",
    cursor: int = 0
) -> Dict:
    """
    按日期范围获取预印本列表（异步版本）

    参数:
        start_date: 起始日期（YYYY-MM-DD）
        end_date: 结束日期（YYYY-MM-DD）
        server: 服务器名（biorxiv 或 medrxiv）
        cursor: 分页游标

    返回:
        预印本列表
    """
    base_url = BIORXIV_BASE_URL if server == "biorxiv" else MEDRXIV_BASE_URL
    url = f"{base_url}/details/{server}/{start_date}/{end_date}/{cursor}/json"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def get_publication_status_async(
    doi: str,
    server: str = "biorxiv"
) -> Dict:
    """
    检查预印本是否已正式发表（异步版本）

    参数:
        doi: DOI（不含 10.1101/ 前缀）
        server: 服务器名

    返回:
        发表状态信息
    """
    base_url = BIORXIV_BASE_URL if server == "biorxiv" else MEDRXIV_BASE_URL
    url = f"{base_url}/pub/{server}/{doi}/na/json"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


# ============ 同步请求 ============
def get_paper_details(
    doi: str,
    server: str = "biorxiv",
    version: Optional[str] = None
) -> Dict:
    """获取预印本详情（同步版本）"""
    base_url = BIORXIV_BASE_URL if server == "biorxiv" else MEDRXIV_BASE_URL
    url = f"{base_url}/details/{server}/{doi}/na/json"
    if version:
        url = f"{base_url}/details/{server}/{doi}/{version}/json"

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def get_papers_by_date(
    start_date: str,
    end_date: str,
    server: str = "biorxiv"
) -> Dict:
    """按日期范围获取预印本列表（同步版本）"""
    base_url = BIORXIV_BASE_URL if server == "biorxiv" else MEDRXIV_BASE_URL
    url = f"{base_url}/details/{server}/{start_date}/{end_date}/0/json"

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def get_publication_status(doi: str, server: str = "biorxiv") -> Dict:
    """检查预印本是否已正式发表（同步版本）"""
    base_url = BIORXIV_BASE_URL if server == "biorxiv" else MEDRXIV_BASE_URL
    url = f"{base_url}/pub/{server}/{doi}/na/json"

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def get_publications_by_date(
    start_date: str,
    end_date: str,
    server: str = "biorxiv",
    cursor: int = 0,
) -> Dict:
    """按日期范围获取正式发表映射"""
    base_url = BIORXIV_BASE_URL if server == "biorxiv" else MEDRXIV_BASE_URL
    url = f"{base_url}/pubs/{server}/{start_date}/{end_date}/{cursor}/json"

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


# ============ 酶设计场景示例 ============
async def search_recent_enzyme_preprints(
    days: int = 30,
    category: str = "Biochemistry"
) -> List[Dict]:
    """搜索最近的酶相关预印本"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    result = await get_papers_by_date_async(
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d"),
        server="biorxiv"
    )

    # 过滤包含 enzyme 或 protein engineering 的论文
    enzyme_papers = []
    keywords = ["enzyme", "protein engineering", "directed evolution", "biocatalyst"]

    for paper in result.get("collection", []):
        title = paper.get("title", "").lower()
        abstract = paper.get("abstract", "").lower()
        text = f"{title} {abstract}"

        if any(kw in text for kw in keywords):
            enzyme_papers.append(paper)

    return enzyme_papers


async def track_paper_to_publication(doi: str) -> Optional[Dict]:
    """追踪预印本到正式发表的历程"""
    pub_status = await get_publication_status_async(doi, server="biorxiv")

    if pub_status.get("collection"):
        return pub_status["collection"][0]
    return None


async def get_paper_all_versions(doi: str) -> List[Dict]:
    """获取论文的所有版本"""
    details = await get_paper_details_async(doi, server="biorxiv")
    return details.get("collection", [])


# ============ Mock 测试 (使用 pytest-httpx) ============
def test_paper_details_mock(httpx_mock: HTTPXMock):
    """Mock 测试：获取预印本详情"""
    httpx_mock.add_response(
        url=f"{BIORXIV_BASE_URL}/details/biorxiv/2024.01.15.123456/na/json",
        json={
            "status": "ok",
            "messages": [],
            "collection": [
                {
                    "doi": "10.1101/2024.01.15.123456",
                    "title": "Engineering of thermostable enzymes",
                    "authors": "Smith J; Zhang L",
                    "date": "2024-01-15",
                    "version": "1",
                    "category": "Biochemistry",
                    "abstract": "This study presents..."
                }
            ]
        },
        status_code=200
    )

    result = get_paper_details("2024.01.15.123456")
    assert result["status"] == "ok"
    assert len(result["collection"]) == 1
    assert result["collection"][0]["category"] == "Biochemistry"


def test_papers_by_date_mock(httpx_mock: HTTPXMock):
    """Mock 测试：按日期获取预印本"""
    httpx_mock.add_response(
        url=f"{BIORXIV_BASE_URL}/details/biorxiv/2024-01-01/2024-01-31/0/json",
        json={
            "status": "ok",
            "collection": [
                {
                    "doi": "10.1101/2024.01.15.123456",
                    "title": "Test Paper 1",
                    "category": "Biochemistry"
                },
                {
                    "doi": "10.1101/2024.01.16.123457",
                    "title": "Test Paper 2",
                    "category": "Molecular Biology"
                }
            ]
        },
        status_code=200
    )

    result = get_papers_by_date("2024-01-01", "2024-01-31")
    assert result["status"] == "ok"
    assert len(result["collection"]) == 2


def test_publication_status_mock(httpx_mock: HTTPXMock):
    """Mock 测试：检查发表状态"""
    httpx_mock.add_response(
        url=f"{BIORXIV_BASE_URL}/pub/biorxiv/2024.01.15.123456/na/json",
        json={
            "status": "ok",
            "collection": [
                {
                    "preprint_doi": "10.1101/2024.01.15.123456",
                    "published_doi": "10.1038/s41586-024-12345",
                    "preprint_date": "2024-01-15",
                    "published_date": "2024-03-15"
                }
            ]
        },
        status_code=200
    )

    result = get_publication_status("2024.01.15.123456")
    assert result["collection"][0]["published_doi"] == "10.1038/s41586-024-12345"


def test_medrxiv_mock(httpx_mock: HTTPXMock):
    """Mock 测试：medRxiv API"""
    httpx_mock.add_response(
        url=f"{MEDRXIV_BASE_URL}/details/medrxiv/2024.01.15.123456/na/json",
        json={
            "status": "ok",
            "collection": [
                {
                    "doi": "10.1101/2024.01.15.123456",
                    "title": "Clinical Study on Enzyme Therapy",
                    "category": "Clinical Research"
                }
            ]
        },
        status_code=200
    )

    result = get_paper_details("2024.01.15.123456", server="medrxiv")
    assert result["collection"][0]["category"] == "Clinical Research"


def test_enzyme_search_mock(httpx_mock: HTTPXMock):
    """Mock 测试：酶相关预印本搜索"""
    httpx_mock.add_response(
        url=f"{BIORXIV_BASE_URL}/details/biorxiv/2024-01-01/2024-01-31/0/json",
        json={
            "status": "ok",
            "collection": [
                {
                    "doi": "10.1101/2024.01.15.123456",
                    "title": "Engineering of thermostable lipase enzymes",
                    "category": "Biochemistry",
                    "abstract": "We present a novel enzyme engineering approach..."
                },
                {
                    "doi": "10.1101/2024.01.16.123457",
                    "title": "Unrelated Paper",
                    "category": "Ecology"
                }
            ]
        },
        status_code=200
    )

    result = get_papers_by_date("2024-01-01", "2024-01-31")
    enzyme_papers = [
        p for p in result["collection"]
        if "enzyme" in p["title"].lower()
    ]
    assert len(enzyme_papers) == 1


def test_publications_by_date_mock(httpx_mock: HTTPXMock):
    """Mock 测试：区间发表映射"""
    httpx_mock.add_response(
        url=f"{BIORXIV_BASE_URL}/pubs/biorxiv/2024-01-01/2024-01-31/0/json",
        json={
            "status": "ok",
            "collection": [
                {
                    "preprint_doi": "10.1101/2024.01.15.123456",
                    "published_doi": "10.1038/s41586-024-12345",
                }
            ],
        },
        status_code=200,
    )

    result = get_publications_by_date("2024-01-01", "2024-01-31")
    assert result["collection"][0]["published_doi"] == "10.1038/s41586-024-12345"


# ============ 主函数 ============
async def main():
    """运行示例"""
    print("=" * 60)
    print("bioRxiv/medRxiv API 示例")
    print("=" * 60)
    print("注意: 无需 API Key")
    print()

    # 示例 1: 获取预印本详情
    print("示例 1: 获取预印本详情")
    print("-" * 40)
    try:
        # 使用一个真实的 bioRxiv DOI 作为示例
        result = await get_paper_details_async("2023.11.01.565211", server="biorxiv")
        if result.get("collection"):
            paper = result["collection"][0]
            print(f"标题: {paper.get('title', 'N/A')[:60]}...")
            print(f"作者: {paper.get('authors', 'N/A')[:50]}...")
            print(f"日期: {paper.get('date', 'N/A')}")
            print(f"分类: {paper.get('category', 'N/A')}")
        else:
            print("未找到预印本")
    except Exception as e:
        print(f"请求失败: {e}")

    await asyncio.sleep(RATE_LIMIT_DELAY)

    # 示例 2: 按日期获取预印本
    print("\n示例 2: 获取最近 7 天的预印本")
    print("-" * 40)
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)

        result = await get_papers_by_date_async(
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            server="biorxiv"
        )
        papers = result.get("collection", [])
        print(f"找到 {len(papers)} 篇预印本")
        if papers:
            print(f"最新: {papers[0].get('title', 'N/A')[:50]}...")
    except Exception as e:
        print(f"请求失败: {e}")

    await asyncio.sleep(RATE_LIMIT_DELAY)

    # 示例 3: 检查发表状态
    print("\n示例 3: 检查预印本是否已正式发表")
    print("-" * 40)
    try:
        # 检查一个较早的预印本
        result = await get_publication_status_async("2020.01.01.123456", server="biorxiv")
        if result.get("collection"):
            pub = result["collection"][0]
            print(f"预印本 DOI: {pub.get('preprint_doi')}")
            print(f"正式发表 DOI: {pub.get('published_doi', '尚未发表')}")
        else:
            print("尚未正式发表")
    except Exception as e:
        print(f"请求失败: {e}")

    print()
    print("=" * 60)
    print("示例运行完成")
    print("运行 mock 测试: pytest examples.py -v")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
