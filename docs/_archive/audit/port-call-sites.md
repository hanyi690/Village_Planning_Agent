# Port Call-Site Audit (P3-7)

Defines minimal Protocol ports from the *actual* call sites in `app/modules`,
not from guessed interfaces. Every method listed below is exercised by real
module code.

## ReportStore usage from modules

The concrete `ReportStore` singleton is reached from modules through
`ReportStore.get_instance()`. The following reader methods are actually called:

| File | Line | Method | Args | Used type |
|------|------|--------|------|-----------|
| `app/modules/planning_text/generator.py` | 68,69,70 | `get_layer_reports` | `session_id, layer` | `Dict[str, str]` |
| `app/modules/planning_text/generator.py` | 81,82,83,144,145,146 | `get_layer_summaries` | `session_id, layer` | `Dict[str, Dict[str, Any]]` |
| `app/modules/planning_text/generator.py` | 200 | `get_layer_reports` | `session_id, layer` | `Dict[str, str]` |
| `app/modules/planning_text/generator.py` | 230,279 | `get_layer_reports_with_sources` | `session_id, layer` | `Dict[str, Dict[str, Any]]` |
| `app/modules/planning_text/rag_appender.py` | 36 | `get_layer_reports_with_sources` | `session_id, layer` | `Dict[str, Dict[str, Any]]` |
| `app/modules/planning_text/layer_exporter.py` | 103,169 | `get_layer_reports` | `session_id, layer` | `Dict[str, str]` |
| `app/modules/planning_text/layer_exporter.py` | 114,179 | `get_layer_summaries` | `session_id, layer` | `Dict[str, Dict[str, Any]]` |
| `app/modules/planning_text/layer_exporter.py` | 227 | `get_layer_reports_with_sources` | `session_id, layer` | `Dict[str, Dict[str, Any]]` |
| `app/modules/rag/service.py` | 245,246,247 | `get_layer_reports` | `session_id, layer` | `Dict[str, str]` |
| `app/modules/rag/service.py` | 250,251,252 | `get_layer_summaries` | `session_id, layer` | `Dict[str, Dict[str, Any]]` |

No module calls any *writer* method (`save`, `bulk_save`, `update_summary`).
Report writing is confined to the services/agent layer. Therefore the writer
port is declared defensively with the save signature for future use, but no
current module call site requires it.

## get_cached_context usage from kg enrichment

| File | Line | Call | Purpose |
|------|------|------|---------|
| `app/modules/kg/enrichment/report_entity_enrichment.py` | 548,550 | `get_cached_context(session_id)` | Mutates `cached_context.gazetteer` and `cached_context.ports.gazetteer` after GIS binding |

Only the *read* of the cached context is needed by the module. The enrichment
code does not build a context; it only retrieves the frozen in-process context
to update its in-memory gazetteer.

## Reverse imports to eliminate (`modules -> services`)

| File | Import |
|------|--------|
| `app/modules/planning_text/generator.py` | `from app.services.report_store import ReportStore` |
| `app/modules/planning_text/rag_appender.py` | `from app.services.report_store import ReportStore` |
| `app/modules/planning_text/layer_exporter.py` | `from app.services.report_store import ReportStore` |
| `app/modules/rag/service.py` | `from app.services.report_store import ReportStore` |
| `app/modules/kg/enrichment/report_entity_enrichment.py` | `from app.services.context.planning_context import get_cached_context` |

## Ports defined

- `app/modules/ports/report_reader.py` -> `ReportReaderPort`
- `app/modules/ports/report_writer.py` -> `ReportWriterPort`
- `app/modules/ports/context_reader.py` -> `ContextReaderPort`

These are the ONLY methods observed at real call sites. They are injected into
modules by the composition root (`app/services/composition.py`).

## Residuals

None. All five `modules -> services` reverse imports were eliminated. Modules
now depend either on the Port Protocols (`report_reader.py`,
`report_writer.py`, `context_reader.py`) or on the neutral registry
(`app/modules/ports/registry.py`) that the composition root populates at boot.
The composition root (`app/services/composition.py`) owns the concrete
singletons and registers them into the registry; modules never import
`app.services` directly.