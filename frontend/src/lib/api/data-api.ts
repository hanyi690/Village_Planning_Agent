// ============================================
// Data API - 数据访问 API
// ============================================

import { apiRequest } from './client';
import type {
  VillageInfo,
  VillageSession,
  LayerContent,
  Checkpoint,
} from './types';

// ============================================
// Data API
// ============================================

export const dataApi = {
  /**
   * List all villages
   * GET /api/data/villages
   */
  async listVillages(): Promise<VillageInfo[]> {
    const response = await apiRequest<{ villages: VillageInfo[] }>('/api/data/villages');
    return response.villages || [];
  },

  /**
   * Get sessions for a village
   * GET /api/data/villages/{name}/sessions
   */
  async getVillageSessions(villageName: string): Promise<VillageSession[]> {
    return apiRequest<VillageSession[]>(
      `/api/data/villages/${encodeURIComponent(villageName)}/sessions`
    );
  },

  /**
   * Get layer content
   * GET /api/data/villages/{name}/layers/{layer}
   */
  async getLayerContent(
    villageName: string,
    layerId: string,
    session?: string,
    format: 'markdown' | 'html' | 'json' = 'markdown'
  ): Promise<LayerContent> {
    const params = new URLSearchParams({ format });
    if (session) params.append('session', session);

    return apiRequest<LayerContent>(
      `/api/data/villages/${encodeURIComponent(villageName)}/layers/${layerId}?${params}`
    );
  },

  /**
   * Get checkpoints for a village
   * GET /api/data/villages/{name}/checkpoints
   */
  async getCheckpoints(
    villageName: string,
    session?: string
  ): Promise<{ checkpoints: Checkpoint[]; count: number; project_name: string; session?: string }> {
    const params = new URLSearchParams();
    if (session) params.append('session', session);

    const query = params.toString() ? `?${params}` : '';
    return apiRequest<{ checkpoints: Checkpoint[]; count: number; project_name: string; session?: string }>(
      `/api/data/villages/${encodeURIComponent(villageName)}/checkpoints${query}`
    );
  },

  /**
   * Compare two checkpoints
   * GET /api/data/villages/{name}/compare/{cp1}/{cp2}
   */
  async compareCheckpoints(
    villageName: string,
    cp1: string,
    cp2: string
  ): Promise<{ diff: string; summary: string }> {
    return apiRequest(
      `/api/data/villages/${encodeURIComponent(villageName)}/compare/${cp1}/${cp2}`
    );
  },

  /**
   * Get combined plan
   * GET /api/data/villages/{name}/plan
   */
  async getCombinedPlan(
    villageName: string,
    session?: string,
    format: 'markdown' | 'html' | 'pdf' = 'markdown'
  ): Promise<{ content: string }> {
    const params = new URLSearchParams({ format });
    if (session) params.append('session', session);

    return apiRequest(
      `/api/data/villages/${encodeURIComponent(villageName)}/plan?${params}`
    );
  },

  /**
   * Test spatial layout generation
   * POST /api/gis/test/spatial-layout
   */
  async testSpatialLayout(
    villageName?: string,
    planningScheme?: Record<string, unknown>
  ): Promise<{
    success: boolean;
    geojson?: any;
    zones_geojson?: any;
    facilities_geojson?: any;
    axes_geojson?: any;
    statistics?: any;
    center?: [number, number];
    error?: string;
  }> {
    return apiRequest('/api/dev/gis/test/spatial-layout', {
      method: 'POST',
      body: JSON.stringify({
        village_name: villageName || '金田村委会',
        planning_scheme: planningScheme,
        use_real_data: true,
      }),
    });
  },

  /**
   * Test boundary fallback mechanism
   * POST /api/gis/test/boundary-fallback
   */
  async testBoundaryFallback(
    villageName?: string,
    options?: {
      skip_user_upload?: boolean;
      force_bbox?: boolean;
    }
  ): Promise<{
    success: boolean;
    geojson?: any;
    strategy_used?: string;
    fallback_history?: Array<{
      strategy: string;
      success: boolean;
      reason: string;
      stats?: any;
    }>;
    warnings?: string[];
    stats?: any;
    error?: string;
  }> {
    return apiRequest('/api/dev/gis/test/boundary-fallback', {
      method: 'POST',
      body: JSON.stringify({
        village_name: villageName || '测试村庄',
        skip_user_upload: options?.skip_user_upload ?? true,
        force_bbox: options?.force_bbox ?? false,
      }),
    });
  },

  // ============================================
  // Jintian Data API
  // ============================================

  /**
   * Get Jintian village metadata
   * GET /api/jintian/metadata
   */
  async getJintianMetadata(): Promise<{
    success: boolean;
    data: {
      village: { name: string; code: string; area_km2: number };
      coordinate_system: string;
      files: Record<string, any>;
    };
    village_name: string;
    area_km2: number;
  }> {
    return apiRequest('/api/jintian/metadata');
  },

  /**
   * Get Jintian GeoJSON data file
   * GET /api/jintian/data/{filename}
   */
  async getJintianData(filename: string): Promise<{
    success: boolean;
    filename: string;
    feature_count: number;
    geometry_types: string[];
    geojson: any;
  }> {
    return apiRequest(`/api/jintian/data/${filename}`);
  },

  /**
   * List all Jintian data files
   * GET /api/jintian/files
   */
  async listJintianFiles(): Promise<{
    success: boolean;
    total_files: number;
    files: Array<{
      filename: string;
      source_gdb: string;
      source_layer: string;
      records: number;
      geometry_type: string;
    }>;
  }> {
    return apiRequest('/api/jintian/files');
  },

  /**
   * Get report content for a layer
   * GET /api/jintian/report/{layer}
   */
  async getReportData(layer: number): Promise<{
    success: boolean;
    layer: number;
    content: string;
    word_count: number;
  }> {
    return apiRequest(`/api/jintian/report/${layer}`);
  },

  /**
   * Get planning facilities from report
   * GET /api/jintian/planning/facilities
   */
  async getPlanningFacilities(): Promise<{
    success: boolean;
    total: number;
    facilities: Array<{
      name: string;
      content: string;
      scale: string;
      location: string;
      function: string;
    }>;
  }> {
    return apiRequest('/api/jintian/planning/facilities');
  },

  /**
   * Get planning zones from report
   * GET /api/jintian/planning/zones
   */
  async getPlanningZones(): Promise<{
    success: boolean;
    total: number;
    zones: Array<{
      zone_id: string;
      name: string;
      type: string;
      description: string;
      location_hint: string;
      area_ratio: number;
    }>;
    structure: string;
  }> {
    return apiRequest('/api/jintian/planning/zones');
  },

  // ============================================
  // GIS Tool Test API
  // ============================================

  /**
   * Test isochrone analysis
   * POST /api/dev/gis/test/isochrone
   */
  async testIsochrone(params: {
    center?: [number, number];
    time_minutes?: number[];
    travel_mode?: 'walk' | 'drive';
  }): Promise<{
    success: boolean;
    geojson?: any;
    center?: [number, number];
    travel_mode?: string;
    error?: string;
  }> {
    return apiRequest('/api/dev/gis/test/isochrone', {
      method: 'POST',
      body: JSON.stringify({
        center: params.center || [116.044146, 24.818629],
        time_minutes: params.time_minutes || [5, 10, 15],
        travel_mode: params.travel_mode || 'walk',
      }),
    });
  },

  /**
   * Test accessibility analysis
   * POST /api/dev/gis/test/accessibility
   */
  async testAccessibility(params: {
    origin?: [number, number];
    destinations?: Array<[number, number]>;
    analysis_type?: string;
  }): Promise<{
    success: boolean;
    coverage_rate?: number;
    reachable_count?: number;
    geojson?: any;
    summary?: any;
    error?: string;
  }> {
    return apiRequest('/api/dev/gis/test/accessibility', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /**
   * Test POI search
   * POST /api/dev/gis/test/poi-search
   */
  async testPOISearch(params: {
    keyword: string;
    region?: string;
    center?: [number, number];
    radius?: number;
  }): Promise<{
    success: boolean;
    pois?: Array<any>;
    total_count?: number;
    geojson?: any;
    source?: string;
    error?: string;
  }> {
    return apiRequest('/api/dev/gis/test/poi-search', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /**
   * Test GIS coverage calculation
   * POST /api/dev/gis/test/gis-coverage
   */
  async testGISCoverage(params: {
    location: string;
    buffer_km?: number;
  }): Promise<{
    success: boolean;
    location?: string;
    coverage_rate?: number;
    layers_available?: Record<string, boolean>;
    feature_counts?: Record<string, number>;
    layers?: Array<any>;
    data_sources?: Record<string, string>;
    error?: string;
  }> {
    return apiRequest('/api/dev/gis/test/gis-coverage', {
      method: 'POST',
      body: JSON.stringify({
        location: params.location,
        buffer_km: params.buffer_km || 5.0,
      }),
    });
  },

  /**
   * Test ecological sensitivity analysis
   * POST /api/dev/gis/test/ecological
   */
  async testEcological(params: {
    study_area?: any;
    use_jintian_data?: boolean;
  }): Promise<{
    success: boolean;
    study_area_km2?: number;
    sensitive_area_km2?: number;
    sensitivity_class?: string;
    sensitivity_zones?: Array<any>;
    recommendations?: Array<string>;
    geojson?: any;
    error?: string;
  }> {
    return apiRequest('/api/dev/gis/test/ecological', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /**
   * Test facility location validation
   * POST /api/dev/gis/test/facility
   */
  async testFacility(params: {
    facility_type: string;
    location: [number, number];
  }): Promise<{
    success: boolean;
    overall_score?: number;
    suitability_level?: string;
    recommendations?: Array<string>;
    error?: string;
  }> {
    return apiRequest('/api/dev/gis/test/facility', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /**
   * Test planning vectorizer
   * POST /api/dev/gis/test/vectorizer
   */
  async testVectorizer(params: {
    zones?: Array<any>;
    facilities?: Array<any>;
    use_report_data?: boolean;
  }): Promise<{
    success: boolean;
    zones_geojson?: any;
    facilities_geojson?: any;
    error?: string;
  }> {
    return apiRequest('/api/dev/gis/test/vectorizer', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  // ============================================
  // 新增工具测试 API
  // ============================================

  /**
   * Test landuse change analysis
   * POST /api/dev/gis/test/landuse-change
   */
  async testLanduseChange(params: {
    use_jintian_data?: boolean;
    change_threshold?: number;
  }): Promise<{
    success: boolean;
    change_statistics?: Record<string, any>;
    total_current_area_km2?: number;
    total_planned_area_km2?: number;
    total_area_change_km2?: number;
    increase_types?: string[];
    decrease_types?: string[];
    error?: string;
  }> {
    return apiRequest('/api/dev/gis/test/landuse-change', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /**
   * Test constraint validator
   * POST /api/dev/gis/test/constraint-validator
   */
  async testConstraintValidator(params: {
    use_jintian_data?: boolean;
    strict_mode?: boolean;
  }): Promise<{
    success: boolean;
    compliance_score?: number;
    passed_checks?: number;
    total_checks?: number;
    conflicts?: Array<any>;
    is_valid?: boolean;
    recommendations?: string[];
    error?: string;
  }> {
    return apiRequest('/api/dev/gis/test/constraint-validator', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /**
   * Test hazard buffer generator
   * POST /api/dev/gis/test/hazard-buffer
   */
  async testHazardBuffer(params: {
    use_jintian_data?: boolean;
    buffer_meters?: number;
  }): Promise<{
    success: boolean;
    buffer_zones?: any;
    affected_area_km2?: number;
    hazard_count?: number;
    hazard_summary?: Record<string, any>;
    error?: string;
  }> {
    return apiRequest('/api/dev/gis/test/hazard-buffer', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },
};