"""
瓦片请求链路调试脚本

测试路径：
1. 直接调用 TileService.get_annotation_url()
2. 直接调用 TileService.get_tile_url()
3. 模拟后端 API 代理请求
4. 验证瓦片返回状态
"""

import asyncio
import httpx
from src.tools.geocoding.tianditu.tiles import TileService
from src.tools.geocoding.tianditu.constants import TILE_LAYERS, ANNOTATION_LAYERS


async def test_tile_service():
    """测试 TileService URL 生成"""
    ts = TileService()

    print("=== 1. 测试底图 URL ===")
    url = ts.get_tile_url("vec", "c", 200, 400, 10)
    print(f"vec_c URL: {url}")

    print("\n=== 2. 测试注记 URL ===")
    url = ts.get_annotation_url("cva", "c", 200, 400, 10)
    print(f"cva_c URL: {url}")

    print("\n=== 3. 直接请求瓦片 ===")
    client = httpx.AsyncClient(timeout=10.0)

    # 底图瓦片
    resp = await client.get(ts.get_tile_url("vec", "c", 200, 400, 10))
    print(f"vec_c 状态: {resp.status_code}, 大小: {len(resp.content)} bytes")

    # 注记瓦片
    resp = await client.get(ts.get_annotation_url("cva", "c", 200, 400, 10))
    print(f"cva_c 状态: {resp.status_code}, 大小: {len(resp.content)} bytes")

    await client.aclose()


async def test_backend_proxy():
    """测试后端代理 API"""
    print("\n=== 4. 测试后端代理 ===")

    # 前端请求路径: /api/tiles/tianditu/vec_c/10/200/400
    # 后端解析: layer=vec_c -> tile_layer=vec, projection=c

    client = httpx.AsyncClient(timeout=10.0)

    # 底图代理
    base_url = "http://localhost:8000/api/tiles/tianditu/vec_c/10/400/200"
    resp = await client.get(base_url)
    print(f"底图代理: {base_url}")
    print(f"  状态: {resp.status_code}, 大小: {len(resp.content)} bytes")

    # 注记代理
    annotation_url = "http://localhost:8000/api/tiles/tianditu/cva_c/10/400/200"
    resp = await client.get(annotation_url)
    print(f"注记代理: {annotation_url}")
    print(f"  状态: {resp.status_code}, 大小: {len(resp.content)} bytes")

    await client.aclose()


async def main():
    print("=" * 50)
    print("瓦片请求链路调试")
    print("=" * 50)

    print(f"\n可用底图图层: {TILE_LAYERS}")
    print(f"可用注记图层: {ANNOTATION_LAYERS}")

    await test_tile_service()

    # 仅在后端运行时测试代理
    print("\n[后端代理测试需要后端服务运行]")
    try:
        await test_backend_proxy()
    except httpx.ConnectError:
        print("后端服务未运行，跳过代理测试")


if __name__ == "__main__":
    asyncio.run(main())