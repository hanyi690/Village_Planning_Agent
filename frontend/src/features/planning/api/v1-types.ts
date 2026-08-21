/**
 * v1 稳定 API 类型（唯一权威来源：docs/contracts/openapi-v1.json）。
 *
 * 由 openapi-typescript 自动生成（src/generated/v1.ts），此处仅做友好 re-export。
 * 生成命令（后端契约变更后必须重新生成）：
 *   npx openapi-typescript ../docs/contracts/openapi-v1.json -o src/generated/v1.ts
 */
import type { components } from '@/generated/v1';

export type SessionProjection = components['schemas']['SessionProjection'];
export type SessionCreated = components['schemas']['SessionCreated'];
export type ResumeAccepted = components['schemas']['ResumeAccepted'];
export type ResumeRequest = components['schemas']['ResumeRequest'];
export type DeliveryProjection = components['schemas']['DeliveryProjection'];
export type MapLayerCollection = components['schemas']['MapLayerCollection'];
export type MapLayer = components['schemas']['MapLayer'];
export type HumanReviewProjection = components['schemas']['HumanReviewProjection'];
export type HumanReviewDecision = components['schemas']['HumanReviewDecision'];
export type EventSyncResponse = components['schemas']['EventSyncResponse'];
export type ResourceLinks = components['schemas']['ResourceLinks'];
export type CreateSessionBody = components['schemas']['Body_create_session_api_v1_sessions_post'];
export type EvidenceQueryRequest = components['schemas']['EvidenceQueryRequest'];
export type EvidenceQueryResponse = components['schemas']['EvidenceQueryResponse'];
export type EvidenceFeatureRef = components['schemas']['FeatureEvidenceRef'];

export type SessionRunStatus = SessionProjection['status'];
export type DeliveryStatus = NonNullable<DeliveryProjection['delivery_status']>;
export type MapLayerType = MapLayer['layer_type'];
