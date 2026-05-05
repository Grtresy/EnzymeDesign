#!/usr/bin/env python3
"""
CORE API 请求示例

本脚本演示如何使用 CORE API 搜索和下载开放获取论文。
包括：搜索论文、获取元数据、下载全文。

注意: CORE 官方当前文档以 v2 Swagger 为准；本文件同步示例使用该公开 surface。

运行方式:
    # 直接运行
    python examples.py

    # 如有 API Key，可一并提供
    CORE_API_KEY=your-api-key python examples.py

    # 仅运行 mock 测试（无需 API Key）
    pytest examples.py -v
"""

import os
import re
import asyncio
from typing import Dict
from urllib.parse import quote

import httpx
import pytest
from pytest_httpx import HTTPXMock


# ============ 配置 ============
API_KEY = os.environ.get("CORE_API_KEY")
BASE_URL = "https://api.core.ac.uk/v2"
RATE_LIMIT_DELAY = 0.5


def _get_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    return headers


# ============ 异步请求 ============
async def search_works_async(query: str) -> Dict:
    """搜索论文（异步版本）"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/search/{quote(query)}", headers=_get_headers())
        response.raise_for_status()
        return response.json()


async def get_work_async(work_id: str) -> Dict:
    """获取单篇论文（异步版本）"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/articles/get/{work_id}", headers=_get_headers())
        response.raise_for_status()
        return response.json()


# ============ 同步请求 ============
def search_works(query: str) -> Dict:
    """搜索论文（同步版本）"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/search/{quote(query)}", headers=_get_headers())
        response.raise_for_status()
        return response.json()


def get_work(work_id: str) -> Dict:
    """获取单篇论文（同步版本）"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/articles/get/{work_id}", headers=_get_headers())
        response.raise_for_status()
        return response.json()


def download_work(work_id: str) -> bytes:
    """下载论文 PDF（同步版本）"""
    with httpx.Client(timeout=60.0) as client:
        response = client.get(f"{BASE_URL}/articles/get/{work_id}/download/pdf", headers=_get_headers())
        response.raise_for_status()
        return response.content


# ============ Mock 测试 (使用 pytest-httpx) ============
def test_search_mock(httpx_mock: HTTPXMock):
    """Mock 测试：搜索论文"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/search/.*"),
        json={"totalHits": 100, "results": [{"id": "12345678", "title": "Test Paper 1"}]},
        status_code=200
    )
    result = search_works("enzyme engineering")
    assert result["totalHits"] == 100


def test_get_work_mock(httpx_mock: HTTPXMock):
    """Mock 测试：获取单篇论文"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/articles/get/12345678.*"),
        json={"id": "12345678", "title": "Test Paper Title", "doi": "10.1234/test"},
        status_code=200
    )
    result = get_work("12345678")
    assert result["id"] == "12345678"


def test_download_mock(httpx_mock: HTTPXMock):
    """Mock 测试：下载 PDF"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/articles/get/12345678/download/pdf.*"),
        content=b"%PDF-1.4 fake pdf content",
        status_code=200
    )
    content = download_work("12345678")
    assert content.startswith(b"%PDF")


def test_similar_mock(httpx_mock: HTTPXMock):
    """Mock 测试：获取相似论文"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/articles/similar.*"),
        json={"results": [{"id": "87654321", "title": "Similar Paper 1"}]},
        status_code=200
    )
    with httpx.Client(timeout=30.0) as client:
        response = client.post(f"{BASE_URL}/articles/similar", json={"ids": ["12345678"]}, headers=_get_headers())
        result = response.json()
    assert len(result["results"]) == 1


def test_enzyme_search_mock(httpx_mock: HTTPXMock):
    """Mock 测试：酶文献搜索"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/search/.*"),
        json={"totalHits": 50, "results": [{"id": "enz001", "title": "Engineering of thermostable lipase enzymes", "downloadUrl": "https://example.com/lipase.pdf"}]},
        status_code=200
    )
    result = search_works("lipase enzyme")
    papers_with_url = [p for p in result["results"] if p.get("downloadUrl")]
    assert len(papers_with_url) == 1


# ============ 主函数 ============
async def main():
    """运行示例"""
    print("=" * 60)
    print("CORE API 示例")
    print("=" * 60)

    print(f"API Key 配置: {'已设置' if API_KEY else '未设置'}")

    print("示例 1: 搜索酶相关开放获取论文")
    print("-" * 40)
    try:
        result = await search_works_async("enzyme engineering")
        print(f"总结果数: {result.get('totalHits', 'N/A')}")
    except Exception as e:
        print(f"请求失败: {e}")

    print()
    print("=" * 60)
    print("示例运行完成")
    print("运行 mock 测试: pytest examples.py -v")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
