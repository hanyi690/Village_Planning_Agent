/**
 * Planning Feature API
 *
 * Unified API module for planning-related endpoints.
 */

// Types
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
  GISDataType,
  GISUploadMetadata,
  GISUploadResult,
  GISDataStatus,
  GISSupportedFormat,
  GISSupportedFormatsResponse,
} from './types';

// Constants
export { GIS_DATA_TYPE_NAMES } from './types';

// Client
export { apiRequest, API_BASE_URL, createApiError } from './client';

// API modules
export { planningApi } from './planning-api';
export { dataApi } from './data-api';
export { fileApi, knowledgeApi } from './knowledge-api';
export { gisApi } from './gis-api';

// Default export
import { planningApi } from './planning-api';
import { dataApi } from './data-api';
import { fileApi, knowledgeApi } from './knowledge-api';
import { gisApi } from './gis-api';

const api = {
  planningApi,
  dataApi,
  fileApi,
  knowledgeApi,
  gisApi,
};

export default api;

// Compatibility alias
export { planningApi as taskApi } from './planning-api';