# schema/encodings - Encoding Systems & Mapping Tables

> **Purpose**: Centralizes all land-use classification code sets (DLBM/GHYTBM/TUGUI/VNE/...), cross-system mapping tables, and the candidate proposal engine. Single runtime source for all encoding lookups.
> **Updated: 2026-07-28 (v4.8.1)**

---

## Key files

| File | Role |
| --- | --- |
| `classification.py` | `LandUseClass` dataclass + `ClassificationSchema` snapshot + `EncodingRegistry` (central lookup) |
| `code_sets.py` | Module-level dicts derived from YAML: `DLBM_TO_ZONE_TYPE`, `DLBM_TO_PLANNING_ZONE`, `GHYTBM_TO_VNE`, lookup functions (`is_basic_farmland`, `get_zone_type_for_dlbm`, `normalize_landuse`, ...) |
| `dicts/loader.py` | `CodeDictionary`, `MappingTable`, `DictionaryCenter`, `get_center()` - loads all YAML |
| `dicts/candidate_engine.py` | `CandidateEngine` + `ClassificationProposal` + `Resolution` - proposes classification candidates, never auto-decides |
| `dicts/disambiguation.py` | `DisambiguationContext` - LLM disambiguation when multiple candidates survive |
| `dicts/expr_eval.py` | `Condition` / `MappingContext` - evaluates YAML rule conditions |
| `dicts/rule_loader.py` | Loads rule YAMLs (planning_zone_rules, allowed_operations, ...) |

## YAML data directories

```
dicts/
├── encodings/        # 6 standard code systems (verbatim from standards)
│   ├── appendix5.yaml      # 广东省村庄规划用地分类 (GHYTBM)
│   ├── gbt21010.yaml       # GB/T 21010-2017 土地利用现状分类
│   ├── tugui.yaml          # 广东省县级土规数据库标准
│   ├── ghflbm.yaml         # 土规规划分类编码
│   ├── ydyhfldm.yaml       # 自然资发〔2023〕234号 用地用海分类
│   └── vne.yaml            # 住建部 V/N/E 村庄规划用地分类
├── mappings/         # Cross-system mapping tables (1:N schema)
│   ├── dlbm_to_ghytbm.yaml
│   ├── ghflbm_to_tdytfqdm.yaml
│   └── sddlbm_to_ydyhfldm.yaml
├── rules/            # Engineering rules (derived config)
│   ├── planning_zone_rules.yaml
│   ├── construction_zone_codes.yaml
│   ├── allowed_operations.yaml
│   ├── field_defaults.yaml
│   ├── ghytbm_to_planning_zone.yaml
│   └── ...
└── references/       # Reference data
```

## Public API

```python
from app.data.encodings import (
    # Code sets (module-level dicts)
    DLBM_TO_ZONE_TYPE, DLBM_TO_PLANNING_ZONE, DLBM_TO_PRIMARY_ZONE,
    GHYTBM_TO_GHYTMC, GHYTBM_TO_VNE, VNE_CODE_TO_NAME,
    BASIC_FARMLAND_CODES, ECOLOGICAL_CODES, FOREST_CODES, WATER_CODES,
    SPACE_CONTROL_ZONE_CODES, PLANNING_ZONE_TO_PRIMARY_ZONE,
    # Lookup functions
    is_basic_farmland, get_zone_type_for_dlbm, get_primary_zone,
    dlbm_to_planning_zone, normalize_landuse, get_planning_zone_from_landuse,
    get_ghytbm_for_dlbm, get_tdytfqdm_for_ghflbm,
    # Registry / schema
    EncodingRegistry, get_encoding_registry,
    ClassificationSchema, get_schema,
    # Dictionary center
    DictionaryCenter, get_center,
)
```

## Decision ladder (CandidateEngine)

The `CandidateEngine` replaces the old "resolve_mapping" concept. It proposes candidates but never auto-decides:

| Level | Condition | Result |
| --- | --- | --- |
| L0 | Single target in mapping | `auto` |
| L1 | `Condition.evaluate()` uniquely hits | `rule_based` |
| L2 | Multiple survivors, LLM resolves | `llm` |
| L3 | `decision: manual` in YAML | `manual` (all candidates returned) |

## Dependencies

- `pydantic` (for `ClassificationProposal`, `Resolution`)
- `yaml`
- Standard library
- **Zero** deps on `data`, `kg`, `agent`, `tools`

## How to extend

- **New encoding system**: add YAML to `dicts/encodings/`, add loader call in `code_sets.py`
- **New cross-system mapping**: add YAML to `dicts/mappings/` (1:N schema with `Condition` rules), consume via `get_center().get_mapping()`
- **New derived rule**: add YAML to `dicts/rules/`, load in `code_sets.py` or `rule_loader.py`
- See `dicts/loader.py` docstring for the YAML schema conventions
