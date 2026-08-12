import { apiRequest } from '@/features/planning/api/client';

export interface SuitabilityZoneSummary {
  zone: string;
  parcel_count: number;
  area_ha: number;
  ecological_avg: number;
  agricultural_avg: number;
  construction_avg: number;
  dominant_class: string;
}

export interface SuitabilityResult {
  session_id: string;
  project_name: string;
  analyzed_at: string;
  area_summary: Record<string, number>;
  zone_summaries: SuitabilityZoneSummary[];
  sample_parcels: Array<{
    bsm: string;
    dlbm: string;
    area_ha: number;
    planning_zone: string;
    ecological: number;
    agricultural: number;
    construction: number;
    hazard_near: boolean;
    in_farmland_protection: boolean;
    in_ecological_protection: boolean;
  }>;
  diagnostics: {
    village_name: string;
    data_source: string;
    parcel_count: number;
    hazard_point_count: number;
    calibration_profile?: string;
    calibration_params?: Record<string, number>;
    layer_completeness?: {
      score_pct: number;
      critical_missing: string[];
      recommended_missing: string[];
      layers: Array<{
        layer_key: string;
        label: string;
        tier: string;
        present: boolean;
        feature_count: number;
        source: string;
      }>;
      summary: string;
    };
    warnings: string[];
  };
}

export const suitabilityApi = {
  run: (sessionId: string) =>
    apiRequest<{ session_id: string; status: string; message: string; result?: SuitabilityResult }>(
      `/api/suitability/sessions/${sessionId}/run`,
      { method: 'POST' },
    ),
  getResults: (sessionId: string) =>
    apiRequest<SuitabilityResult>(`/api/suitability/sessions/${sessionId}/results`),
  getStatus: (sessionId: string) =>
    apiRequest<{ session_id: string; has_result: boolean; analyzed_at?: string }>(
      `/api/suitability/sessions/${sessionId}/status`,
    ),
};
