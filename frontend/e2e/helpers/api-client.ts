/**
 * Direct backend API client for E2E tests.
 * Uses native fetch to call the FastAPI backend without going through the frontend.
 */

import { BACKEND_URL } from '../fixtures/village-data';

export interface SessionConfig {
  projectName: string;
  villageName?: string;
  villageData: string;
  taskDescription?: string;
  constraints?: string;
  province?: string;
  city?: string;
  county?: string;
  township?: string;
  planningPeriod?: string;
  stepMode?: boolean;
  ragEnabled?: boolean;
}

export interface SessionStatus {
  session_id: string;
  status: string;
  phase: string;
  current_layer: number;
  current_wave: number;
  progress: number;
  completed_dimensions: Record<string, string[]>;
  project_name: string;
  village_name: string;
  step_mode: boolean;
  execution_error?: string;
  interrupt_info?: {
    layer: number;
    phase: string;
    layer_name: string;
    reason: string;
  };
}

export interface PlanningTextResponse {
  session_id: string;
  version: number;
  phase: string;
  content: string;
  generated_at: string;
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = BACKEND_URL) {
    this.baseUrl = baseUrl;
  }

  /** Create a new planning session. Returns session_id. */
  async createSession(config: SessionConfig): Promise<string> {
    const formData = new FormData();
    formData.append('project_name', config.projectName);
    formData.append('village_data', config.villageData);
    if (config.villageName) formData.append('village_name', config.villageName);
    if (config.taskDescription) formData.append('task_description', config.taskDescription);
    if (config.constraints) formData.append('constraints', config.constraints);
    if (config.province) formData.append('province', config.province);
    if (config.city) formData.append('city', config.city);
    if (config.county) formData.append('county', config.county);
    if (config.township) formData.append('township', config.township);
    if (config.planningPeriod) formData.append('planning_period', config.planningPeriod);
    if (config.stepMode !== undefined) formData.append('step_mode', String(config.stepMode));
    if (config.ragEnabled !== undefined) formData.append('rag_enabled', String(config.ragEnabled));

    const response = await fetch(`${this.baseUrl}/api/v1/sessions`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const errBody = await response.json().catch(() => ({}));
      throw new Error(`Create session failed (${response.status}): ${JSON.stringify(errBody)}`);
    }

    const data = await response.json();
    return data.session_id;
  }

  /** Get session status. */
  async getStatus(sessionId: string): Promise<SessionStatus> {
    const response = await fetch(`${this.baseUrl}/api/v1/sessions/${sessionId}/state`);
    if (!response.ok) {
      throw new Error(`Get status failed (${response.status})`);
    }
    return response.json();
  }

  /** Poll until session reaches expected status or timeout. */
  async waitForStatus(
    sessionId: string,
    predicate: (status: SessionStatus) => boolean,
    timeoutMs: number = 300000,
    intervalMs: number = 2000,
  ): Promise<SessionStatus> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const status = await this.getStatus(sessionId);
      if (predicate(status)) return status;
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    throw new Error(`Timeout waiting for status after ${timeoutMs}ms`);
  }

  /** Wait for session to reach 'paused' state (interrupt). */
  async waitForPaused(sessionId: string, timeoutMs: number = 300000): Promise<SessionStatus> {
    return this.waitForStatus(sessionId, (s) => s.status === 'paused' || s.status === 'completed', timeoutMs);
  }

  /** Wait for session to reach 'completed' state. */
  async waitForCompleted(sessionId: string, timeoutMs: number = 600000): Promise<SessionStatus> {
    return this.waitForStatus(sessionId, (s) => s.status === 'completed', timeoutMs);
  }

  /** Approve current layer and continue. */
  async approve(sessionId: string) {
    const response = await fetch(`${this.baseUrl}/api/sessions/${sessionId}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approve: true }),
    });
    return response.json();
  }

  /** Reject with feedback and trigger revision. */
  async reject(sessionId: string, feedback: string, dimensions?: string[]) {
    const response = await fetch(`${this.baseUrl}/api/sessions/${sessionId}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ feedback, dimensions, approve: false }),
    });
    return response.json();
  }

  /** Delete a session. */
  async deleteSession(sessionId: string) {
    await fetch(`${this.baseUrl}/api/sessions/${sessionId}`, { method: 'DELETE' });
  }

  /** Get planning text for a session. */
  async getPlanningText(sessionId: string): Promise<PlanningTextResponse | null> {
    const response = await fetch(`${this.baseUrl}/api/sessions/${sessionId}/planning-text`);
    if (!response.ok) return null;
    return response.json();
  }

  /** Trigger GIS analysis by sending a message with GIS keywords. */
  async triggerGisAnalysis(sessionId: string): Promise<{ status: string }> {
    const response = await fetch(`${this.baseUrl}/api/sessions/${sessionId}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: '请进行空间布局分析', approve: false }),
    });
    if (!response.ok) {
      const errBody = await response.json().catch(() => ({}));
      throw new Error(`GIS analysis trigger failed (${response.status}): ${JSON.stringify(errBody)}`);
    }
    return response.json();
  }

  /** Upload a GIS GeoJSON file to an existing session. */
  async uploadGisData(
    sessionId: string,
    filePath: string,
    dataType?: string,
  ): Promise<{ file_id: string; filename: string; data_type: string; feature_count: number; parse_status: string }> {
    const fs = await import('fs/promises');
    const path = await import('path');
    const fileName = path.basename(filePath);
    const fileBuffer = await fs.readFile(filePath);
    const blob = new Blob([fileBuffer], { type: 'application/geo+json' });

    const formData = new FormData();
    formData.append('file', blob, fileName);
    if (dataType) formData.append('data_type', dataType);

    const response = await fetch(`${this.baseUrl}/api/sessions/${sessionId}/gis-data`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const errBody = await response.json().catch(() => ({}));
      throw new Error(`GIS upload failed (${response.status}): ${JSON.stringify(errBody)}`);
    }

    return response.json();
  }

  /** Batch upload Jintian GIS data files. */
  async uploadJintianGisData(
    sessionId: string,
    files: Record<string, string>,
  ): Promise<{ file_id: string; filename: string; data_type: string; feature_count: number; parse_status: string }[]> {
    const results = [];
    for (const [dataType, filePath] of Object.entries(files)) {
      try {
        const result = await this.uploadGisData(sessionId, filePath, dataType);
        results.push(result);
        console.log(`[uploadJintianGisData] ${dataType}: ${result.feature_count} features (${result.parse_status})`);
      } catch (err) {
        console.warn(`[uploadJintianGisData] ${dataType} upload failed: ${(err as Error).message}`);
      }
    }
    return results;
  }

  /** Create session with GIS files uploaded in the same call. */
  async createSessionWithGis(
    config: SessionConfig,
    gisFiles: Record<string, string>,
  ): Promise<string> {
    // First create the session
    const sessionId = await this.createSession(config);

    // Then upload GIS files
    if (Object.keys(gisFiles).length > 0) {
      await this.uploadJintianGisData(sessionId, gisFiles);
    }

    return sessionId;
  }
}

export const apiClient = new ApiClient();
