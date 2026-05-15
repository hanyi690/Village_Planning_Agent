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
  FeedbackRequest,
  SessionStatusResponse,
  UIMessage,
  DimensionReportResponse,
  LayerReportsResponse,
  FileUploadResponse,
  ReviewData,
  ImageData,
  ImageSourceType,
} from './types';

// Client
export { apiRequest, API_BASE_URL, createApiError } from './client';

// API modules
export { planningApi } from './planning-api';
export { dataApi } from './data-api';

// Default export
import { planningApi } from './planning-api';
import { dataApi } from './data-api';

const api = {
  planningApi,
  dataApi,
};

export default api;

// Compatibility alias
export { planningApi as taskApi } from './planning-api';
