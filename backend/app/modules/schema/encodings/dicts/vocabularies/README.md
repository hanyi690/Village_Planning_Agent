# Encoding vocabularies

本目录存放编码 DSL 使用的词汇装载逻辑。词汇是规则输入，不是规划决策结果；加载失败应产生可定位诊断，不能静默扩大候选集合。

`loader.py` 的输出必须保持可序列化、稳定排序，并由上层 `dicts/loader.py` 统一调用。任何词汇别名、优先级或合法值变更，都应同步更新 `docs/reference/terminology.md` 和对应契约测试。
