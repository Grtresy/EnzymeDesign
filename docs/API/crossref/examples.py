#!/usr/bin/env python3
"""
CrossRef API 请求示例

本脚本演示如何使用 CrossRef API 获取 DOI 元数据和引用信息。
包括：搜索论文、获取 DOI 详情、批量查询、期刊查询。

运行方式:
    # 真实请求（无需 API Key）
    python examples.py

    # 仅运行 mock 测试
    pytest examples.py -v
"""

import os
import re
import asyncio
from typing import Dict, List, Optional

import httpx
import pytest
from pytest_httpx import HTTPXMock


# ============ 配置 ============
BASE_URL = "https://api.crossref.org"
EMAIL = os.environ.get("CROSSREF_EMAIL", "")
RATE_LIMIT_DELAY = 0.05


def _get_headers() -> Dict[str, str]:
    headers = {}
    if EMAIL:
        headers["User-Agent"] = f"OpenZyme/1.0 (mailto:{EMAIL})"
    return headers


# ============ 异步请求 ============
async def search_works_async(query: str, rows: int = 20) -> Dict:
    """搜索论文（异步版本）"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/works", params={"query": query, "rows": rows}, headers=_get_headers())
        response.raise_for_status()
        return response.json()


async def get_work_by_doi_async(doi: str) -> Dict:
    """根据 DOI 获取论文详情（异步版本）"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/works/{doi}", headers=_get_headers())
        response.raise_for_status()
        return response.json()


# ============ 同步请求 ============
def search_works(query: str, rows: int = 20) -> Dict:
    """搜索论文（同步版本）"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/works", params={"query": query, "rows": rows}, headers=_get_headers())
        response.raise_for_status()
        return response.json()


def get_work_by_doi(doi: str) -> Dict:
    """根据 DOI 获取论文详情（同步版本）"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/works/{doi}", headers=_get_headers())
        response.raise_for_status()
        return response.json()


def search_works_cursor(filter_expr: str, rows: int = 1000, cursor: str = "*") -> Dict:
    """使用 cursor 深分页拉取记录"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            f"{BASE_URL}/works",
            params={"filter": filter_expr, "rows": rows, "cursor": cursor},
            headers=_get_headers(),
        )
        response.raise_for_status()
        return response.json()


def get_journal_works(issn: str, rows: int = 20) -> Dict:
    """获取某期刊下的文献"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/journals/{issn}/works", params={"rows": rows}, headers=_get_headers())
        response.raise_for_status()
        return response.json()


def list_types() -> Dict:
    """列出 Crossref 文献类型"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/types", headers=_get_headers())
        response.raise_for_status()
        return response.json()


# ============ Mock 测试 (使用 pytest-httpx) ============
def test_search_mock(httpx_mock: HTTPXMock):
    """Mock 测试：搜索论文"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/works.*"),
        json={
            "status": "ok",
            "message": {
                "total-results": 1000,
                "items": [{"DOI": "10.1234/test1", "title": ["Test Paper 1"]}, {"DOI": "10.1234/test2", "title": ["Test Paper 2"]}]
            }
        },
        status_code=200
    )

    result = search_works("enzyme engineering")
    assert result["message"]["total-results"] == 1000


def test_get_by_doi_mock(httpx_mock: HTTPXMock):
    """Mock 测试：根据 DOI 获取论文"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/works/10\.1234/test.*"),
        json={
            "status": "ok",
            "message": {"DOI": "10.1234/test", "title": ["Test Article Title"], "author": [{"given": "John", "family": "Smith"}]}
        },
        status_code=200
    )

    result = get_work_by_doi("10.1234/test")
    assert result["message"]["DOI"] == "10.1234/test"


def test_cursor_mock(httpx_mock: HTTPXMock):
    """Mock 测试：cursor 深分页"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/works.*"),
        json={
            "status": "ok",
            "message": {
                "next-cursor": "AoJ0ZXN0LWN1cnNvcg==",
                "items": [{"DOI": "10.1234/test1", "title": ["Paper 1"]}],
            },
        },
        status_code=200
    )
    result = search_works_cursor("from-pub-date:2024-01-01", rows=1000)
    assert result["message"]["next-cursor"]
    assert len(result["message"]["items"]) == 1


def test_journals_mock(httpx_mock: HTTPXMock):
    """Mock 测试：搜索期刊"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/journals.*"),
        json={"status": "ok", "message": {"total-results": 10, "items": [{"ISSN": ["1234-5678"], "title": "Nature"}]}},
        status_code=200
    )

    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/journals", params={"query": "Nature"}, headers=_get_headers())
        result = response.json()

    assert result["message"]["items"][0]["title"] == "Nature"


def test_journal_works_mock(httpx_mock: HTTPXMock):
    """Mock 测试：获取期刊文献"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/journals/1476-4687/works.*"),
        json={"status": "ok", "message": {"items": [{"DOI": "10.1234/test-journal", "title": ["Journal Paper"]}]}},
        status_code=200,
    )

    result = get_journal_works("1476-4687")
    assert result["message"]["items"][0]["DOI"] == "10.1234/test-journal"


def test_types_mock(httpx_mock: HTTPXMock):
    """Mock 测试：文献类型列表"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/types.*"),
        json={"status": "ok", "message": {"items": [{"id": "journal-article", "label": "Journal Article"}]}},
        status_code=200,
    )

    result = list_types()
    assert result["message"]["items"][0]["id"] == "journal-article"


def test_citation_format_mock(httpx_mock: HTTPXMock):
    """Mock 测试：引用格式生成"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/works/10\.1234/test.*"),
        json={
            "status": "ok",
            "message": {
                "DOI": "10.1234/test",
                "title": ["Test Article"],
                "author": [{"given": "John", "family": "Smith"}, {"given": "Li", "family": "Zhang"}],
                "published": {"date-parts": [[2024]]},
                "container-title": ["Test Journal"]
            }
        },
        status_code=200
    )

    async def get_citation(doi: str) -> int:
        work = await get_work_by_doi_async(doi)
        return work["message"]["published"]["date-parts"][0][0]

    result = asyncio.run(get_citation("10.1234/test"))
    assert result == 2024


# ============ 主函数 ============
async def main():
    """运行示例"""
    print("=" * 60)
    print("CrossRef API 示例")
    print("=" * 60)

    print("示例 1: 搜索酶工程论文")
    print("-" * 40)
    try:
        result = await search_works_async("enzyme engineering", rows=5)
        print(f"总结果数: {result.get('message', {}).get('total-results', 'N/A')}")
    except Exception as e:
        print(f"请求失败: {e}")

    print()
    print("=" * 60)
    print("示例运行完成")
    print("运行 mock 测试: pytest examples.py -v")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
