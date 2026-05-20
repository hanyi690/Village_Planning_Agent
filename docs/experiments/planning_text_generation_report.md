# 规划文本生成系统 — 技术实现报告

## 一、系统总览

```
baseline_reports.json          ← Agent 3层28维度报告
       │
       ├── Layer1 (12维): 现状分析段落 — location, land_use, socio_economic 等
       ├── Layer2 (4维):  规划思路 — development_goals, planning_positioning 等
       └── Layer3 (12维): 详细规划 — industry, ecological, heritage 等
              │
   ┌──────────┼──────────┐
   ▼          ▼          ▼
content_extractor   reference_parser   llm_styler
(数字/表格提取)    (参考docx解析)     (Tier3 LLM生成)
   │          │          │
   └──────────┼──────────┘
              ▼
      section_builder (三层策略路由)
         ├─ S-COPY (10条)
         ├─ S-ASSEMBLE (3条)
         ├─ S-TEMPLATE (4条)
         └─ S-GENERATE (5条)
              │
       ┌──────┴──────┐
       ▼              ▼
   .render()      docx_builder
   → .md          → .docx
       │              │
       └──────┬───────┘
              ▼
      quality_checker
```

---

## 二、数据源：Agent三层报告详解

### 2.1 baseline_reports.json 结构

```json
{
  "session_id": "baseline_68d4bfa9",
  "checkpoint_id": "1f152ba9-...",
  "generated_at": "2026-05-18T21:08:06",
  "dimension_count": 28,
  "reports": {
    "location":   "文本内容...",
    "land_use":   "文本内容...",
    ...
  }
}
```

28个维度的报告以 `{维度key: 文本内容}` 映射存储。维度的生成由 `backend/app/agent/nodes/analysis.py` 通过LangGraph Send API并行/波次执行，prompt模板来自 `backend/app/services/modules/prompts/`。

### 2.2 Layer1 — 现状分析（12维度）

由 `analysis.py: get_layer1_prompt()` 生成，每个维度独立调用LLM。输出为自然段落叙述。

**dimension → 数据特征 → 提取用途**：

```
location:
  层级区位: "广东省→梅州市→平远县→泗水镇→金田村"
  → 无直接提取，保留作为上下文

land_use:
  "土地总用地面积约 2352.89 公顷"
  "农业用地 1960.70 公顷 (83.33%)"
  "建设用地 30.17 公顷 (1.28%)"
  "生态用地 362.02 公顷 (15.39%)"
  "耕地 85.2 公顷，水田 78.83 公顷"
  "林地占比 90%，商业林 1867.38 公顷，生态林 325.92 公顷"
  "水域 35.99 公顷"
  → 提取: total_area_ha, farmland_ha, paddy_ha, construction_land_ha,
         ecological_land_ha, forest_coverage_pct, commercial_forest_ha,
         ecological_forest_ha, water_ha

socio_economic:
  "下辖园寨、田坑、社前、分水、清明、塘笃、长塘、
   炉池、肩丰、营仔、新山、黄竹共 12 个自然村"
  "户籍人口 1403 人"
  "常住人口约 500 人"
  "325 户"
  → 提取: village_names, population_registered, population_resident,
         population_household

natural_environment:
  "5 处崩塌隐患点，35 处滑坡隐患点"
  → 提取: collapse_points, landslide_points

architecture:
  "现有建筑 583 处"
  → 提取: building_count

traffic:
  "Y122 乡道，X038 县道，公交站点 3 处"
  → 上下文引用

infrastructure:
  "供水管道 6000 余米，水电站 3 个"
  → 上下文引用

public_services:
  "小学、幼儿园各一处，卫生站一处，文化广场两处"
  → 上下文引用

ecological_green:
  "林地占比 90%，生态林 325.92 公顷"
  → 补充 ecological_forest_ha

historical_culture:
  "三座祠堂（950㎡/1450㎡），千年古檀树，古驿道遗存，船灯舞"
  → 上下文引用

villager_wishes:
  诉求排序: 生活保障→环境改善→增收致富→公共服务
  → 上下文引用

superior_planning:
  上位规划定位、约束、政策背景、指标分解
  → 上下文引用
```

**提取代码**（`content_extractor.py: _extract_numbers()`）：

