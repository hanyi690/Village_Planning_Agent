/**
 * GIS Test API Client — 8 endpoints for development/testing
 *
 * 后端: backend/app/api/gis_test_routes.py
 * 前缀: /api/dev/gis
 */

import { apiRequest } from '@/features/planning/api/client';

const BASE = '/api/dev/gis';

// ============================================
// Types
// ============================================

export interface GisServiceStatus {
  tianditu: boolean;
  amap: boolean;
  spatial: boolean;
  osmnx?: boolean;
}

export interface TestResultBase {
  success: boolean;
  error?: string;
  timing_ms?: number;
}

export interface DataResult extends TestResultBase {
  data_summary?: Record<string, unknown>;
  center?: [number, number];
  bbox?: Record<string, unknown>;
  coverage?: Record<string, unknown>;
  gis_data?: Record<string, unknown>;
}

export interface AnalysisResult extends TestResultBase {
  isochrones?: unknown;
  accessibility?: unknown;
  pois?: unknown;
}

export interface ValidateResult extends TestResultBase {
  validation?: Record<string, unknown>;
  checks?: Array<{ name: string; passed: boolean; violation_count: number; violations: Array<{ check: string; severity: string; message: string }> }>;
  sensitivity?: Record<string, unknown>;
  conflicts?: { metric_conflicts: number; constraint_violations: number };
  hazard_count?: number;
  buffer_geojson?: unknown;
}

// Layout validation convenience types (used by ValidationPanel, GisResultCard, ProcessPanel)
export interface LayoutValidationViolation {
  check: string;
  severity: string;
  message: string;
}

export interface LayoutValidationCheck {
  name: string;
  passed: boolean;
  violation_count: number;
  violations: LayoutValidationViolation[];
}

export interface LayoutValidationDetail {
  status: 'pass' | 'fail' | 'warning';
  total_violations: number;
  warnings?: string[];
  violations?: LayoutValidationViolation[];
  [key: string]: unknown;
}

export interface LayoutValidationResult extends TestResultBase {
  validation?: Record<string, unknown>;
  checks?: LayoutValidationCheck[];
  zone_areas?: Record<string, number>;
}

export interface LayoutResult extends TestResultBase {
  gen?: Record<string, unknown>;
  plan?: Record<string, unknown>;
  comparison?: Record<string, unknown>;
  landuse_change?: Record<string, unknown>;
  validation_result?: Record<string, unknown>;
}

export interface IntentResult extends TestResultBase {
  intent?: Record<string, unknown>;
  source?: string;
}

export interface ZonesResult extends TestResultBase {
  zone_type?: string;
  geojson?: unknown;
  feature_count?: number;
  categories?: Record<string, unknown>;
  definitions?: Record<string, unknown>;
}

export interface JintianFile {
  filename: string;
  name: string;
  group: string;
  layer_type: string;
  records: number;
}

// ============================================
// API Client
// ============================================

export const gisTestApi = {
  /** 1. GET /api/dev/gis/status */
  async getStatus(): Promise<GisServiceStatus> {
    return apiRequest(`${BASE}/status`);
  },

  /** 2. POST /api/dev/gis/data */
  async fetchData(params: {
    location?: string;
    buffer_km?: number;
    include?: string[];
  }): Promise<DataResult> {
    return apiRequest(`${BASE}/data`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** 3. POST /api/dev/gis/analysis */
  async analyze(params: {
    analysis_type?: 'isochrone' | 'accessibility' | 'poi';
    center?: number[];
    time_minutes?: number[];
    travel_mode?: string;
    keyword?: string;
    radius?: number;
  }): Promise<AnalysisResult> {
    return apiRequest(`${BASE}/analysis`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** 4. POST /api/dev/gis/validate */
  async validate(params: {
    validation_type?: 'layout' | 'facility' | 'ecological' | 'constraint' | 'hazard';
    layout_configs?: unknown[];
    facility_type?: string;
    location?: number[];
    constraints?: Record<string, unknown>[];
    buffer_meters?: number;
    use_jintian_data?: boolean;
  }): Promise<ValidateResult> {
    return apiRequest(`${BASE}/validate`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** 5. POST /api/dev/gis/layout */
  async generateLayout(params: {
    village_name?: string;
    run_path?: 'gen' | 'plan' | 'both';
    intent?: Record<string, unknown>;
    compare_to_planned?: boolean;
    include_validation?: boolean;
    include_landuse_change?: boolean;
    use_llm?: boolean;
  }): Promise<LayoutResult> {
    return apiRequest(`${BASE}/layout`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** 6. POST /api/dev/gis/intent */
  async parseIntent(params: {
    village_name?: string;
    planning_text?: string;
    use_db_reports?: boolean;
    use_jintian_reports?: boolean;
  }): Promise<IntentResult> {
    return apiRequest(`${BASE}/intent`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** 7. POST /api/dev/gis/zones */
  async generateZones(params: {
    zone_type?: 'land_use' | 'space_control';
    village_name?: string;
  }): Promise<ZonesResult> {
    return apiRequest(`${BASE}/zones`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** 8. GET /api/dev/gis/files */
  async listFiles(): Promise<{ files: string[]; count: number }> {
    return apiRequest(`${BASE}/files`);
  },

  /** 8. GET /api/dev/gis/files/{path} */
  async getFile(filepath: string): Promise<unknown> {
    return apiRequest(`${BASE}/files/${filepath}`);
  },
};
