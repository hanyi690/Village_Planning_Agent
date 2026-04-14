"""
LLM 多模态测试脚本

验证多模态简化修改：
- create_llm(model=LLM_MODEL) 统一调用
- build_multimodal_message() 消息构建
- qwen3.6-plus 模型处理纯文本和图片
"""

import os
import sys
import base64
from pathlib import Path
import io
import struct
import zlib

# 项目路径设置
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from src.core.llm_factory import create_llm
from src.core.message_builder import build_multimodal_message
from src.core.config import LLM_MODEL, DEFAULT_IMAGE_FORMAT
from langchain_core.messages import HumanMessage


def get_test_image_base64():
    """生成有效的 10x10 红色 PNG 图片 base64"""
    def create_png(width, height, color=(255, 0, 0)):
        def png_chunk(chunk_type, data):
            chunk_len = len(data)
            chunk = struct.pack('>I', chunk_len) + chunk_type + data
            crc = zlib.crc32(chunk_type + data) & 0xffffffff
            return chunk + struct.pack('>I', crc)

        # PNG signature
        signature = b'\x89PNG\r\n\x1a\n'

        # IHDR chunk
        ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
        ihdr = png_chunk(b'IHDR', ihdr_data)

        # IDAT chunk (image data)
        raw_data = b''
        for y in range(height):
            raw_data += b'\x00'  # filter byte
            for x in range(width):
                raw_data += bytes(color)

        compressed = zlib.compress(raw_data)
        idat = png_chunk(b'IDAT', compressed)

        # IEND chunk
        iend = png_chunk(b'IEND', b'')

        return signature + ihdr + idat + iend

    png_bytes = create_png(10, 10, (255, 0, 0))
    return base64.b64encode(png_bytes).decode('utf-8')


def test_1_text_only():
    """测试 1: 纯文本调用"""
    print("\n--- 测试 1: 纯文本 ---")
    llm = create_llm(model=LLM_MODEL, max_tokens=50)
    response = llm.invoke([HumanMessage(content="你好，请说'测试成功'")])
    print(f"模型: {LLM_MODEL}, 响应: {response.content}")
    return True


def test_2_message_builder():
    """测试 2: 多模态消息构建"""
    print("\n--- 测试 2: 消息构建 ---")
    # 纯文本
    msg1 = build_multimodal_message("纯文本")
    print(f"纯文本消息类型: {type(msg1.content)}")

    # 图片+文本
    msg2 = build_multimodal_message(
        text_content="描述图片",
        image_base64=get_test_image_base64(),
        image_format="png"
    )
    print(f"多模态消息类型: {type(msg2.content)}, 块数: {len(msg2.content)}")
    return True


def test_3_multimodal_invoke():
    """测试 3: 图片+文本调用"""
    print("\n--- 测试 3: 图片+文本 ---")
    llm = create_llm(model=LLM_MODEL, max_tokens=100)

    msg = build_multimodal_message(
        text_content="这是什么颜色？",
        image_base64=get_test_image_base64(),
        image_format="png"
    )
    response = llm.invoke([msg])
    print(f"响应: {response.content}")
    return True


def main():
    print("LLM 多模态测试")
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        print("错误: OPENAI_API_KEY 未配置")
        return False

    print(f"API Key: {api_key[:8]}..., LLM_MODEL: {LLM_MODEL}")

    try:
        test_1_text_only()
        test_2_message_builder()
        test_3_multimodal_invoke()
        print("\n所有测试完成")
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        return False
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)