```python
NUM_PATTERNS = [
    # (正则, 字段名, 倍数)
    (r'土地总用地面积[约]*\s*([\d.]+)\s*公顷', 'total_area_ha', 1.0),
    (r'户籍人口\s*(\d+)\s*人', 'population_registered', 1),
    (r'常住人口[约]?\s*(\d+)\s*人', 'population_resident', 1),
    (r'耕地面积[约]*\s*([\d.]+)\s*公顷', 'farmland_ha', 1.0),
    (r'建设用地[总面积]?\s*([\d.]+)\s*公顷', 'construction_land_ha', 1.0),
    (r'林地[面积]*[在占比达]?\s*(\d+)\s*%', 'forest_coverage_pct', 1.0),
    (r'(\d+)\s*处崩塌', 'collapse_points', 1),
    (r'(\d+)\s*处滑坡', 'landslide_points', 1),
    ...
]

# 两阶段提取:
# Phase1: land_use 报告单独提取 total_area_ha (避免被其他维度"总面积"覆盖)
# Phase2: 全部28维度联合提取其余字段 (跳过 Phase1 已提取的)
```

### 2.3 Layer2 — 规划思路（4维度）

由 `concept.py: get_layer2_prompt()` 生成。输出高度精炼：

```
development_goals:
    "粤闽赣边客家文化生态保育与特色南药康养旅游综合发展示范村"
    → 1行，直接供给 S-GENERATE 第7条

planning_positioning:
    "粤闽赣边客家文化生态保育村
     特色南药与林下经济产业村
     古驿道康养旅游特色村
     （释义：立足90%林地覆盖率与千年古檀树资源...）"
    → 3标签+释义，供给 S-GENERATE 第7条

planning_strategies:
    "生态优先——生态保护网格化（针对90%林地覆盖率...）
     产业振兴——主导产业特色化（针对产业结构单一...）
     设施完善——基础设施标准化（针对对外交通不便...）
     人居提升——村庄风貌优质化（针对道路景观较差...）
     治理有效——乡村治理现代化（针对常住人口老龄化...）"
    → 5条，格式"策略名——方向（问题+措施）"

resource_endowment:
    "民俗资源：平远船灯舞、添灯习俗...
     自然资源：90%覆盖率林地、金田河水系...
     历史古迹：南粤古驿道遗存、古茶亭遗址、三座祠堂...
     特色产业：林芝种植、烤烟种植、杉木家具制造...
     唯一性标签：【全镇唯一】船灯舞、【全县唯一】千年古檀树..."
    → 5类资源，分类列举
```

**提取代码**（`content_extractor.py: _extract_layer2()`）：

```python
for key, attr in [
    ('development_goals', 'development_goal'),
    ('planning_positioning', 'planning_positioning'),
    ('planning_strategies', 'planning_strategies'),
    ('resource_endowment', 'resource_endowment'),
]:
    if key in self.reports:
        setattr(self.data, attr, self.reports[key].strip())
# 直接全文字符串赋值，不做结构化解析
```

### 2.4 Layer3 — 详细规划（12维度）

由 `detailed.py: get_layer3_prompt()` 生成。每个维度输出包含多个 `【标题】` 段落，段落中混合自然文本和Markdown表格。

**12个维度的完整section清单**：

```
industry:            产业规划, 产业发展定位, 产业发展思路,
                    三链逻辑构建, 产业项目清单, 空间布局

traffic_planning:    道路交通规划, 路网格局, 道路等级规划, 交通设施清单

public_service:      公共服务设施规划, 配置原则与策略, 设施配置清单

infrastructure_planning: 基础设施规划, 给水工程, 排水工程, 电力工程,
                         通信工程, 环卫工程, 工程量汇总表

ecological:          生态绿地规划, 生态空间格局, 绿地指标,
                    绿地系统, 生态管控要求, 实施计划

disaster_prevention: 防灾减灾规划, 灾害风险评估, 防灾设施清单,
                    工程防治措施, 应急管理体系

heritage:            历史文化保护规划, 文化遗产清单, 保护范围划定,
                    建筑分类整治, 非物质文化遗产活化,
                    防灾减灾与安全, 产业融合利用,
                    基础设施配套, 人口与用地管控

landscape:           村庄风貌指引, 整体风貌定位与景观格局,
                    建筑风貌控制导则, 核心景观节点设计指引,
                    人居环境整治指引

project_bank:        建设项目库, 近期项目, 中期项目, 远期项目

spatial_structure:   空间结构规划, 空间结构模式, 功能节点规划,
                    功能分区表, 边界管控

land_use_planning:   土地利用规划, 土地利用结构调整表,
                    土地用途分区表, 重点建设项目清单,
                    风貌与设施管控要求

settlement_planning: 居民点规划, 规划目标, 人口与用地规模,
                    居民点布局模式, 布局说明, 宅基地规划表,
                    防灾减灾规划, 基础设施规划, 历史文化保护,
                    产业空间布局, 实施时序
```

