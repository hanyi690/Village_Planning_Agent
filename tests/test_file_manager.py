"""
测试文件管理工具

测试 VillageDataManager 的各种功能。
"""

import pytest
from pathlib import Path
import tempfile
import os

# 添加项目根目录到路径
import sys
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.tools.file_manager import VillageDataManager, read_village_data, load_data_with_metadata


class TestVillageDataManager:
    """测试 VillageDataManager 类"""

    def setup_method(self):
        """每个测试方法前的设置"""
        self.manager = VillageDataManager()
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """每个测试方法后的清理"""
        # 清理临时文件
        import shutil
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)

    def test_load_text_data(self):
        """测试加载纯文本数据"""
        text = "人口：1200人\n面积：5.2平方公里\n主要产业：农业"
        result = self.manager.load_data(text)

        assert result["success"] is True
        assert result["content"] == text
        assert result["metadata"]["type"] == "text"
        assert result["metadata"]["size"] == len(text)
        assert result["error"] == ""

    def test_load_text_empty(self):
        """测试加载空文本"""
        result = self.manager.load_data("")

        assert result["success"] is False
        assert result["content"] == ""
        assert "空" in result["error"]

    def test_load_txt_file(self):
        """测试加载txt文件"""
        # 创建临时txt文件
        txt_file = Path(self.temp_dir) / "test_data.txt"
        content = "村庄名称：测试村\n人口：1000人"
        txt_file.write_text(content, encoding='utf-8')

        # 加载文件
        result = self.manager.load_data(str(txt_file))

        assert result["success"] is True
        assert result["content"] == content
        assert result["metadata"]["type"] == "file"
        assert result["metadata"]["filename"] == "test_data.txt"
        assert result["metadata"]["extension"] == ".txt"

    def test_load_nonexistent_file(self):
        """测试加载不存在的文件"""
        result = self.manager.load_data("nonexistent_file.txt")

        assert result["success"] is False
        assert "不存在" in result["error"]

    def test_detect_source_type_file(self):
        """测试检测文件类型"""
        # 创建临时文件
        txt_file = Path(self.temp_dir) / "test.txt"
        txt_file.write_text("test content")

        detected_type = self.manager._detect_source_type(str(txt_file))
        assert detected_type == "file"

    def test_detect_source_type_text(self):
        """测试检测文本类型"""
        text = "人口：1200人\n面积：5.2平方公里"
        detected_type = self.manager._detect_source_type(text)
        assert detected_type == "text"

    def test_batch_load_files(self):
        """测试批量加载文件"""
        # 创建多个测试文件
        files = []
        for i in range(3):
            file_path = Path(self.temp_dir) / f"test{i}.txt"
            file_path.write_text(f"内容{i}", encoding='utf-8')
            files.append(str(file_path))

        # 批量加载（不合并）
        result = self.manager.batch_load_files(files, merge=False)

        assert result["success"] is True
        assert result["metadata"]["total_files"] == 3
        assert result["metadata"]["success_count"] == 3

        # 批量加载（合并）
        result_merged = self.manager.batch_load_files(files, merge=True)

        assert result_merged["success"] is True
        assert "内容0" in result_merged["content"]
        assert "内容1" in result_merged["content"]
        assert "内容2" in result_merged["content"]


class TestConvenienceFunctions:
    """测试便捷函数"""

    def test_read_village_data_text(self):
        """测试读取文本数据"""
        text = "人口：1200人"
        result = read_village_data(text)
        assert result == text

    def test_read_village_data_file(self):
        """测试读取文件数据"""
        # 创建临时文件
        temp_dir = tempfile.mkdtemp()
        try:
            txt_file = Path(temp_dir) / "test.txt"
            content = "测试内容"
            txt_file.write_text(content, encoding='utf-8')

            result = read_village_data(str(txt_file))
            assert result == content
        finally:
            import shutil
            shutil.rmtree(temp_dir)

    def test_load_data_with_metadata(self):
        """测试加载数据并获取元数据"""
        text = "人口：1200人\n面积：5.2平方公里"
        result = load_data_with_metadata(text)

        assert result["success"] is True
        assert result["content"] == text
        assert "metadata" in result
        assert result["metadata"]["type"] == "text"


class TestFileFormats:
    """测试支持的文件格式"""

    def setup_method(self):
        """每个测试方法前的设置"""
        self.manager = VillageDataManager()
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """每个测试方法后的清理"""
        import shutil
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)

    def test_supported_formats_list(self):
        """测试支持的格式列表"""
        from src.tools.file_manager import SUPPORTED_EXTENSIONS

        expected_formats = ['.txt', '.pdf', '.docx', '.md', '.pptx', '.ppt']
        for fmt in expected_formats:
            assert fmt in SUPPORTED_EXTENSIONS

    def test_unsupported_format(self):
        """测试不支持的格式"""
        # 创建一个不支持的文件格式
        unsupported_file = Path(self.temp_dir) / "test.xyz"
        unsupported_file.write_text("test content")

        result = self.manager.load_data(str(unsupported_file))

        assert result["success"] is False
        assert "不支持的文件格式" in result["error"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
