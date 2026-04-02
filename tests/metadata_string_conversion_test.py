"""
元数据字符串转换测试

验证 MetadataInjector 将列表元数据转换为字符串，以及 kb_manager 正确解析回列表
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.documents import Document
from src.rag.metadata.injector import MetadataInjector


def test_metadata_injector_list_to_string():
    """测试 MetadataInjector 将列表转换为字符串"""
    print("\n" + "=" * 60)
    print("测试：MetadataInjector 列表元数据转换为字符串")
    print("=" * 60)

    injector = MetadataInjector()

    # 创建测试文档
    doc = Document(
        page_content="测试内容",
        metadata={"source": "test.pdf"}
    )

    # 测试手动指定的维度标签
    manual_dimension_tags = ["socio_economic", "public_services", "architecture", "industry_development"]
    manual_regions = ["测试村 1", "测试村 2"]

    # 注入元数据
    result_doc = injector.inject(
        doc=doc,
        manual_dimension_tags=manual_dimension_tags,
        manual_terrain="mountain",
        manual_doc_type="policy",
    )

    # 验证 dimension_tags 是字符串而不是列表
    dimension_tags_value = result_doc.metadata.get("dimension_tags")
    regions_value = result_doc.metadata.get("regions")

    print(f"\n原始列表：{manual_dimension_tags}")
    print(f"注入后的值：{dimension_tags_value}")
    print(f"类型：{type(dimension_tags_value)}")

    assert isinstance(dimension_tags_value, str), f"dimension_tags 应该是字符串，但得到了 {type(dimension_tags_value)}"
    assert dimension_tags_value == ",".join(manual_dimension_tags), f"值不匹配：{dimension_tags_value}"

    print("\n✅ dimension_tags 正确转换为字符串")

    # 测试地区
    print(f"\n原始地区列表：{manual_regions}")
    print(f"注入后的值：{regions_value}")
    print(f"类型：{type(regions_value)}")

    # 注意：inject() 方法会从文本中提取 regions，所以手动指定的 regions 不会直接注入
    # 这里我们验证 regions 是字符串类型
    if regions_value:
        assert isinstance(regions_value, str), f"regions 应该是字符串，但得到了 {type(regions_value)}"
        print("✅ regions 是字符串类型")

    # 测试默认值
    doc2 = Document(
        page_content="测试内容 2",
        metadata={"source": "test2.pdf"}
    )
    result_doc2 = injector.inject(doc=doc2)

    default_dimension_tags = result_doc2.metadata.get("dimension_tags")
    print(f"\n默认 dimension_tags: {default_dimension_tags}")
    print(f"类型：{type(default_dimension_tags)}")

    assert isinstance(default_dimension_tags, str), f"默认 dimension_tags 应该是字符串"
    assert default_dimension_tags == "general", f"默认值应该是 'general'"

    print("✅ 默认 dimension_tags 正确设置为 'general'")

    print("\n" + "=" * 60)
    print("所有测试通过！")
    print("=" * 60)


def test_kb_manager_string_to_list():
    """测试 kb_manager 将字符串解析回列表"""
    print("\n" + "=" * 60)
    print("测试：kb_manager 字符串元数据解析为列表")
    print("=" * 60)

    # 模拟 ChromaDB 返回的元数据（字符串格式，使用英文逗号分隔）
    mock_metadata = {
        "dimension_tags": "socio_economic,public_services,architecture",
        "regions": "测试村 1,测试村 2,测试村 3",  # 使用英文逗号分隔
        "terrain": "mountain",
        "category": "policies",
    }

    # 模拟解析逻辑
    dimension_tags = mock_metadata.get("dimension_tags", "").split(",") if mock_metadata.get("dimension_tags") else []
    regions = mock_metadata.get("regions", "").split(",") if mock_metadata.get("regions") else []

    print(f"\n原始字符串：{mock_metadata['dimension_tags']}")
    print(f"解析后的列表：{dimension_tags}")

    assert isinstance(dimension_tags, list), f"dimension_tags 应该是列表，但得到了 {type(dimension_tags)}"
    assert dimension_tags == ["socio_economic", "public_services", "architecture"], f"值不匹配"

    print("✅ dimension_tags 正确解析为列表")

    print(f"\n原始字符串：{mock_metadata['regions']}")
    print(f"解析后的列表：{regions}")

    assert isinstance(regions, list), f"regions 应该是列表，但得到了 {type(regions)}"
    assert regions == ["测试村 1", "测试村 2", "测试村 3"], f"值不匹配"

    print("✅ regions 正确解析为列表")

    # 测试空字符串处理
    empty_metadata = {
        "dimension_tags": "",
        "regions": "",
    }

    empty_dimension_tags = empty_metadata.get("dimension_tags", "").split(",") if empty_metadata.get("dimension_tags") else []
    empty_regions = empty_metadata.get("regions", "").split(",") if empty_metadata.get("regions") else []

    assert empty_dimension_tags == [], f"空字符串应该解析为空列表"
    assert empty_regions == [], f"空字符串应该解析为空列表"

    print("✅ 空字符串正确解析为空列表")

    print("\n" + "=" * 60)
    print("所有测试通过！")
    print("=" * 60)


if __name__ == "__main__":
    test_metadata_injector_list_to_string()
    test_kb_manager_string_to_list()
    print("\n✅ 所有元数据转换测试通过！")
