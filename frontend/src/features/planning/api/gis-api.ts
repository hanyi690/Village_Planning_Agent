// ============================================
// GIS API - GIS 数据上传和管理 API
// ============================================

import { apiRequest, API_BASE_URL } from './client';
import type {
  GISDataType,
  GISUploadResult,
  BackendGISUploadResult,
  GISUploadMetadata,
  BackendGISUploadMetadata,
  GISDataStatus,
  BackendGISDataStatus,
  GISSupportedFormatsResponse,
} from './types';

// ============================================
// Helper Functions
// ============================================

/**
 * Convert backend snake_case metadata to frontend camelCase
 */
function convertMetadata(metadata: BackendGISUploadMetadata): GISUploadMetadata {
  return {
    fileName: metadata.file_name,
    fileSize: metadata.file_size,
    fileType: metadata.file_type,
    featureCount: metadata.feature_count,
    properties: metadata.properties,
    crs: metadata.crs,
    uploadedAt: metadata.uploaded_at,
  };
}

/**
 * Convert backend snake_case upload result to frontend camelCase
 */
function convertUploadResult(result: BackendGISUploadResult): GISUploadResult {
  return {
    success: result.success,
    villageName: result.village_name,
    dataType: result.data_type as GISDataType,
    geojson: result.geojson,
    metadata: convertMetadata(result.metadata),
    source: result.source,
    error: result.error,
  };
}

/**
 * Convert backend snake_case status to frontend camelCase
 */
function convertDataStatus(status: BackendGISDataStatus): GISDataStatus {
  const metadata: Record<string, GISUploadMetadata> = {};
  for (const [key, value] of Object.entries(status.metadata)) {
    metadata[key] = convertMetadata(value);
  }

  return {
    villageName: status.village_name,
    userUploaded: status.user_uploaded as GISDataType[],
    cached: status.cached as GISDataType[],
    missing: status.missing as GISDataType[],
    metadata,
  };
}

// ============================================
// GIS API
// ============================================

export const gisApi = {
  /**
   * Upload GIS file
   * POST /api/gis/upload
   */
  async uploadGISFile(
    file: File,
    villageName: string,
    dataType?: GISDataType
  ): Promise<GISUploadResult> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('village_name', villageName);
    if (dataType) {
      formData.append('data_type', dataType);
    }

    // FormData 需要 multipart/form-data，不能使用 apiRequest 的默认 JSON 头
    const response = await fetch(`${API_BASE_URL}/api/gis/upload`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `上传失败: ${response.status}`);
    }

    const data: BackendGISUploadResult = await response.json();
    return convertUploadResult(data);
  },

  /**
   * Upload GeoJSON directly (parsed in frontend)
   * POST /api/gis/upload - with JSON body instead of FormData
   */
  async uploadGeoJSON(
    geojson: GeoJSON.FeatureCollection,
    villageName: string,
    dataType: GISDataType,
    fileName?: string
  ): Promise<GISUploadResult> {
    // 构建请求体
    const body = {
      geojson,
      village_name: villageName,
      data_type: dataType,
      file_name: fileName || 'uploaded.geojson',
    };

    const result = await apiRequest<BackendGISUploadResult>('/api/gis/upload-geojson', {
      method: 'POST',
      body: JSON.stringify(body),
    });

    return convertUploadResult(result);
  },

  /**
   * Get GIS data status for a village
   * GET /api/gis/status/{village_name}
   */
  async getGISDataStatus(villageName: string): Promise<GISDataStatus> {
    const result = await apiRequest<BackendGISDataStatus>(
      `/api/gis/status/${encodeURIComponent(villageName)}`
    );
    return convertDataStatus(result);
  },

  /**
   * Clear user uploaded GIS data
   * DELETE /api/gis/clear/{village_name}/{data_type}
   */
  async clearGISData(villageName: string, dataType: GISDataType): Promise<{ success: boolean; message: string }> {
    return apiRequest(
      `/api/gis/clear/${encodeURIComponent(villageName)}/${encodeURIComponent(dataType)}`,
      { method: 'DELETE' }
    );
  },

  /**
   * Get supported GIS file formats
   * GET /api/gis/supported-formats
   */
  async getSupportedFormats(): Promise<GISSupportedFormatsResponse> {
    const result = await apiRequest<{
      supported: Array<{ ext: string; type: string; description: string }>;
      unsupported: Array<{ ext: string; type: string; description: string }>;
      max_file_size_mb: number;
    }>('/api/gis/supported-formats');

    return {
      supported: result.supported,
      unsupported: result.unsupported,
      maxFileSizeMb: result.max_file_size_mb,
    };
  },

  /**
   * Infer GIS data type from GeoJSON properties
   * POST /api/gis/infer-type
   */
  async inferDataType(geojson: GeoJSON.FeatureCollection): Promise<{ dataType: GISDataType; confidence: number }> {
    return apiRequest<{ data_type: string; confidence: number }>(
      '/api/gis/infer-type',
      {
        method: 'POST',
        body: JSON.stringify({ geojson }),
      }
    ).then(result => ({
      dataType: result.data_type as GISDataType,
      confidence: result.confidence,
    }));
  },
};

export default gisApi;