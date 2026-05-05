#!/usr/bin/env python3
"""
Europe PMC API 请求示例

本脚本演示如何使用 Europe PMC API 进行文献检索和获取。
包括：搜索文献、获取全文、获取注释、获取数据库链接。

运行方式:
    # 真实请求（无需 API Key）
    python examples.py

    # 仅运行 mock 测试
    pytest examples.py -v
"""

import re
import asyncio
from typing import Dict

import httpx
import pytest
from pytest_httpx import HTTPXMock


# ============ 配置 ============
BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
RATE_LIMIT_DELAY = 0.2


# ============ 异步请求 ============
async def search_papers_async(query: str, page_size: int = 25) -> Dict:
    """搜索文献（异步版本）"""
    params = {"query": query, "pageSize": page_size, "resultType": "core", "format": "json"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/search", params=params)
        response.raise_for_status()
        return response.json()


# ============ 同步请求 ============
def search_papers(query: str, page_size: int = 25) -> Dict:
    """搜索文献（同步版本）"""
    params = {"query": query, "pageSize": page_size, "resultType": "core", "format": "json"}
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/search", params=params)
        response.raise_for_status()
        return response.json()


def get_article(source: str, article_id: str) -> Dict:
    """获取文章详情（同步版本）"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/article/{source}/{article_id}", params={"format": "json"})
        response.raise_for_status()
        return response.json()


def get_annotations(article_ids: str) -> Dict:
    """按 articleIds 获取注释"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            f"{BASE_URL}/annotations_api/annotationsByArticleIds",
            params={"articleIds": article_ids, "format": "json"},
        )
        response.raise_for_status()
        return response.json()


def get_database_links(source: str, article_id: str) -> Dict:
    """获取数据库交叉引用"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/{source}/{article_id}/databaseLinks", params={"format": "json"})
        response.raise_for_status()
        return response.json()


def get_fulltext_xml(pmcid: str) -> str:
    """获取开放获取全文 XML"""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/{pmcid}/fullTextXML")
        response.raise_for_status()
        return response.text


# ============ Mock 测试 (使用 pytest-httpx) ============
def test_search_mock(httpx_mock: HTTPXMock):
    """Mock 测试：搜索文献"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/search.*"),
        json={
            "version": "4.0",
            "hitCount": 100,
            "resultList": {
                "result": [
                    {"id": "38123456", "pmid": "38123456", "title": "Test Paper 1", "isOpenAccess": "Y"},
                    {"id": "38123457", "pmid": "38123457", "title": "Test Paper 2", "isOpenAccess": "N"}
                ]
            }
        },
        status_code=200
    )

    result = search_papers("enzyme engineering")
    assert result["hitCount"] == 100
    assert len(result["resultList"]["result"]) == 2


def test_article_mock(httpx_mock: HTTPXMock):
    """Mock 测试：获取文章详情"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/article/MED/38123456.*"),
        json={"result": {"pmid": "38123456", "title": "Test Article Title", "abstractText": "This is a test abstract."}},
        status_code=200
    )

    result = get_article("MED", "38123456")
    assert result["result"]["pmid"] == "38123456"


def test_annotations_mock(httpx_mock: HTTPXMock):
    """Mock 测试：获取文献注释"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/annotations_api/annotationsByArticleIds.*"),
        json={"annotations": [{"exact": "lipase", "type": "Chemical", "id": "http://purl.obolibrary.org/obo/CHEBI_28593"}]},
        status_code=200
    )

    result = get_annotations("PMC:PMC1234567")
    assert len(result["annotations"]) == 1
    assert result["annotations"][0]["type"] == "Chemical"


def test_database_links_mock(httpx_mock: HTTPXMock):
    """Mock 测试：获取数据库链接"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/PMC/PMC1234567/databaseLinks.*"),
        json={
            "pmcid": "PMC1234567",
            "hasDbLinks": "Y",
            "dbCrossReferenceList": {"dbCrossReference": [{"dbName": "UNIPROT", "accession": "P00533", "info": "EGFR"}]}
        },
        status_code=200
    )

    result = get_database_links("PMC", "PMC1234567")
    assert result["hasDbLinks"] == "Y"


def test_open_access_search_mock(httpx_mock: HTTPXMock):
    """Mock 测试：开放获取搜索"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/search.*"),
        json={"hitCount": 50, "resultList": {"result": [{"pmid": "12345678", "title": "Open Access Paper", "isOpenAccess": "Y"}]}},
        status_code=200
    )

    result = search_papers("TITLE:enzyme AND OPEN_ACCESS:Y")
    assert result["resultList"]["result"][0]["isOpenAccess"] == "Y"


def test_fulltext_xml_mock(httpx_mock: HTTPXMock):
    """Mock 测试：获取全文 XML"""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE_URL)}/PMC1234567/fullTextXML.*"),
        text="<article><body><p>Test full text</p></body></article>",
        status_code=200,
    )

    result = get_fulltext_xml("PMC1234567")
    assert "<article>" in result


# ============ 主函数 ============
async def main():
    """运行示例"""
    print("=" * 60)
    print("Europe PMC API 示例")
    print("=" * 60)
    print("注意: 无需 API Key")
    print()

    print("示例 1: 搜索开放获取的酶工程文献")
    print("-" * 40)
    try:
        result = await search_papers_async("TITLE:enzyme AND ABSTRACT:engineering AND OPEN_ACCESS:Y", page_size=5)
        print(f"总结果数: {result.get('hitCount', 'N/A')}")
    except Exception as e:
        print(f"请求失败: {e}")

    print()
    print("=" * 60)
    print("示例运行完成")
    print("运行 mock 测试: pytest examples.py -v")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
