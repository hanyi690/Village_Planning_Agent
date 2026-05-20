# 规划文本生成系统 — Prompt 优化报告

**日期**：2026-05-19
**策略**：源头治理 — 优先优化各层 prompt，确保 Layer 阶段产出规划文本所需的结构化内容

---

## 一、修改总览

| 阶段 | 文件 | 状态 |
|------|------|------|
| P0 | `backend/app/services/modules/prompts/detailed.py` | 已优化 |
| P0 | `backend/app/services/modules/prompts/concept.py` | 已优化 |
| P0 | `backend/app/services/modules/prompts/analysis.py` | 已优化 |
| P0 | `scripts/experiments/prompt_optimization/test_prompts.py` | 已创建 |
| P1 | `scripts/experiments/planning_text/section_builder.py` | 已优化 |
| P1 | `scripts/experiments/planning_text/llm_styler.py` | 已优化 |
| P1 | `scripts/experiments/planning_text/reference_parser.py` | 已优化 |
| P1 | `scripts/experiments/planning_text/prompts/generation.py` | 已标记废弃 |
| P2 | `scripts/experiments/planning_text/docx_builder.py` | 已优化 |

---

## 二、Layer 3 Prompt Section 补全（P0 — 核心修改）

### 问题根因

`section_builder.py` 的 `ARTICLE_DEFS` 通过精确子串匹配从 Layer 3 报告中提取【】section 内容。但 Layer 3 prompt 定义的输出结构中，大量 section 未被要求生成，导致匹配失败 -> 子编号跳号 -> 内容支离破碎。

### 修改明细

| 维度 | 修改前 sections | 修改后 sections | 新增 |
|------|----------------|----------------|------|
| `settlement_planning` | 3 | 11 | +8 |
| `heritage` | 2 | 9 | +7 |
| `ecological` | 4 | 6 | +2 |
| `disaster_prevention` | 3 | 5 | +2 |
| `land_use_planning` | 3 | 5 | +2 |
| `infrastructure_planning` | 5 | 7 | +2 |
| `landscape` | 5 | 5 | 0（已完整） |
| 其余5个维度 | 各已完整 | 不变 | 0 |

**总计新增：23个 section，覆盖率从约 67% 提升至 100%**

### 同步增强

1. **规划文本用途说明**：每个 prompt 新增"你的输出将被用作规划文本第X条"的用途指引
2. **表格格式规范**：统一要求 `| :--- |` 分隔行格式、数值带单位
3. **内容质量指引**：每个 section 增加具体内容要求
4. **WRITING_RULES 升级**：用途说明 + 参考风格 + 禁用词扩展 + 表格格式严格规范

---

## 三、Layer 2 Prompt 优化（P0）

- **development_goals**：从单句目标 -> 总体目标 + 7项核心指标（耕地/基本农田/生态红线/建设用地/林地/森林覆盖率/人口）
- **planning_positioning**：新增村庄分类 + 上位规划衔接说明
- **planning_strategies**：新增策略间逻辑关系段落
- **resource_endowment**：资源描述增加定量数据（面积/等级/产值）

---

## 四、Layer 1 Prompt 优化（P0）

- **land_use**：新增6行用地结构表 + 耕地/林地/建设用地详情
- **socio_economic**：新增6行人口结构表 + 自然村名单格式化 + 收入水平
- **natural_environment**：新增4行地质灾害隐患点表 + 气候/地形具体数值

---

## 五、Section Builder 增强（P1）

- **模糊匹配 fallback**：`difflib.SequenceMatcher` 相似度 >=75% 作为备选
- **匹配日志**：记录每个 S-COPY 条文未匹配的 pattern
- **Bug 修复**：移除 `_clean_full` 重复定义

---

## 六、LLM 生成层优化（P1）

- **第7条上下文**：从 1100 -> 2000+ 字符（新增规划策略数据）
- **第19-22条上下文**：从 <50 -> 含村庄概况/人口/面积/定位/目标/指标
- **Few-shot**：从 300 -> 600 字符
- **死代码清理**：`prompts/generation.py` 添加 DeprecationWarning

---

## 七、DOCX 渲染修复（P2）

- **表格间距**：`doc.add_paragraph()` -> 微型间距（2pt/2pt）
- **文本连接**：盲目 `join` -> 智能合并（保留子段落换行）
- **标题样式**：Word Heading 样式 -> 纯段落 + 手动字体
- **表格着色**：偶数行添加 #F2F2F2 灰色底色

---

## 八、验证结果

- **Prompt Section 覆盖率**：100% (70/70 sections)，0 gaps
- **ARTICLE_DEFS 交叉验证**：All patterns found
- **语法检查**：9/9 files pass

---

## 九、不足与后续优化方向

### 当前未覆盖的问题

1. S-TEMPLATE 仍为硬编码（第2/3/4/6条）
2. S-ASSEMBLE 预留值未替换为警告机制
3. 跨村庄通用性：法律引用仅广东、村名/默认值硬编码
4. DOCX 高级格式：页码、目录、页眉页脚
5. 质量检查器：缺少跳号/预留值/内容一致性检测
6. 附件内容：5个附件均为占位符

### 建议后续 Phase

| 优先级 | 任务 |
|--------|------|
| P1 | S-TEMPLATE 注入村庄特异性 |
| P1 | S-ASSEMBLE 预留值 -> 警告 |
| P1 | 质量检查器扩展 |
| P2 | 跨村庄参数化 |
| P2 | DOCX 高级格式 |
| P3 | 端到端跨村庄测试（>=3村庄） |

### Prompt 质量持续监控

```bash
python scripts/experiments/prompt_optimization/test_prompts.py
```

该脚本在 section 覆盖率 <100% 时返回非零退出码，适合作为 CI/pre-commit 检查。
