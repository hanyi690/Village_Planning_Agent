/**
 * 后端真实 artifact key 集合。
 *
 * 与 `backend/app/infrastructure/artifacts/runtime.py` 的 ARTIFACT_KEYS 保持一致，
 * 作为前端"中间产物"面板的显示清单。新增/删除 artifact 时必须同步两端。
 */
export const ARTIFACT_KEYS = [
  'l1_snapshot',
  'l2_strategy',
  'planning_program',
  'target_projection',
  'grounding_result',
  'demand_portfolio',
  'suitability_surface',
  'portfolio_decision',
  'site_selection',
  'execution_plan',
  'execution_result',
  'parcel_changeset',
  'planned_state',
  'validation_report',
  'reconciliation_report',
  'delivery_manifest',
  'layout_configs',
  'render_layers',
  'delivery_spatial_snapshot',
  'deferral_ledger',
  'export_result',
  'render_artifacts',
  'execution_diagnostics',
  'kg_layer1',
] as const;

export type ArtifactKey = (typeof ARTIFACT_KEYS)[number];