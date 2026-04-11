#!/usr/bin/env python3
"""
Semantic Scholar API 请求示例

本脚本演示如何使用 Semantic Scholar API 进行学术文献检索。
包括：论文搜索、获取论文详情、作者查询、批量操作。

运行方式:
    # 真实请求（可选设置 API Key）
    python examples.py

    # 使用 API Key 提高速率限制
    SEMANTIC_SCHOLAR_API_KEY=your-key python examples.py

    # 仅运行 mock 测试
    pytest examples.py -v
"""

import os
import re
import time
import asyncio
from typing import List, Dict, Optional

import httpx
import pytest
from pytest_httpx import HTTPXMock


# ============ 配置 ============
API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
BASE_URL = "https://api.semanticscholar.org/graph/v1"

# 速率限制延迟（秒）
RATE_LIMIT_DELAY = 0.2


def _get_headers() -> Dict[str, str]:
    """获取请求头（包含 API Key）"""
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["x-api-key"] = API_KEY
    return headers


# ============ 异步请求 ============
async def search_papers_async(
    query: str,
    limit: int = 10,
    offset: int = 0,
    fields: Optional[str] = None,
    year: Optional[str] = None,
    venue: Optional[str] = None,
    open_access_pdf: bool = False
) -> Dict:
    """搜索论文（异步版本）"""
    if fields is None:
        fields = "paperId,title,year,authors,citationCount,abstract,tldr"

    params = {
        "query": query,
        "limit": limit,
        "offset": offset,
        "fields": fields
    }
    if year:
        params["year"] = year
    if venue:
        params["venue"] = venue
    if open_access_pdf:
        params["openAccessPdf"] = "any"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{BASE_URL}/paper/search",
            params=params,
            headers=_get_headers()
        )
        response.raise_for_status()
        return response.json()


async def get_paper_async(paper_id: str, fields: Optional[str] = None) -> Dict:
    """获取单篇论文详情（异步版本）"""
    if fields is None:
        fields = "paperId,title,abstract,year,authors,citationCount,referenceCount,tldr,openAccessPdf"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{BASE_URL}/paper/{paper_id}",
            params={"fields": fields},
            headers=_get_headers()
        )
        response.raise_for_status()
        return response.json()


async def get_author_async(author_id: str, fields: Optional[str] = None) -> Dict:
    """获取作者详情（异步版本）"""
    if fields is None:
        fields = "name,paperCount,citationCount,papers.title,papers.year,papers.citationCount"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{BASE_URL}/author/{author_id}",
            params={"fields": fields},
            headers=_get_headers()
        )
        response.raise_for_status()
        return response.json()


# ============ 同步请求 ============
def search_papers(query: str, limit: int = 10, fields: Optional[str] = None) -> Dict:
    """搜索论文（同步版本）"""
    if fields is None:
        fields = "paperId,title,year,authors,citationCount,abstract,tldr"

    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            f"{BASE_URL}/paper/search",
            params={"query": query, "limit": limit, "fields": fields},
            headers=_get_headers()
        )
        response.raise_for_status()
        return response.json()


def get_paper(paper_id: str, fields: Optional[str] = None) -> Dict:
    """获取单篇论文详情（同步版本）"""
    if fields is None:
        fields = "paperId,title,abstract,year,authors,citationCount,tldr"

    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            f"{BASE_URL}/paper/{paper_id}",
            params={"fields": fields},
            headers=_get_headers()
        )
        response.raise_for_status()
        return response.json()


def get_author(author_id: str, fields: Optional[str] = None) -> Dict:
    """获取作者详情（同步版本）"""
    if fields is None:
        fields = "name,paperCount,citationCount,papers.title,papers.year,papers.citationCount"

    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            f"{BASE_URL}/author/{author_id}",
            params={"fields": fields},
            headers=_get_headers()
        )
        response.raise_for_status()
        return response.json()


# ============ Mock 测试 (使用 pytest-httpx) ============
def test_search_mock(httpx_mock: HTTPXMock):
    """Mock 测试：搜索论文"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/paper/search.*"),
        json={
            "total": 100,
            "offset": 0,
            "data": [
                {"paperId": "abc123", "title": "Test Paper 1", "year": 2024, "citationCount": 50},
                {"paperId": "def456", "title": "Test Paper 2", "year": 2023, "citationCount": 30}
            ]
        },
        status_code=200
    )

    result = search_papers("test query")
    assert "data" in result
    assert len(result["data"]) == 2


def test_get_paper_mock(httpx_mock: HTTPXMock):
    """Mock 测试：获取单篇论文"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/paper/abc123.*"),
        json={
            "paperId": "abc123",
            "title": "Test Paper Title",
            "abstract": "This is a test abstract.",
            "year": 2024,
            "citationCount": 100,
            "tldr": {"model": "tldr@v2.0.0", "text": "This paper presents a novel approach."}
        },
        status_code=200
    )

    result = get_paper("abc123")
    assert result["paperId"] == "abc123"
    assert result["tldr"]["text"] == "This paper presents a novel approach."


def test_batch_mock(httpx_mock: HTTPXMock):
    """Mock 测试：批量获取论文"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/paper/batch.*"),
        json=[{"paperId": "abc123", "title": "Paper 1"}, {"paperId": "def456", "title": "Paper 2"}],
        status_code=200
    )

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{BASE_URL}/paper/batch",
            params={"fields": "paperId,title"},
            json={"ids": ["abc123", "def456"]},
            headers=_get_headers()
        )
        result = response.json()

    assert len(result) == 2


def test_author_search_mock(httpx_mock: HTTPXMock):
    """Mock 测试：搜索作者"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/author/search.*"),
        json={"data": [{"authorId": "12345", "name": "Test Author", "citationCount": 1000}]},
        status_code=200
    )

    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            f"{BASE_URL}/author/search",
            params={"query": "Test Author"},
            headers=_get_headers()
        )
        result = response.json()

    assert "data" in result
    assert result["data"][0]["name"] == "Test Author"


def test_author_detail_mock(httpx_mock: HTTPXMock):
    """Mock 测试：作者详情及嵌套论文"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/author/12345.*"),
        json={
            "authorId": "12345",
            "name": "Test Author",
            "paperCount": 2,
            "papers": [
                {"title": "Paper 1", "year": 2024, "citationCount": 11},
                {"title": "Paper 2", "year": 2023, "citationCount": 8},
            ],
        },
        status_code=200,
    )

    result = get_author("12345")
    assert result["paperCount"] == 2
    assert result["papers"][0]["title"] == "Paper 1"


def test_enzyme_search_mock(httpx_mock: HTTPXMock):
    """Mock 测试：酶文献搜索"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/paper/search.*"),
        json={
            "total": 50,
            "data": [{"paperId": "enz001", "title": "Engineering of thermostable lipase", "year": 2024, "citationCount": 25}]
        },
        status_code=200
    )

    result = search_papers("lipase enzyme engineering")
    assert result["total"] == 50


# ============ 主函数 ============
async def main():
    """运行示例"""
    print("=" * 60)
    print("Semantic Scholar API 示例")
    print("=" * 60)
    print(f"API Key 配置: {'已设置' if API_KEY else '未设置'}")
    print()

    print("示例 1: 搜索酶工程论文")
    print("-" * 40)
    try:
        result = await search_papers_async("enzyme engineering", limit=5)
        print(f"总结果数: {result.get('total', 'N/A')}")
    except Exception as e:
        print(f"请求失败: {e}")

    print()
    print("=" * 60)
    print("示例运行完成")
    print("运行 mock 测试: pytest examples.py -v")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
