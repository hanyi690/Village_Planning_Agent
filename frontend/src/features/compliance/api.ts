import { apiRequest } from '@/features/planning/api/client';

export interface LandBalanceRow {
  land_use_name: string;
  land_use_code: string;
  planning_zone?: string | null;
  current_area_ha: number;
  current_ratio: number;
  planned_area_ha: number;
  planned_ratio: number;
  change_ha: number;
  change_pct: number;
}

export interface LandBalanceTable {
  rows: LandBalanceRow[];
  total_current_area_ha: number;
  total_planned_area_ha: number;
  closure_deviation_pct: number;
  is_closed: boolean;
  agriculture_current: number;
  agriculture_planned: number;
  construction_current: number;
  construction_planned: number;
  ecological_current: number;
  ecological_planned: number;
}

export interface DeliveryGate {
  passed: boolean;
  land_balance_closed: boolean;
  three_line_violations: number;
  protected_intrusions: number;
  changed_parcels_pct: number;
  changed_parcels_threshold: number;
  zones_complete: boolean;
  failures: string[];
  summary: string;
}

export interface ComplianceResult {
  session_id: string;
  project_name: string;
  analyzed_at: string;
  land_balance: LandBalanceTable;
  delivery_gate: DeliveryGate;
  diagnostics: {
    village_name: string;
    data_source: string;
    current_parcel_count: number;
    planned_parcel_count: number;
    layer_completeness?: LayerCompleteness;
    warnings: string[];
  };
}

export interface LayerStatusItem {
  layer_key: string;
  label: string;
  tier: string;
  present: boolean;
  feature_count: number;
  source: string;
}

export interface LayerCompleteness {
  score_pct: number;
  critical_missing: string[];
  recommended_missing: string[];
  layers: LayerStatusItem[];
  summary: string;
}

export const complianceApi = {
  run: (sessionId: string) =>
    apiRequest<{ session_id: string; status: string; message: string; result?: ComplianceResult }>(
      `/api/compliance/sessions/${sessionId}/run`,
      { method: 'POST' },
    ),
  getResults: (sessionId: string) =>
    apiRequest<ComplianceResult>(`/api/compliance/sessions/${sessionId}/results`),
  getStatus: (sessionId: string) =>
    apiRequest<{ session_id: string; has_result: boolean; analyzed_at?: string; gate_passed?: boolean }>(
      `/api/compliance/sessions/${sessionId}/status`,
    ),
};