**section解析**（`content_extractor.py: _parse_bracket_sections()`）：

```python
def _parse_bracket_sections(self, text: str) -> Dict[str, str]:
    pattern = re.compile(r'【(.+?)】\s*\n?')
    parts = list(pattern.finditer(text))
    # parts[0]: "生态空间格局" at position 16
    # parts[1]: "绿地指标" at position 89
    # ...

    for i, match in enumerate(parts):
        title = match.group(1).strip()       # "绿地指标"
        start = match.end()
        end = parts[i+1].start() if i+1 < len(parts) else len(text)
        content = text[start:end].strip()
        sections[title] = content
```

---

## 三、Section获取与映射

### 3.1 从维度级到Section级的映射

早期版本按维度映射（`Article 9 → ["land_use_planning", "settlement_planning"]`），导致同一维度内容在多个条文间重复。改进为section级精确映射。

**ARTICLE_DEFS 完整定义**：

```python
ARTICLE_DEFS = {
    # 第9条: 从2个维度取8个section
    9: ("建设用地布局优化", 3, "S-COPY", {
        "land_use_planning": [
            "土地利用规划",          # 核心管控段落
            "土地利用结构调整表",    # 地类/现状/规划/变化 表
            "土地用途分区表",        # 分区/面积/管控 表
        ],
        "settlement_planning": [
            "居民点规划",            # 总述
            "规划目标",              # 集约用地
            "人口与用地规模",        # 人口/指标
            "居民点布局模式",        # "组团式"
            "布局说明",              # 3组团分布
        ],
    }),

    # 第15条: 从2个维度取11个section
    15: ("农村住房建设", 3, "S-COPY", {
        "settlement_planning": [
            "宅基地规划表",          # 现状/新增/腾退 表
            "防灾减灾规划",          # 灾害避让
            "基础设施规划",          # 供水/排水
            "历史文化保护",          # 祠堂/古树
            "产业空间布局",          # 产业分布
            "实施时序",              # 时段/内容 表
        ],
        "landscape": [               # 第15条同时引入景观维度
            "村庄风貌指引",
            "整体风貌定位与景观格局",
            "建筑风貌控制导则",      # 客家风格/色彩/高度控制
            "核心景观节点设计指引",  # 古檀广场/古驿道/祠堂群
            "人居环境整治指引",      # 道路/环卫/绿化
        ],
    }),

    # 第13条: 从1个维度取9个section
    13: ("历史文化传承与保护", 3, "S-COPY", {
        "heritage": [
            "历史文化保护规划", "文化遗产清单", "保护范围划定",
            "建筑分类整治", "非物质文化遗产活化",
            "防灾减灾与安全", "产业融合利用",
            "基础设施配套", "人口与用地管控",
        ],
    }),

    # 第16条: 从3个维度取14个section (合并度最高)
    16: ("基础设施和公共服务设施建设", 3, "S-COPY", {
        "infrastructure_planning": [
            "基础设施规划", "给水工程", "排水工程",
            "电力工程", "通信工程", "环卫工程", "工程量汇总表",
        ],
        "public_service": [
            "公共服务设施规划", "配置原则与策略", "设施配置清单",
        ],
        "traffic_planning": [
            "道路交通规划", "路网格局", "道路等级规划", "交通设施清单",
        ],
    }),
}
```

### 3.2 匹配执行

```python
def _build_copy(self, num, title, chapter, sources):
    parts = []
    section_idx = 0

    for dim_key, section_patterns in sources.items():
        sections = self.data.layer3_sections.get(dim_key, {})
        # sections = {"绿地指标": "| 指标 | 现状 | 目标 |\n...", ...}

        for sec_title, sec_content in sections.items():
            # 精确匹配: pattern in title OR title in pattern
            matched = any(pat in sec_title or sec_title in pat
                         for pat in section_patterns)
            if not matched:
                continue

            section_idx += 1
            cleaned, next_tbl = self._add_table_numbers(
                sec_content, chapter, table_idx, sec_title
            )
            parts.append(f"（{section_idx}）{sec_title}\n{cleaned}")
```

