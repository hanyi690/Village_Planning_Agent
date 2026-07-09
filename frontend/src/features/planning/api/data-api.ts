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
    try {
      const response = await apiRequest<{ versions: DimensionVersion[] }>(
        `/api/sessions/${sessionId}/reports/${dimKey}/versions`
      );
      return response.versions || [];
    } catch {
      return [];
    }
  },
};
