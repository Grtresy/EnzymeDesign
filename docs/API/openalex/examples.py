#!/usr/bin/env python3
"""
OpenAlex API 请求示例

本脚本演示如何使用 OpenAlex API 进行学术图谱检索。
包括：搜索论文、作者查询、机构查询、主题和关键词查询。

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
BASE_URL = "https://api.openalex.org"
EMAIL = os.environ.get("OPENALEX_EMAIL", "")
RATE_LIMIT_DELAY = 0.1


def _get_params(params: Dict) -> Dict:
    if EMAIL:
        params["mailto"] = EMAIL
    return params


# ============ 异步请求 ============
async def search_works_async(query: str, per_page: int = 25) -> Dict:
    """搜索论文（异步版本）"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/works", params=_get_params({"search": query, "per_page": per_page}))
        response.raise_for_status()
        return response.json()


async def get_work_async(work_id: str) -> Dict:
    """获取单篇论文（异步版本）"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/works/{work_id}", params=_get_params({}))
        response.raise_for_status()
        return response.json()


async def search_institutions_async(query: str, per_page: int = 25) -> Dict:
    """搜索机构（异步版本）"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/institutions", params=_get_params({"search": query, "per_page": per_page}))
        response.raise_for_status()
        return response.json()


# ============ 同步请求 ============
def search_works(query: str, per_page: int = 25) -> Dict:
    """搜索论文（同步版本）"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/works", params=_get_params({"search": query, "per_page": per_page}))
        response.raise_for_status()
        return response.json()


def get_work(work_id: str) -> Dict:
    """获取单篇论文（同步版本）"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/works/{work_id}", params=_get_params({}))
        response.raise_for_status()
        return response.json()


def search_institutions(query: str, per_page: int = 25) -> Dict:
    """搜索机构（同步版本）"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/institutions", params=_get_params({"search": query, "per_page": per_page}))
        response.raise_for_status()
        return response.json()


def search_topics(query: str, per_page: int = 25) -> Dict:
    """搜索主题（同步版本）"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/topics", params=_get_params({"search": query, "per_page": per_page}))
        response.raise_for_status()
        return response.json()


def search_keywords(query: str, per_page: int = 25) -> Dict:
    """搜索关键词（同步版本）"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/keywords", params=_get_params({"search": query, "per_page": per_page}))
        response.raise_for_status()
        return response.json()


# ============ Mock 测试 (使用 pytest-httpx) ============
def test_search_works_mock(httpx_mock: HTTPXMock):
    """Mock 测试：搜索论文"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/works.*"),
        json={
            "meta": {"count": 100, "page": 1, "per_page": 25},
            "results": [{"id": "W123456", "title": "Test Paper 1", "cited_by_count": 50}]
        },
        status_code=200
    )

    result = search_works("enzyme engineering")
    assert result["meta"]["count"] == 100


def test_get_work_mock(httpx_mock: HTTPXMock):
    """Mock 测试：获取单篇论文"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/works/W123456.*"),
        json={"id": "W123456", "title": "Test Paper Title", "concepts": [{"display_name": "Enzyme", "score": 0.8}]},
        status_code=200
    )

    result = get_work("W123456")
    assert result["title"] == "Test Paper Title"


def test_search_authors_mock(httpx_mock: HTTPXMock):
    """Mock 测试：搜索作者"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/authors.*"),
        json={"results": [{"id": "A123456", "display_name": "Test Author", "works_count": 100}]},
        status_code=200
    )

    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/authors", params=_get_params({"search": "Test Author"}))
        result = response.json()

    assert result["results"][0]["display_name"] == "Test Author"


def test_search_institutions_mock(httpx_mock: HTTPXMock):
    """Mock 测试：搜索机构"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/institutions.*"),
        json={"results": [{"id": "I123456", "display_name": "MIT", "country_code": "US"}]},
        status_code=200
    )

    result = search_institutions("MIT")
    assert result["results"][0]["display_name"] == "MIT"


def test_search_topics_mock(httpx_mock: HTTPXMock):
    """Mock 测试：搜索主题"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/topics.*"),
        json={"results": [{"id": "T123456", "display_name": "Enzyme engineering"}]},
        status_code=200
    )

    result = search_topics("enzyme")
    assert result["results"][0]["display_name"] == "Enzyme engineering"


def test_search_keywords_mock(httpx_mock: HTTPXMock):
    """Mock 测试：搜索关键词"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/keywords.*"),
        json={"results": [{"id": "K123456", "display_name": "lipase"}]},
        status_code=200
    )

    result = search_keywords("lipase")
    assert result["results"][0]["display_name"] == "lipase"


def test_filter_mock(httpx_mock: HTTPXMock):
    """Mock 测试：过滤条件"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/works.*"),
        json={"results": [{"id": "W123", "title": "Open Access Paper", "is_oa": True}]},
        status_code=200
    )

    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/works", params=_get_params({"filter": "is_oa:true", "per_page": 10}))
        result = response.json()

    assert len(result["results"]) == 1


# ============ 主函数 ============
async def main():
    """运行示例"""
    print("=" * 60)
    print("OpenAlex API 示例")
    print("=" * 60)

    print("示例 1: 搜索酶工程论文")
    print("-" * 40)
    try:
        result = await search_works_async("enzyme engineering", per_page=5)
        print(f"总结果数: {result.get('meta', {}).get('count', 'N/A')}")
    except Exception as e:
        print(f"请求失败: {e}")

    print()
    print("=" * 60)
    print("示例运行完成")
    print("运行 mock 测试: pytest examples.py -v")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
