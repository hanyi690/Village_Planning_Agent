/**
 * useSessionRestore Hook
 *
 * Handles session restoration from URL sessionId parameter.
 * When page refreshes with sessionId in URL, automatically:
 * 1. Sets sessionId in store
 * 2. Fetches and syncs backend state
 * 3. Loads historical messages
 * 4. Updates URL with sessionId
 */

import { useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { usePlanningStore } from '../store/planningStore';
import { planningApi } from '../api';
import { logger } from '@/features/planning/utils/logger';
import { DIMENSION_NAMES } from '../config/dimensions';
import type { DimensionProgressItem, KnowledgeSource } from '../types';
import type { LayerCompletedMessage, Message } from '../types/messages';
import type { RAGRetrievalLog, RetrievedChunk, KnowledgeSourceItem } from '../api/types';

interface UseSessionRestoreOptions {
  enabled?: boolean;
}

export function useSessionRestore({ enabled = true }: UseSessionRestoreOptions = {}) {
  const searchParams = useSearchParams();

  const sessionIdFromUrl = searchParams.get('sessionId');
  const sessionId = usePlanningStore((state) => state.sessionId);
  const status = usePlanningStore((state) => state.status);
  const setSessionId = usePlanningStore((state) => state.setSessionId);
  const setMessages = usePlanningStore((state) => state.setMessages);
  const setReports = usePlanningStore((state) => state.setReports);
  const syncBackendState = usePlanningStore((state) => state.syncBackendState);
  const setStatus = usePlanningStore((state) => state.setStatus);
  const resetConversation = usePlanningStore((state) => state.resetConversation);
  const setDimensionProgressBatch = usePlanningStore((state) => state.setDimensionProgressBatch);
  const setRagDocuments = usePlanningStore((state) => state.setRagDocuments);

  const restoringRef = useRef(false);
  const restoredSessionIdRef = useRef<string | null>(null);
  const resetProtectionRef = useRef(false);

  // Update URL with sessionId (without triggering navigation)
  const updateUrlWithSessionId = useCallback((newSessionId: string) => {
    const currentUrl = new URL(window.location.href);
    const currentSessionIdInUrl = currentUrl.searchParams.get('sessionId');

    if (currentSessionIdInUrl !== newSessionId) {
      currentUrl.searchParams.set('sessionId', newSessionId);
      window.history.replaceState({}, '', currentUrl.toString());
      logger.context.info('URL updated with sessionId', { sessionId: newSessionId });
    }
  }, []);

  // Restore session from backend
  const restoreSession = useCallback(async (targetSessionId: string) => {
    // Skip if already restoring
    if (restoringRef.current) {
      return;
    }

    // Check if store already has correct sessionId
    const currentSessionId = usePlanningStore.getState().sessionId;
    if (currentSessionId === targetSessionId) {
      restoredSessionIdRef.current = targetSessionId;
      return;
    }

    restoringRef.current = true;
    logger.context.info('Starting session restoration', { sessionId: targetSessionId });

    try {
      // 1. Set sessionId first
      setSessionId(targetSessionId);

      // 2. Fetch session status
      const statusData = await planningApi.getStatus(targetSessionId);

      // 3. Sync backend state
      syncBackendState(statusData);

      // 4. Set project name if available (from village_name field if exists)
      // Note: SessionStatusResponse doesn't include project_name directly
      // Project name is typically derived from village history selection
      // During refresh restore, we skip this and rely on backend state

      // 5. Set status based on backend status
      const backendStatus = statusData.status;
      if (backendStatus === 'completed' || backendStatus === 'paused') {
        setStatus(backendStatus);
      } else if (backendStatus === 'planning' || backendStatus === 'running') {
        setStatus('planning');
      }

      // 6. Restore messages from backend - rebuild LayerCompletedMessage from reports
      // Note: We don't restore LLM messages (statusData.messages), instead we rebuild UI messages
      // from the persisted dimension_reports data
      const restoredMessages: Message[] = [];

      // 7. Load layer reports for completed layers
      const completedDimensions = statusData.completed_dimensions;
      console.log('[SessionRestore] completedDimensions:', completedDimensions);
      if (completedDimensions) {
        const layers = [1, 2, 3] as const;
        for (const layer of layers) {
          const dims = completedDimensions[`layer${layer}`];
          console.log('[SessionRestore] Layer', layer, 'dims:', dims);
          if (dims && dims.length > 0) {
            try {
              console.log('[SessionRestore] Fetching reports for layer', layer);
              const reportsData = await planningApi.getLayerReports(targetSessionId, layer);
              console.log('[SessionRestore] reportsData for layer', layer, ':', reportsData);

              // Handle both formats:
              // 1. New format: {dim_key: {content, knowledge_sources}} (direct dict)
              // 2. Old format: {layer, reports: {dim_key: {...}}} (wrapped)
              const reportsDict = reportsData.reports || reportsData;
              const reportKeys = Object.keys(reportsDict);

              console.log('[SessionRestore] reportKeys for layer', layer, ':', reportKeys);

              if (reportKeys.length > 0) {
                // Convert new format to old format for setReports compatibility
                const reportsContent: Record<string, string> = {};
                const knowledgeSourcesMap: Record<string, KnowledgeSource[]> = {};

                for (const [dimKey, reportData] of Object.entries(reportsDict)) {
                  // Handle both new format (object) and old format (string)
                  if (typeof reportData === 'string') {
                    reportsContent[dimKey] = reportData;
                  } else if (reportData && typeof reportData === 'object' && 'content' in reportData) {
                    reportsContent[dimKey] = reportData.content;

                    // Extract RAG knowledge sources from RAGRetrievalLog format
                    if (reportData.knowledge_sources) {
                      const ks = reportData.knowledge_sources as RAGRetrievalLog | KnowledgeSourceItem[];
                      console.log('[SessionRestore] knowledge_sources for', dimKey, ':', ks);

                      // Backend stores RAGRetrievalLog object with retrieved_chunks
                      if ('retrieved_chunks' in ks && Array.isArray(ks.retrieved_chunks)) {
                        console.log('[SessionRestore] retrieved_chunks found, count:', ks.retrieved_chunks.length);
                        const fullKey = `${layer}_${dimKey}`;

                        // Direct conversion: RetrievedChunk -> RagDocument (preserve score)
                        const ragDocuments = ks.retrieved_chunks.map((chunk: RetrievedChunk) => ({
                          title: chunk.source || 'unknown',
                          snippet: chunk.content_preview || '',
                          source: chunk.source,
                          score: chunk.score,
                          chunk_id: chunk.chunk_id,
                          dimension_tags: chunk.dimension_tags,
                        }));

                        if (ragDocuments.length > 0) {
                          // Set query first, then documents
                          if (ks.query) {
                            usePlanningStore.getState().setRagQuery(fullKey, ks.query);
                          }
                          setRagDocuments(fullKey, ragDocuments);
                          console.log('[SessionRestore] Set RAG sources for', fullKey, ':', {
                            query: ks.query,
                            documentCount: ragDocuments.length,
                          });
                        }
                      } else if (Array.isArray(ks)) {
                        console.log('[SessionRestore] knowledge_sources is array, count:', ks.length);
                        // Fallback: direct array format (KnowledgeSourceItem[])
                        const fullKey = `${layer}_${dimKey}`;
                        const ragDocuments = ks.map((item: KnowledgeSourceItem) => ({
                          title: item.title || item.source || 'unknown',
                          snippet: item.snippet || '',
                          source: item.source,
                          score: item.score,
                        }));

                        if (ragDocuments.length > 0) {
                          setRagDocuments(fullKey, ragDocuments);
                          console.log('[SessionRestore] Set RAG sources for', fullKey, ':', {
                            documentCount: ragDocuments.length,
                          });
                        }
                      } else {
                        console.log('[SessionRestore] knowledge_sources format not recognized');
                      }
                    } else {
                      console.log('[SessionRestore] No knowledge_sources for', dimKey);
                    }
                  }
                }
                setReports({ [`layer${layer}`]: reportsContent });

                // Build LayerCompletedMessage for this layer
                const totalChars = Object.values(reportsContent).reduce((sum, c) => sum + c.length, 0);
                const layerMsg: LayerCompletedMessage = {
                  id: `layer_report_${layer}`,
                  type: 'layer_completed',
                  layer,
                  content: '',
                  summary: {
                    word_count: totalChars,
                    key_points: [],
                    dimension_count: Object.keys(reportsContent).length,
                  },
                  fullReportContent: '',
                  dimensionReports: reportsContent,
                  dimensionKnowledgeSources: knowledgeSourcesMap,
                  actions: [],
                  timestamp: new Date(),
                  role: 'assistant',
                };
                restoredMessages.push(layerMsg);

                // Restore dimensionProgress from reports for completed dimensions
                const progressUpdates: Record<string, DimensionProgressItem> = {};
                for (const [dimKey, content] of Object.entries(reportsContent)) {
                  if (content && content.length > 0) {
                    const progressKey = `${layer}_${dimKey}`;
                    progressUpdates[progressKey] = {
                      dimensionKey: dimKey,
                      dimensionName: DIMENSION_NAMES[dimKey] || dimKey,
                      layer,
                      status: 'completed',
                      wordCount: content.length,
                      completedAt: new Date().toISOString(),
                    };
                  }
                }
                if (Object.keys(progressUpdates).length > 0) {
                  setDimensionProgressBatch(progressUpdates);
                }

                logger.context.info(`Loaded layer ${layer} reports`, {
                  dimensionCount: Object.keys(reportsData.reports).length,
                });
              }
            } catch (error) {
              logger.context.warn(`Failed to load layer ${layer} reports`, { error });
            }
          }
        }
      }

      // Set rebuilt messages
      if (restoredMessages.length > 0) {
        setMessages(restoredMessages);
      } else {
        setMessages([]);
      }

      // 8. Mark as restored
      restoredSessionIdRef.current = targetSessionId;
      logger.context.info('Session restoration completed', {
        sessionId: targetSessionId,
        status: statusData.status,
        phase: statusData.phase,
      });
    } catch (error) {
      logger.context.error('Session restoration failed', { error, sessionId: targetSessionId });
      // Clear invalid sessionId from URL
      const url = new URL(window.location.href);
      url.searchParams.delete('sessionId');
      window.history.replaceState({}, '', url.toString());
      resetConversation();
    } finally {
      restoringRef.current = false;
    }
  }, [setSessionId, syncBackendState, setStatus, setMessages, setReports, resetConversation, setDimensionProgressBatch, setRagDocuments]);

  // On mount: check if sessionId in URL and restore
  useEffect(() => {
    if (!enabled) return;

    // Clear resetProtection when sessionIdFromUrl becomes null (URL cleared)
    if (!sessionIdFromUrl) {
      resetProtectionRef.current = false;
    }

    // Only restore if:
    // 1. sessionId in URL
    // 2. Store has no sessionId (fresh page load)
    // 3. Not already restoring
    // 4. Not protected by reset (prevents restore after clicking "New Task")
    if (sessionIdFromUrl && !sessionId && !restoringRef.current && !resetProtectionRef.current) {
      restoreSession(sessionIdFromUrl);
    }

    // StrictMode cleanup: reset ref so remount can restore
    return () => {
      restoringRef.current = false;
    };
  }, [enabled, sessionIdFromUrl, sessionId, restoreSession]);

  // When sessionId changes in store, update URL
  useEffect(() => {
    if (!enabled || !sessionId) return;

    // Don't update URL if this is the sessionId we just restored
    if (sessionId === restoredSessionIdRef.current) return;

    updateUrlWithSessionId(sessionId);
  }, [enabled, sessionId, updateUrlWithSessionId]);

  // Detect reset: when sessionId becomes null and status becomes 'idle'
  // Set resetProtection to prevent session restore from re-triggering
  useEffect(() => {
    if (!enabled) return;

    // When store is reset to idle state, activate protection
    if (sessionId === null && status === 'idle') {
      resetProtectionRef.current = true;
      logger.context.info('Reset protection activated');
    }
  }, [enabled, sessionId, status]);

  return {
    isRestoring: restoringRef.current,
    sessionIdFromUrl,
    restoreSession,
    updateUrlWithSessionId,
  };
}

export default useSessionRestore;