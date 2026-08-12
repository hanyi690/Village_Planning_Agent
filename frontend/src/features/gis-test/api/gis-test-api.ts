/**
 * GIS Test API Client - 开发环境专用的 GIS 端到端测试 API
 *
 * 对应后端 backend/app/api/gis_test_routes.py（合并后的 /data /analysis /validate /layout）
 * 所有端点前缀: /api/dev/gis
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

export interface DataFetchResult extends TestResultBase {
  data?: Record<string, unknown>;
  data_summary?: Record<string, unknown>;
  gis_data?: Record<string, unknown>;
  coverage?: Record<string, unknown>;
}

export interface CenterResult extends TestResultBase {
  center?: [number, number];
  metadata?: Record<string, unknown>;
}

export interface IsochroneResult extends TestResultBase {
  geojson?: unknown;
  isochrones?: unknown[];
}

export interface AccessibilityResult extends TestResultBase {
  data?: Record<string, unknown>;
  accessibility?: Record<string, unknown>;
}

export interface POISearchResult extends TestResultBase {
  pois?: unknown;
}

export interface CoverageResult extends TestResultBase {
  location?: string;
  coverage_rate?: number;
  coverage?: Record<string, unknown>;
}

export interface FacilityValidationResult extends TestResultBase {
  overall_score?: number;
  suitability_level?: string;
  checks?: unknown[];
  recommendations?: string[];
}

export interface EcologicalResult extends TestResultBase {
  study_area_km2?: number;
  sensitivity_class?: string;
}

export interface SpatialLayoutResult extends TestResultBase {
  layout_configs?: unknown[];
  conflicts?: { metric_conflicts: number; constraint_violations: number };
}

export interface LanduseChangeResult extends TestResultBase {
  current_parcels?: number;
  planned_parcels?: number;
  geojson?: { current: unknown; planned: unknown };
  landuse_change?: Record<string, unknown>;
}

export interface ConstraintValidatorResult extends TestResultBase {
  metric_conflicts?: number;
  constraint_violations?: number;
  is_valid?: boolean;
}

export interface HazardBufferResult extends TestResultBase {
  hazard_count?: number;
  buffer_meters?: number;
  geojson?: unknown;
}

export interface LayoutValidationViolation {
  check: string;
  severity: 'error' | 'warning';
  message: string;
  details?: Record<string, unknown>;
}

export interface LayoutValidationCheck {
  name: string;
  passed: boolean;
  violation_count: number;
  violations: LayoutValidationViolation[];
}

export interface LayoutValidationResult extends TestResultBase {
  validation?: {
    passed: boolean;
    status: 'pass' | 'fail' | 'warning';
    total_violations: number;
    violations: LayoutValidationViolation[];
    warnings: string[];
  };
  checks?: LayoutValidationCheck[];
  zone_areas?: Record<string, number>;
}

export interface JintianFile {
  filename: string;
  name: string;
  group: 'status' | 'planned' | 'protection';
  layer_type: GISLayerConfigLayerType;
  records: number;
}

type GISLayerConfigLayerType =
  | 'boundary'
  | 'function_zone'
  | 'infrastructure'
  | 'facility_point'
  | 'hazard_point'
  | 'planning_zone';

function inferJintianFileGroup(filename: string): JintianFile['group'] {
  const normalized = filename.replace(/\\/g, '/').toLowerCase();
  if (normalized.includes('/planned/') || normalized.startsWith('planned/')) return 'planned';
  if (
    normalized.includes('protection')
    || normalized.includes('farmland')
    || normalized.includes('ecological')
    || normalized.includes('historical')
    || normalized.includes('hazard')
  ) {
    return 'protection';
  }
  return 'status';
}

function inferJintianLayerType(filename: string): GISLayerConfigLayerType {
  const base = filename.split('/').pop()?.toLowerCase() ?? '';
  if (base.includes('boundary')) return 'boundary';
  if (base.includes('road')) return 'infrastructure';
  if (base.includes('facility') || base.includes('poi')) return 'facility_point';
  if (base.includes('hazard')) return 'hazard_point';
  if (base.includes('landuse') || base.includes('zone')) return 'function_zone';
  return 'planning_zone';
}

function humanizeFilename(filename: string): string {
  const base = filename.split('/').pop()?.replace(/\.geojson$/i, '') ?? filename;
  return base.replace(/[_-]+/g, ' ');
}

function toJintianFile(filename: string): JintianFile {
  return {
    filename,
    name: humanizeFilename(filename),
    group: inferJintianFileGroup(filename),
    layer_type: inferJintianLayerType(filename),
    records: 0,
  };
}

// ============================================
// API Client
// ============================================

export const gisTestApi = {
  /** GET /api/dev/gis/status */
  async getStatus(): Promise<GisServiceStatus> {
    return apiRequest(`${BASE}/status`);
  },

  /** POST /api/dev/gis/data */
  async fetchData(params: {
    location?: string;
    buffer_km?: number;
    max_features?: number;
  }): Promise<DataFetchResult> {
    return apiRequest(`${BASE}/data`, {
      method: 'POST',
      body: JSON.stringify({
        location: params.location ?? '金田村委会',
        buffer_km: params.buffer_km ?? 5,
        include: ['data', 'coverage', 'center', 'bbox'],
      }),
    });
  },

  /** POST /api/dev/gis/data (center only) */
  async getCenter(params: {
    location?: string;
    buffer_km?: number;
  }): Promise<CenterResult> {
    const result = await apiRequest<DataFetchResult & CenterResult>(`${BASE}/data`, {
      method: 'POST',
      body: JSON.stringify({
        location: params.location ?? '金田村委会',
        buffer_km: params.buffer_km ?? 5,
        include: ['center'],
      }),
    });
    return {
      success: result.success,
      error: result.error,
      timing_ms: result.timing_ms,
      center: result.center,
      metadata: result.data_summary,
    };
  },

  /** POST /api/dev/gis/data (bbox only) */
  async getBBox(params: {
    location?: string;
    buffer_km?: number;
  }): Promise<TestResultBase & { bbox?: unknown }> {
    return apiRequest(`${BASE}/data`, {
      method: 'POST',
      body: JSON.stringify({
        location: params.location ?? '金田村委会',
        buffer_km: params.buffer_km ?? 5,
        include: ['bbox'],
      }),
    });
  },

  /** POST /api/dev/gis/analysis (isochrone) */
  async generateIsochrones(params: {
    center?: number[];
    time_minutes?: number[];
    travel_mode?: string;
  }): Promise<IsochroneResult> {
    return apiRequest(`${BASE}/analysis`, {
      method: 'POST',
      body: JSON.stringify({
        analysis_type: 'isochrone',
        center: params.center ?? [116.044146, 24.818629],
        time_minutes: params.time_minutes ?? [5, 10, 15],
        travel_mode: params.travel_mode ?? 'walk',
      }),
    });
  },

  /** POST /api/dev/gis/analysis (accessibility) */
  async analyzeAccessibility(params: {
    analysis_type?: string;
    origin?: number[];
    center?: number[];
  }): Promise<AccessibilityResult> {
    return apiRequest(`${BASE}/analysis`, {
      method: 'POST',
      body: JSON.stringify({
        analysis_type: 'accessibility',
        center: params.center ?? params.origin ?? [116.044146, 24.818629],
      }),
    });
  },

  /** POST /api/dev/gis/analysis (poi) */
  async searchPOI(params: {
    keyword?: string;
    center?: number[];
    radius?: number;
  }): Promise<POISearchResult> {
    return apiRequest(`${BASE}/analysis`, {
      method: 'POST',
      body: JSON.stringify({
        analysis_type: 'poi',
        keyword: params.keyword ?? '学校',
        center: params.center ?? [116.044146, 24.818629],
        radius: params.radius ?? 2000,
      }),
    });
  },

  /** POST /api/dev/gis/data (coverage) */
  async calculateCoverage(params: {
    location?: string;
    buffer_km?: number;
  }): Promise<CoverageResult> {
    const result = await apiRequest<DataFetchResult & CoverageResult>(`${BASE}/data`, {
      method: 'POST',
      body: JSON.stringify({
        location: params.location ?? '金田村委会',
        buffer_km: params.buffer_km ?? 5,
        include: ['coverage'],
      }),
    });
    return {
      ...result,
      coverage_rate: typeof result.coverage?.coverage_rate === 'number'
        ? result.coverage.coverage_rate
        : undefined,
    };
  },

  /** POST /api/dev/gis/validate (facility) */
  async validateFacility(params: {
    facility_type?: string;
    location?: number[];
  }): Promise<FacilityValidationResult> {
    return apiRequest(`${BASE}/validate`, {
      method: 'POST',
      body: JSON.stringify({
        validation_type: 'facility',
        facility_type: params.facility_type ?? '公共服务设施',
        location: params.location ?? [116.044146, 24.818629],
      }),
    });
  },

  /** POST /api/dev/gis/validate (ecological) */
  async assessEcological(params: {
    use_jintian_data?: boolean;
  }): Promise<EcologicalResult> {
    return apiRequest(`${BASE}/validate`, {
      method: 'POST',
      body: JSON.stringify({
        validation_type: 'ecological',
        use_jintian_data: params.use_jintian_data ?? true,
      }),
    });
  },

  /** POST /api/dev/gis/layout */
  async generateSpatialLayout(params: {
    village_name?: string;
  }): Promise<SpatialLayoutResult> {
    return apiRequest(`${BASE}/layout`, {
      method: 'POST',
      body: JSON.stringify({
        village_name: params.village_name ?? '金田村委会',
        run_path: 'gen',
        include_validation: true,
      }),
    });
  },

  /** POST /api/dev/gis/layout (landuse change) */
  async analyzeLanduseChange(params: {
    location?: string;
    buffer_km?: number;
  }): Promise<LanduseChangeResult> {
    return apiRequest(`${BASE}/layout`, {
      method: 'POST',
      body: JSON.stringify({
        village_name: params.location ?? '金田村委会',
        include_landuse_change: true,
      }),
    });
  },

  /** POST /api/dev/gis/validate (constraint) */
  async validateConstraints(_params: {
    location?: string;
    strict_mode?: boolean;
  }): Promise<ConstraintValidatorResult> {
    return apiRequest(`${BASE}/validate`, {
      method: 'POST',
      body: JSON.stringify({
        validation_type: 'constraint',
        use_jintian_data: true,
      }),
    });
  },

  /** POST /api/dev/gis/validate (hazard) */
  async generateHazardBuffer(params: {
    location?: string;
    buffer_meters?: number;
  }): Promise<HazardBufferResult> {
    return apiRequest(`${BASE}/validate`, {
      method: 'POST',
      body: JSON.stringify({
        validation_type: 'hazard',
        buffer_meters: params.buffer_meters ?? 200,
        use_jintian_data: true,
      }),
    });
  },

  /** POST /api/dev/gis/validate (layout) */
  async validateLayout(params: {
    layout_configs?: unknown[];
    constraints?: Record<string, unknown>[];
    use_jintian_data?: boolean;
  }): Promise<LayoutValidationResult> {
    return apiRequest(`${BASE}/validate`, {
      method: 'POST',
      body: JSON.stringify({
        validation_type: 'layout',
        layout_configs: params.layout_configs ?? [],
        constraints: params.constraints,
        use_jintian_data: params.use_jintian_data ?? true,
      }),
    });
  },

  /** GET /api/dev/gis/files */
  async listJintianFiles(): Promise<{ success: boolean; files: JintianFile[] }> {
    const result = await apiRequest<{ files?: string[]; count?: number }>(`${BASE}/files`);
    const files = (result.files ?? []).map(toJintianFile);
    return { success: true, files };
  },

  /** GET /api/dev/gis/files/{filepath} */
  async getJintianData(filename: string): Promise<{ success: boolean; geojson?: unknown; error?: string }> {
    try {
      const geojson = await apiRequest<unknown>(`${BASE}/files/${encodeURIComponent(filename)}`);
      if (geojson && typeof geojson === 'object' && 'error' in geojson) {
        return { success: false, error: String((geojson as { error?: string }).error) };
      }
      return { success: true, geojson };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Failed to load GeoJSON',
      };
    }
  },
};
