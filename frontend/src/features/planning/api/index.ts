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
  PersistedHistoryResponse,
  CurrentSourceLayer,
  CurrentSourceRaster,
  CurrentSourceLayerCollection,
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
  ArtifactType,
  ArtifactRef,
  ArtifactListResponse,
  ArtifactResponse,
  ArtifactRefResponse,
  ChatHistoryMessage,
  RenderLayer,
  RenderLayersResponse,
  DeliveryStatus,
  DeliveryProjection,
  HumanReviewItem,
  HumanReviewListResponse,
  HumanReviewResolveRequest,
  HumanReviewResolveResponse,
  EvidenceQueryRequest,
  EvidenceFeatureRef,
  EvidenceQueryResponse,
  PlanningDependencyNode,
  PlanningDependencyEdge,
  PlanningDependencyGraphResponse,
} from './types';

// Client
export { apiRequest, API_BASE_URL, createApiError } from './client';

// API modules
export { planningApi } from './planning-api';

// Default export
import { planningApi } from './planning-api';

const api = {
  planningApi,
};

export default api;

// Compatibility alias
export { planningApi as taskApi } from './planning-api';
