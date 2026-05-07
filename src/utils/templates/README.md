# Word模板目录

此目录存放村庄规划文档的Word模板文件。

## 模板文件（待创建）

- `planning_text.docx` - 规划文本模板
- `project_table.docx` - 项目清单表格模板

## 使用方式

```python
from src.utils.planning_compiler import PlanningCompiler

compiler = PlanningCompiler()
result = compiler.compile(village_name, layer_reports)
```