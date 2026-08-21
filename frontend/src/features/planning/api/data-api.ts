// ============================================
// Data API - 数据访问 API
// ============================================

import type { CrossSessionReport, DimensionVersion } from './types';

// ============================================
// Data API
// ============================================
// Legacy cross-session report endpoints remain unavailable in v1.
// Persisted planning history is provided by planningApi.listProjects()
// through GET /api/v1/projects; these legacy methods remain for compatibility.

export const dataApi = {
  /**
   * List all projects
   * GET /api/projects (已下线)
   */
  async listVillages(): Promise<{ name: string; display_name: string; session_count: number }[]> {
    throw new Error('[v1] 项目列表端点已下线（GET /api/projects）');
  },

  /**
   * Get sessions for a project
   * GET /api/projects/{name}/sessions (已下线)
   */
  async getVillageSessions(_villageName: string): Promise<{ session_id: string; created_at: string; completed_at: string | null }[]> {
    throw new Error('[v1] 项目会话端点已下线（GET /api/projects/{name}/sessions）');
  },

  /**
   * Get cross-session dimension report
   * GET /api/projects/{name}/reports/{dim_key} (已下线)
   */
  async getCrossSessionReport(
    _projectName: string,
    _dimKey: string,
    _sessionId?: string,
    _version?: number
  ): Promise<CrossSessionReport> {
    throw new Error('[v1] 跨会话报告端点已下线（GET /api/projects/{name}/reports/{dim_key}）');
  },

  /**
   * Get dimension version history
   * GET /api/sessions/{id}/reports/{dim_key}/versions (已下线)
   */
  async getDimensionVersions(_sessionId: string, _dimKey: string): Promise<DimensionVersion[]> {
    throw new Error('[v1] 版本历史端点已下线（GET /api/sessions/{id}/reports/{dim_key}/versions）');
  },
};
