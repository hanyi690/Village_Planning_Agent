"""
向量库元数据清单生成器

生成共享所需的元数据文件：
- MANIFEST.json: 向量库版本、数据源清单
- README.txt: 使用说明
"""
import json
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
CHROMA_DIR = PROJECT_ROOT / "knowledge_base" / "chroma_db"
DATA_DIR = PROJECT_ROOT / "data"


def generate_manifest():
    """生成向量库清单文件"""
    manifest = {
        "version": "1.0.0",
        "created_at": datetime.now().isoformat(),
        "embedding_model": {
            "provider": "aliyun",
            "model": "text-embedding-v4",
            "dimensions": 1024,
        },
        "vector_db": {
            "type": "chroma",
            "collection": "rural_planning",
        },
        "statistics": {
            "total_documents": 44,
            "total_chunks": 2057,
            "avg_chunk_size": 1772,
        },
        "categories": {
            "domain": "专业教材（城市规划原理等）",
            "laws": "法律法规（城乡规划法等）",
            "policies": "政策文件",
            "plans": "上位规划（广东省国土空间规划等）",
            "standards": "技术规范",
            "cases": "案例资料",
        },
        "data_sources": [],
    }

    # 扫描数据源
    supported_ext = {".pdf", ".doc", ".docx", ".md", ".txt"}
    for category_dir in DATA_DIR.iterdir():
        if category_dir.is_dir() and category_dir.name in ["domain", "laws", "policies", "plans", "standards", "cases"]:
            files = []
            for f in category_dir.rglob("*"):
                if f.is_file() and f.suffix.lower() in supported_ext:
                    files.append({
                        "name": f.name,
                        "size_kb": f.stat().st_size // 1024,
                    })
            manifest["data_sources"].append({
                "category": category_dir.name,
                "file_count": len(files),
                "files": files[:10],  # 只列出前10个文件作为示例
            })

    # 写入清单
    manifest_path = CHROMA_DIR / "MANIFEST.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"✅ 生成清单: {manifest_path}")
    return manifest_path


def generate_readme():
    """生成使用说明"""
    readme_content = """
# 村庄规划知识库向量库

## 版本信息
- 版本: 1.0.0
- 创建时间: {date}
- Embedding模型: 阿里云 text-embedding-v4 (1024维)

## 数据统计
- 文档数量: 44
- 切片数量: 2057
- 平均切片大小: 1772字符

## 使用方法

### 1. 解压向量库
将压缩包解压到项目的 `knowledge_base/chroma_db/` 目录。

### 2. 配置环境变量
确保 `.env` 文件中配置了阿里云 DashScope API Key:
```
DASHSCOPE_API_KEY=your_api_key
EMBEDDING_PROVIDER=aliyun
```

### 3. 检索示例
```python
from src.rag.core.tools import search_knowledge

# 基础检索
result = search_knowledge("城乡规划法", top_k=5)

# 按维度检索
result = search_knowledge("村庄建设用地", dimension="land_use_planning")
```

## 数据分类
| 类别 | 说明 | 文件数 |
|------|------|--------|
| domain | 专业教材 | 8 |
| laws | 法律法规 | 7 |
| policies | 政策文件 | 11 |
| plans | 上位规划 | 3 |
| standards | 技术规范 | 8 |
| cases | 案例资料 | 1 |

## 注意事项
- 向量库使用 Chroma 存储，需要 `langchain-chroma` 库
- Embedding使用阿里云API，需要有效的API Key
- 已排除扫描版PDF（非文字PDF）

---
生成工具: Village Planning Agent RAG System
""".format(date=datetime.now().strftime("%Y-%m-%d %H:%M"))

    readme_path = CHROMA_DIR / "README.txt"
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_content)

    print(f"✅ 生成说明: {readme_path}")
    return readme_path


def main():
    """生成所有元数据文件"""
    print("=" * 60)
    print("📋 生成向量库元数据")
    print("=" * 60)

    if not CHROMA_DIR.exists():
        print(f"❌ 向量库目录不存在: {CHROMA_DIR}")
        return

    print("\n📝 生成清单文件...")
    generate_manifest()

    print("\n📄 生成使用说明...")
    generate_readme()

    print("\n✅ 元数据生成完成!")
    print("   - MANIFEST.json: 版本和数据源清单")
    print("   - README.txt: 使用说明")


if __name__ == "__main__":
    main()