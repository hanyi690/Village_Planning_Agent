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
};