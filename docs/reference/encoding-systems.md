# 编码体系参考

> 本文是查表索引，不是规划决策规则。当前实现位于
> `backend/app/data/encodings/` 和 `backend/app/data/catalog/advisory_crosswalks/`。
> advisory crosswalk 不能替代显式规划分类决定。

## 编码文件

| 编码 | 当前文件 |
|---|---|
| GB/T 21010 | `data/encodings/dicts/encodings/gbt21010.yaml` |
| TUGUI | `data/encodings/dicts/encodings/tugui.yaml` |
| APPENDIX5 | `data/encodings/dicts/encodings/appendix5.yaml` |
| GHFLBM | `data/encodings/dicts/encodings/ghflbm.yaml` |
| YDYHFL | `data/encodings/dicts/encodings/ydyhfldm.yaml` |
| VNE | `data/encodings/dicts/encodings/vne.yaml` |
| planning/primary/three categories | `data/encodings/dicts/encodings/` 下对应 YAML |

## Advisory 映射

映射和规则位于 `backend/app/data/catalog/advisory_crosswalks/yaml/`，例如 GB/T 21010、
GHFLBM、VNE、规划分区到主空间分区和控制码的 crosswalk。它们用于候选、展示或规则
辅助，不能由名称、现状 `dlbm` 或 crosswalk 自动写入规划分类。

## 相关入口

- loader/rule evaluator：`backend/app/data/encodings/dicts/`
- catalog registry：`backend/app/data/catalog/`
- 领域分类决定：`backend/app/contracts/domain/`、`backend/app/domain/program/`
- 成果约束：[Planning and Execution](../design/03_PLANNING_EXECUTION.md)
