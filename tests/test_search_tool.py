"""
网络搜索工具测试
"""

import pytest
from src.tools.search_tool import (
    TavilySearchBackend,
    BingSearchBackend,
    get_search_backend,
    format_search_results
)


class TestSearchBackend:
    """搜索后端测试"""

    def test_tavily_backend_creation(self):
        """测试 Tavily 后端创建"""
        try:
            backend = TavilySearchBackend()
            assert backend is not None
        except ValueError:
            pytest.skip("TAVILY_API_KEY not configured")

    def test_tavily_search(self):
        """测试 Tavily 搜索功能"""
        try:
            backend = TavilySearchBackend()
            results = backend.search("乡村振兴政策 2025", num_results=3)
            assert isinstance(results, list)
            # 不要求一定有结果，但类型要正确
            for result in results:
                assert "title" in result
                assert "url" in result
            print(f"\n搜索结果数量：{len(results)}")
        except ValueError:
            pytest.skip("TAVILY_API_KEY not configured")

    def test_format_results(self):
        """测试结果格式化"""
        mock_results = [
            {
                "title": "测试标题",
                "url": "https://example.com",
                "snippet": "测试摘要内容",
                "score": 0.95
            }
        ]
        formatted = format_search_results(mock_results)
        assert "## 网络搜索结果" in formatted
        assert "测试标题" in formatted
        assert "https://example.com" in formatted

    def test_format_results_empty(self):
        """测试空结果格式化"""
        formatted = format_search_results([])
        assert "未找到相关搜索结果" in formatted

    def test_web_search_tool_via_registry(self):
        """测试通过 ToolRegistry 调用搜索工具"""
        from src.tools.registry import ToolRegistry

        try:
            # 测试错误处理（没有配置 API key 时）
            result = ToolRegistry.execute_tool(
                "web_search",
                {"query": "村庄规划 最新政策", "num_results": 2}
            )
            assert isinstance(result, str)
            # 如果配置了 API key 会返回搜索结果，否则会返回错误信息
            print(f"\n工具返回：{result[:200]}...")
        except ValueError as e:
            pytest.skip(f"搜索工具不可用：{e}")


class TestBingBackend:
    """Bing 搜索后端测试"""

    def test_bing_backend_creation(self):
        """测试 Bing 后端创建"""
        try:
            backend = BingSearchBackend()
            assert backend is not None
        except ValueError:
            pytest.skip("BING_SEARCH_API_KEY not configured")

    def test_bing_backend_no_config(self):
        """测试 Bing 未配置时的行为"""
        # 模拟未配置的情况
        backend = BingSearchBackend(api_key="", endpoint="")
        results = backend.search("test query")
        assert results == []
