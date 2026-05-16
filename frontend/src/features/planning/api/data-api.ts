// ============================================
// Data API - 数据访问 API
// ============================================

import { apiRequest } from './client';
import type { CrossSessionReport, DimensionVersion } from './types';

// ============================================
// Data API
// ============================================

export const dataApi = {
  /**
   * List all projects
   * GET /api/projects
   */
  async listVillages(): Promise<{ name: string; display_name: string; session_count: number }[]> {
    const response = await apiRequest<{ projects: { name: string; display_name: string; session_count: number }[] }>('/api/projects');
    return response.projects || [];
  },

  /**
   * Get sessions for a project
   * GET /api/projects/{name}/sessions
   */
  async getVillageSessions(villageName: string): Promise<{ session_id: string; created_at: string; completed_at: string | null }[]> {
    const response = await apiRequest<{ sessions: { session_id: string; created_at: string; completed_at: string | null }[] }>(
      `/api/projects/${encodeURIComponent(villageName)}/sessions`
    );
    return response.sessions || [];
  },

  /**
   * Get cross-session dimension report
   * GET /api/projects/{name}/reports/{dim_key}?session_id={id}&version={n}
   */
  async getCrossSessionReport(
    projectName: string,
    dimKey: string,
    sessionId?: string,
    version?: number
  ): Promise<CrossSessionReport> {
    const params = new URLSearchParams();
    if (sessionId) params.append('session_id', sessionId);
    if (version !== undefined) params.append('version', String(version));

    const query = params.toString() ? `?${params.toString()}` : '';
    return apiRequest<CrossSessionReport>(
      `/api/projects/${encodeURIComponent(projectName)}/reports/${dimKey}${query}`
    );
  },

  /**
   * Get dimension version history
   * GET /api/sessions/{id}/reports/{dim_key}/versions
   */
  async getDimensionVersions(sessionId: string, dimKey: string): Promise<DimensionVersion[]> {
    const response = await apiRequest<{ versions: DimensionVersion[] }>(
      `/api/sessions/${sessionId}/reports/${dimKey}/versions`
    );
    return response.versions || [];
  },

  // ============================================
  // GIS Tool Test API
  // ============================================

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
