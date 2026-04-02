"""
网络搜索工具 - 支持 Agent 自主联网获取信息

支持多种搜索后端:
- Tavily Search API (推荐，简单可靠)
- Bing Search API (备选)
"""

import os
from typing import Any, Dict, List, Optional
from ..utils.logger import get_logger

logger = get_logger(__name__)


class SearchBackend:
    """搜索后端基类"""

    def search(self, query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """
        执行搜索并返回结果

        Args:
            query: 搜索查询
            num_results: 返回结果数量

        Returns:
            搜索结果列表，每项包含 title, url, snippet
        """
        raise NotImplementedError


class TavilySearchBackend(SearchBackend):
    """Tavily Search API 后端"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        if not self.api_key:
            raise ValueError("TAVILY_API_KEY not configured")

    def search(self, query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """使用 Tavily API 执行搜索"""
        import requests

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": num_results,
            "search_depth": "basic"
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()

            results = []
            for result in data.get("results", []):
                results.append({
                    "title": result.get("title", "无标题"),
                    "url": result.get("url", ""),
                    "snippet": result.get("content", ""),
                    "score": result.get("score", 0)
                })
            logger.info(f"[Tavily] 搜索成功：query='{query[:50]}...', results={len(results)}")
            return results
        except requests.exceptions.Timeout:
            logger.error(f"[Tavily] 请求超时：query='{query[:50]}...'")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"[Tavily] 请求失败：{e}")
            return []
        except Exception as e:
            logger.error(f"[Tavily] 搜索失败：{e}")
            return []


class BingSearchBackend(SearchBackend):
    """Bing Search API 后端"""

    def __init__(self, api_key: Optional[str] = None, endpoint: Optional[str] = None):
        self.api_key = api_key or os.getenv("BING_SEARCH_API_KEY")
        self.endpoint = endpoint or os.getenv("BING_SEARCH_ENDPOINT")

    def search(self, query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """使用 Bing API 执行搜索"""
        import requests

        if not self.api_key or not self.endpoint:
            logger.warning("Bing API 未配置")
            return []

        url = f"{self.endpoint}/v7.0/search"
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}
        params = {"q": query, "count": num_results}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            results = []
            for result in data.get("webPages", {}).get("value", []):
                results.append({
                    "title": result.get("name", "无标题"),
                    "url": result.get("url", ""),
                    "snippet": result.get("snippet", ""),
                    "date": result.get("dateLastCrawled", "")
                })
            logger.info(f"[Bing] 搜索成功：query='{query[:50]}...', results={len(results)}")
            return results
        except Exception as e:
            logger.error(f"[Bing] 搜索失败：{e}")
            return []


def get_search_backend(backend: str = "tavily") -> SearchBackend:
    """获取搜索后端实例"""
    if backend == "tavily":
        return TavilySearchBackend()
    elif backend == "bing":
        return BingSearchBackend()
    else:
        raise ValueError(f"不支持的搜索后端：{backend}")


def format_search_results(results: List[Dict[str, Any]], max_results: int = 5) -> str:
    """格式化搜索结果"""
    if not results:
        return "未找到相关搜索结果"

    formatted = ["## 网络搜索结果\n"]
    for i, result in enumerate(results[:max_results], 1):
        formatted.append(f"**{i}. {result['title']}**")
        formatted.append(f"   URL: {result['url']}")
        formatted.append(f"   {result['snippet']}\n")

    return "\n".join(formatted)