**最终分配结果**（零重叠验证）：

```
第9条  ← land_use(3) + settlement(5) = 8 sections
第10条 ← spatial(4)                    = 4
第11条 ← ecological(6)                = 6
第12条 ← land_use(2)                  = 2
第13条 ← heritage(9)                  = 9
第14条 ← industry(6)                  = 6
第15条 ← settlement(6) + landscape(5) = 11
第16条 ← infra(7) + public(3) + traffic(4) = 14
第17条 ← disaster(5)                  = 5
第18条 ← project_bank(2)              = 2
────────────────────────────────────────
合计                                  = 67 sections
```

---

## 四、固定模板（S-TEMPLATE）

4条条文使用固定模板，内容与参考文档 `docs/平远县泗水镇金田村村庄规划（2022-2035年）文本.docx` 完全对齐：

### 第二条 规划原则

```python
templates[2] = (
    "（1）坚持以人为本，多元参与，尊重村民发展诉求，带动乡村共建共享；\n"
    "（2）坚持因地制宜，突出特色，务实发展特色产业，实现差异产业兴旺；\n"
    "（3）坚持经济可行，集约高效，统筹兼顾各类主体，协调高效使用资源；\n"
    "（4）坚持注重实用，通俗易懂，编制规划实用管用，制定乡约简洁易懂。"
)
```
来源: 参考文档第65-68段

### 第三条 规划任务

```python
templates[3] = (
    "统筹村庄发展目标、生态保护修复、耕地和永久基本农田保护、"
    "历史文化传承与保护、基础设施和基本公共服务设施布局、"
    "产业规划策略、农村住房布局、村庄安全和防灾减灾，"
    "明确规划近期实施项目。"
)
```
来源: 参考文档第70段

### 第四条 规划依据

三级结构：
- `（1）国家政策文件依据` → 10部: 土地管理法、城乡规划法、文物保护法...
- `（2）省、市（县）政策文件依据` → 7部: 广东省条例、梅州市方案...
- `（3）上层次规划依据` → 7部: 梅州市总规、平远县规划...

来源: 参考文档第73-100段

### 第六条 规划期限

```python
templates[6] = (
    "规划期限为2022-2035年，近期到2025年，规划基期年为2022年，"
    "与基本实现社会主义现代化期限保持一致。"
)
```
来源: 参考文档第106段

---

## 五、数据组装（S-ASSEMBLE）

### 第五条 规划范围

```python
def _asm_article5(self):
    area = d.total_area_ha or 2352.89    # land_use → regex
    names = d.village_names               # socio_economic → regex
    if names:
        return f"...总面积{area:.2f}公顷，包括{'、'.join(names)}等{len(names)}个自然村。"
```

**数据链路**:

```
land_use 报告:
  "土地总用地面积约 2352.89 公顷"
    → regex: r'土地总用地面积[约]*\s*([\d.]+)\s*公顷'
    → ExtractedData.total_area_ha = 2352.89

socio_economic 报告:
  "下辖园寨、田坑、社前、分水、清明、塘笃、长塘、
   炉池、肩丰、营仔、新山、黄竹共 12 个自然村"
    → regex: r'下辖(.+?)(?:共|等)?\d+\s*个自然村'
    → split(r'[、，,]')
    → clean: "黄竹共" → re.sub(r'[共等\s\d]+.*$', '') → "黄竹"
    → ExtractedData.village_names = [园寨, 田坑, ..., 黄竹]
```

### 第八条 规划指标

8个指标从 `ExtractedData` 字段动态填充：

```
户籍人口规模 → population_registered (1403，来自 socio_economic)
常住人口规模 → population_resident  (500，  来自 socio_economic)
耕地保有量   → farmland_ha          (85.20，来自 land_use)
永久基本农田 → farmland_ha          (85.20，与耕地对齐)
生态红线面积 → ecological_forest_ha (325.92，来自 land_use)
建设用地规模 → construction_land_ha (30.17，来自 land_use)
林地保有量   → commercial + ecological forest (2193.30)
森林覆盖率   → forest_coverage_pct  (90，   来自 land_use)
```

**两阶段提取防止数据覆盖**:

