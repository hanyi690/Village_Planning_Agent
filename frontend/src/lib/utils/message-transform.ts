/**
 * Message Transform Utilities
 *
 * Common utility for transforming backend message format to frontend Message type.
 * Used by both planning-context.tsx and useSessionRestore.ts.
 */

import type { Message } from '@/types';
import type { GISData } from '@/types/message/message-types';

/**
 * Transform backend messages array to frontend Message format
 */
export function transformBackendMessages(messages: unknown[]): Message[] {
  return messages.map((msg: unknown) => {
    const m = msg as Record<string, unknown>;
    const baseMsg = {
      id: (m.message_id as string) || `db-${m.id}`,
      timestamp: new Date((m.created_at as string) || Date.now()),
      role: (m.role || 'assistant') as 'user' | 'assistant' | 'system',
      created_at: m.created_at as string | undefined,
    };

    const msgMeta = (m.message_metadata || m.metadata || {}) as Record<string, unknown>;

    switch (m.message_type) {
      case 'dimension_report':
        return {
          ...baseMsg,
          type: 'dimension_report' as const,
          layer: (msgMeta.layer as number) || 1,
          dimensionKey: (msgMeta.dimensionKey as string) || '',
          dimensionName: (msgMeta.dimensionName as string) || '',
          content: (m.content as string) || '',
          streamingState: (msgMeta.streamingState as 'streaming' | 'completed' | 'error') || 'completed',
          wordCount: (msgMeta.wordCount as number) || ((m.content as string)?.length || 0),
          previousContent: msgMeta.previousContent as string | undefined,
          revisionVersion: msgMeta.revisionVersion as number | undefined,
          isRevision: msgMeta.isRevision as boolean | undefined,
        };

      case 'layer_completed':
        return {
          ...baseMsg,
          type: 'layer_completed' as const,
          layer: (msgMeta.layer as number) || 1,
          content: (m.content as string) || '',
          summary: (msgMeta.summary as { word_count: number; key_points: string[] }) || { word_count: 0, key_points: [] },
          fullReportContent: msgMeta.fullReportContent as string | undefined,
          dimensionReports: msgMeta.dimensionReports as Record<string, string> | undefined,
          dimensionGisData: msgMeta.dimensionGisData as Record<string, GISData> | undefined,
          actions: [],
        };

      case 'file':
        return {
          ...baseMsg,
          type: 'file' as const,
          filename: (msgMeta.filename as string) || '',
          fileContent: (msgMeta.fileContent as string) || '',
          fileSize: msgMeta.fileSize as number | undefined,
          encoding: msgMeta.encoding as string | undefined,
          fileType: msgMeta.fileType as 'document' | 'image' | undefined,
          imageBase64: msgMeta.imageBase64 as string | undefined,
          imageFormat: msgMeta.imageFormat as string | undefined,
          thumbnailBase64: msgMeta.thumbnailBase64 as string | undefined,
          imageWidth: msgMeta.imageWidth as number | undefined,
          imageHeight: msgMeta.imageHeight as number | undefined,
          embeddedImages: msgMeta.embeddedImages as { imageBase64: string; imageFormat: string; thumbnailBase64: string; imageWidth: number; imageHeight: number }[] | undefined,
        };

      case 'progress':
        return {
          ...baseMsg,
          type: 'progress' as const,
          content: (m.content as string) || '',
          progress: (msgMeta.progress as number) || 0,
          currentLayer: msgMeta.currentLayer as string | undefined,
          taskId: msgMeta.taskId as string | undefined,
        };

      case 'tool_status':
        return {
          ...baseMsg,
          type: 'tool_status' as const,
          toolName: (msgMeta.toolName as string) || '',
          toolDisplayName: (msgMeta.toolDisplayName as string) || '',
          description: (msgMeta.description as string) || '',
          status: (msgMeta.status as 'pending' | 'running' | 'success' | 'error') || 'pending',
          progress: msgMeta.progress as number | undefined,
          stage: msgMeta.stage as string | undefined,
          stageMessage: msgMeta.stageMessage as string | undefined,
          summary: msgMeta.summary as string | undefined,
          error: msgMeta.error as string | undefined,
          startedAt: msgMeta.startedAt as string | undefined,
          completedAt: msgMeta.completedAt as string | undefined,
          estimatedTime: msgMeta.estimatedTime as number | undefined,
        };

      // Legacy types for backward compatibility with old messages
      case 'tool_call':
        return {
          ...baseMsg,
          type: 'tool_status' as const,
          toolName: (msgMeta.toolName as string) || '',
          toolDisplayName: (msgMeta.toolDisplayName as string) || '',
          description: (msgMeta.description as string) || '',
          status: 'running' as const,
          estimatedTime: msgMeta.estimatedTime as number | undefined,
          stage: msgMeta.stage as string | undefined,
        };

      case 'tool_progress':
        return {
          ...baseMsg,
          type: 'tool_status' as const,
          toolName: (msgMeta.toolName as string) || '',
          toolDisplayName: (msgMeta.toolName as string) || '',  // Fallback to toolName
          description: (msgMeta.message as string) || '',
          status: 'running' as const,
          stage: (msgMeta.stage as string) || '',
          progress: (msgMeta.progress as number) || 0,
        };

      case 'tool_result':
        return {
          ...baseMsg,
          type: 'tool_status' as const,
          toolName: (msgMeta.toolName as string) || '',
          toolDisplayName: (msgMeta.toolName as string) || '',
          description: '',
          status: (msgMeta.status === 'error' ? 'error' : 'success') as 'error' | 'success',
          summary: (msgMeta.summary as string) || '',
        };

      default:
        return {
          ...baseMsg,
          type: 'text' as const,
          content: (m.content as string) || '',
        };
    }
  });
}