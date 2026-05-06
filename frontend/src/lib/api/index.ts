// ============================================
// API Module - 统一导出
// ============================================

// Import modules first
import { planningApi } from './planning-api';
import { dataApi } from './data-api';
import { fileApi, knowledgeApi } from './knowledge-api';
import { gisApi } from './gis-api';

// Re-export types
export type {
  APIResponse,
  ApiError,
  VillageInfo,
  VillageSession,
  Checkpoint,
  LayerContent,
  PlanningSSEEventType,
  PlanningSSEDataBase,
  SSEEventResult,
  PlanningSSEEvent,
  StartPlanningRequest,
  StartPlanningResponse,
  ReviewActionRequest,
  SessionStatusResponse,
  UIMessage,
  LayerReportsResponse,
  FileUploadResponse,
  KnowledgeDocument,
  KnowledgeStats,
  AddDocumentResponse,
  AddDocumentOptions,
  SyncResponse,
  TaskStatus,
  TaskProgress,
  AsyncUploadResponse,
  ReviewData,
  ImageData,
  ImageSourceType,
  // GIS Types
  GISDataType,
  GISUploadMetadata,
  GISUploadResult,
  GISDataStatus,
  GISSupportedFormat,
  GISSupportedFormatsResponse,
} from './types';

// Re-export GIS constants
export { GIS_DATA_TYPE_NAMES } from './types';

// Re-export client
export { apiRequest, API_BASE_URL, createApiError } from './client';

// Re-export API modules
export { planningApi, dataApi, fileApi, knowledgeApi, gisApi };

// ============================================
// Default Export
// ============================================

const api = {
  planningApi,
  dataApi,
  fileApi,
  knowledgeApi,
  gisApi,
};

export default api;

// ============================================
// Compatibility Aliases
// ============================================

/**
 * taskApi - 别名指向 planningApi
 * 用于兼容使用 taskApi 的旧代码
 */
export { planningApi as taskApi };