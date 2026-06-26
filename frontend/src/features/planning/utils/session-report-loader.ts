/**
 * Session Report Loader
 *
 * Shared utility for loading session reports, parsing formats,
 * extracting RAG knowledge sources, and updating the store.
 * Used by both loadHistoricalSession and useSessionRestore.
 */

import { planningApi } from '../api';
import { usePlanningStore } from '../store/planningStore';
import { DIMENSION_NAMES } from '../config/dimensions';
import { logger } from './logger';
import type { DimensionProgressItem } from '../types';
import type { RetrievedChunk } from '../api/types';

/** Matches store's internal RagDocument shape */
export interface SessionRagDocument {
  title: string;
  snippet: string;
  source?: string;
  score?: number;
  chunk_id?: string;
  matched_query?: string;
}

interface LayerReportResult {
  layer: number;
  reportsContent: Record<string, string>;
  progressUpdates: Record<string, DimensionProgressItem>;
  ragSources: Record<string, { query: string; documents: SessionRagDocument[] }>;
}

/**
 * Extract RAG knowledge sources from backend response.
 * Handles both RAGRetrievalLog (with retrieved_chunks) and
 * KnowledgeSourceItem[] (direct array) formats.
 */
function extractRagSources(
  ks: unknown,
): { query: string; documents: SessionRagDocument[] } {
  const ksObj = ks as Record<string, unknown>;

  if ('retrieved_chunks' in ksObj && Array.isArray(ksObj.retrieved_chunks)) {
    const chunks = ksObj.retrieved_chunks as RetrievedChunk[];
    const query =
      'query' in ksObj && typeof ksObj.query === 'string' ? ksObj.query : '';
    return {
      query,
      documents: chunks.map((chunk) => ({
        title: chunk.source || 'unknown',
        snippet: chunk.content_preview || '',
        source: chunk.source,
        score: chunk.score,
        chunk_id: chunk.chunk_id,
      })),
    };
  }

  if (Array.isArray(ks)) {
    return {
      query: '',
      documents: (ks as Array<Record<string, unknown>>).map((item) => ({
        title: (item.title as string) || (item.source as string) || 'unknown',
        snippet: (item.snippet as string) || '',
        source: item.source as string | undefined,
        score: item.score as number | undefined,
      })),
    };
  }

  return { query: '', documents: [] };
}

/**
 * Load reports for a single layer and parse all formats.
 */
async function loadLayerReports(
  sessionId: string,
  layer: number,
): Promise<LayerReportResult | null> {
  try {
    const reportsData = await planningApi.getLayerReports(sessionId, layer);
    const reportsDict =
      (reportsData as unknown as Record<string, unknown>).reports ||
      reportsData;
    const reportKeys = Object.keys(reportsDict as Record<string, unknown>);

    if (reportKeys.length === 0) return null;

    const reportsContent: Record<string, string> = {};
    const progressUpdates: Record<string, DimensionProgressItem> = {};
    const ragSources: Record<string, { query: string; documents: SessionRagDocument[] }> = {};

    for (const [dimKey, reportData] of Object.entries(
      reportsDict as Record<string, unknown>,
    )) {
      if (typeof reportData === 'string') {
        reportsContent[dimKey] = reportData;
      } else if (
        reportData &&
        typeof reportData === 'object' &&
        'content' in (reportData as object)
      ) {
        const reportObj = reportData as {
          content: string;
          knowledge_sources?: unknown;
        };
        reportsContent[dimKey] = reportObj.content;

        if (reportObj.knowledge_sources) {
          const fullKey = `${layer}_${dimKey}`;
          const extracted = extractRagSources(reportObj.knowledge_sources);
          if (extracted.documents.length > 0) {
            ragSources[fullKey] = extracted;
          }
        }
      }

      if (reportsContent[dimKey] && reportsContent[dimKey].length > 0) {
        const progressKey = `${layer}_${dimKey}`;
        progressUpdates[progressKey] = {
          dimensionKey: dimKey,
          dimensionName: DIMENSION_NAMES[dimKey] || dimKey,
          layer,
          status: 'completed',
          wordCount: reportsContent[dimKey].length,
          completedAt: new Date().toISOString(),
        };
      }
    }

    return { layer, reportsContent, progressUpdates, ragSources };
  } catch (error) {
    logger.context.warn(`Failed to load layer ${layer} reports`, { error });
    return null;
  }
}

/**
 * Load all completed layer reports for a session in parallel.
 * Returns batched store updates to minimize re-renders.
 */
export async function loadSessionReports(
  sessionId: string,
  completedDimensions: Record<string, string[]>,
): Promise<{
  allReports: Record<string, Record<string, string>>;
  allProgress: Record<string, DimensionProgressItem>;
  allRagSources: Record<string, { query: string; documents: SessionRagDocument[] }>;
}> {
  const layers = [1, 2, 3] as const;
  const layersToFetch = layers.filter((layer) => {
    const dims = completedDimensions[`layer${layer}`];
    return dims && dims.length > 0;
  });

  const results = await Promise.all(
    layersToFetch.map((layer) => loadLayerReports(sessionId, layer)),
  );

  const allReports: Record<string, Record<string, string>> = {};
  const allProgress: Record<string, DimensionProgressItem> = {};
  const allRagSources: Record<string, { query: string; documents: SessionRagDocument[] }> = {};

  for (const result of results) {
    if (!result) continue;
    allReports[`layer${result.layer}`] = result.reportsContent;
    Object.assign(allProgress, result.progressUpdates);
    Object.assign(allRagSources, result.ragSources);
  }

  return { allReports, allProgress, allRagSources };
}

/**
 * Apply loaded reports to the store in minimal batched updates.
 * - One setReports call (triggers deriveUIStateInStore once)
 * - One setDimensionProgressBatch call
 * - Per-dimension setRagQuery + setRagDocuments (unavoidable since
 *   store lacks a batch RAG setter, but only fires for dims with sources)
 */
export function applySessionReportsToStore(
  allReports: Record<string, Record<string, string>>,
  allProgress: Record<string, DimensionProgressItem>,
  allRagSources: Record<string, { query: string; documents: SessionRagDocument[] }>,
): void {
  const store = usePlanningStore.getState();

  if (Object.keys(allReports).length > 0) {
    store.setReports(allReports);
  }

  if (Object.keys(allProgress).length > 0) {
    store.setDimensionProgressBatch(allProgress);
  }

  for (const [dimKey, sources] of Object.entries(allRagSources)) {
    if (sources.query) {
      store.setRagQuery(dimKey, sources.query);
    }
    store.setRagDocuments(dimKey, sources.documents);
  }
}