```python
# Phase1: 从 land_use 优先提取 total_area_ha
land_use = self.reports.get('land_use', '')
m = re.search(r'土地总用地面积[约]*\s*([\d.]+)\s*公顷', land_use)
# → 2352.89 (正确)

# Phase2: 从全部报告提取其余字段，跳过已提取
# 问题: "总面积" 在 settlement_planning 中匹配到建设用地面积30.17
# 解决: 跳过 Phase1 已提取的字段
if field == 'total_area_ha' and self.data.total_area_ha > 0:
    continue
```

---

## 六、表格处理

### 6.1 跨条文连续编号

```python
class SectionBuilder:
    def __init__(self):
        self._chapter_table_idx: dict = {}  # {3: 0, 4: 0}

    def _build_copy(self, num, title, chapter, sources):
        if chapter not in self._chapter_table_idx:
            self._chapter_table_idx[chapter] = 0  # 新章重置

        # ... 每个section中的表格递增 ...
        cleaned, next_tbl = self._add_table_numbers(
            sec_content, chapter,
            self._chapter_table_idx[chapter],  # 当前章累计值
            sec_title
        )
        self._chapter_table_idx[chapter] = next_tbl  # 更新累计
```

**第三章完整编号序列**:

```
第九条:  3-1, 3-2
第十条:  3-3, 3-4           ← 从上次继续
第十一条: 3-5, 3-6, 3-7, 3-8
第十二条: 3-9, 3-10
第十三条: 3-11 ~ 3-18
第十四条: 3-19, 3-20
第十五条: 3-21, 3-22, 3-23
第十六条: 3-24 ~ 3-27
第十七条: 3-28
第十八条: 4-1                ← 新章重置
```

### 6.2 表格标题生成

使用section标题作为表格名，而非列名拼接：

```python
# section_title = "绿地指标"
# 1个表格: "表 3-5 绿地指标"
# section_title = "绿地系统"
# 1个表格: "表 3-6 绿地系统"
# 含多个表格的section: "绿地指标(2)"
```

### 6.3 缺失分隔行自动修复

```python
def _add_table_numbers(self, text, chapter, start_idx, section_title):
    header_seen = False

    for line in lines:
        if stripped.startswith('|'):
            if _is_sep(stripped):
                header_seen = False         # 分隔行清除标志
            elif not in_table:
                header_seen = True          # 表头行
            elif header_seen:
                header_seen = False
                # 表头后直接跟数据 → 插入分隔行
                ncols = len([c for c in stripped.split('|') if c.strip()])
                sep = '| ' + ' | '.join([':---'] * ncols) + ' |'
                result.append(sep)
```

---

## 七、LLM生成（S-GENERATE）

### 上下文构建

```python
# 第7条: Layer2全量数据 (高度精炼，无需过滤)
context = f"规划定位:\n{planning_positioning[:500]}"
context += f"发展目标: {development_goal[:300]}"
context += f"资源禀赋: {resource_endowment[:300]}"

# 第19-22条: 仅村庄标识信息
context = f"项目: 金田村村庄规划(2022-2035年)"
context += f"常住人口: {population_resident}人"
```

### Few-shot来源

```python
# reference_parser.py
targets = {
    'positioning': 7,    # → 第7条参考格式
    'guarantee': 19,     # → 第19-21条参考格式
    'supervision': 22,   # → 第22条参考格式
}
# 每条截取前300字避免token浪费
```

---

## 八、DOCX构建

直接从 `BuildReport.articles` 结构化数据构建，不解析markdown：

- 标题: 黑体22pt居中
- 章标题: 黑体16pt
- 条文标题: 黑体14pt加粗
- 正文: 宋体12pt, 1.5倍行距
- 表格标题: 宋体10pt居中加粗
- 表格: Table Grid样式, 表头加粗居中, 数据10pt, autofit
- `（N）` 开头段落: 首行缩进0.74cm
- `**加粗**` → bold run
- 连续文本行合并为单个段落避免多余换行

---

## 九、文件清单与行数

```
scripts/experiments/planning_text/
├── __init__.py              (1行)
├── run_experiment.py        (100行)  主实验CLI
├── reference_parser.py      (127行)  参考文档解析
├── content_extractor.py     (198行)  数字/表格/段落提取
├── section_builder.py       (340行)  策略路由 + 条文组装 + 表格修复
├── llm_styler.py            (82行)   Tier3 LLM生成
├── docx_builder.py          (145行)  DOCX结构化构建
├── quality_checker.py       (56行)   填充率/结构检查
└── prompts/
    ├── __init__.py
    └── generation.py        (30行)   LLM prompt模板

总计: ~1080行
```
