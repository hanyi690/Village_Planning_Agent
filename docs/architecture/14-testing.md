# 测试架构

本文档说明测试结构和覆盖率。

## 测试结构

```
tests/
├── unit/           # 单元测试
├── integration/    # 集成测试
├── e2e/            # 端到端测试
```

## 测试分类

| 类型 | 范围 | 工具 |
|------|------|------|
| Unit | 单函数/类 | pytest |
| Integration | 模块交互 | pytest |
| E2E | 用户流程 | Playwright |

---

## 相关文档

- [file-index](./file-index.md) - 测试文件路径