# schema/encodings/dicts

编码字典目录负责加载、校验和解释声明式编码规则。它属于 Schema 层，只返回类型化规则、词汇和候选映射，不访问数据库、LLM、API 或 LangGraph。

## 文件职责

| 文件 | 职责 |
|---|---|
| `loader.py` | 读取字典文件并做基础结构校验 |
| `rule_loader.py` | 加载规则 DSL |
| `candidate_engine.py` | 根据规则生成候选编码 |
| `disambiguation.py` | 处理编码歧义，不做最终空间选址 |
| `expr_eval.py` | 在白名单表达式上执行确定性判断 |
| `vocabularies/` | 词汇文件及其加载器 |

正式编码集合和跨体系映射仍由 `schema/encodings/` 统一导出；本目录不能成为第二套 code-set API。

## 验证

运行 Schema 契约测试和编码表加载测试；新增规则必须有非法表达式、缺字段和重复编码用例。
