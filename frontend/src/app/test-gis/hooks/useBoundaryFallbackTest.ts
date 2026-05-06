'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { dataApi } from '@/lib/api/data-api';

// ============================================
// Types
// ============================================

interface FallbackHistoryEntry {
  strategy: string;
  success: boolean;
  reason: string;
  stats?: Record<string, unknown>;
}

interface BoundaryFallbackState {
  loading: boolean;
  error: string | null;
  geojson: Record<string, unknown> | null;
  strategyUsed: string | null;
  fallbackHistory: FallbackHistoryEntry[];
  warnings: string[];
  stats: Record<string, unknown> | null;
}

interface BoundaryFallbackOptions {
  skipUserUpload?: boolean;
  forceBbox?: boolean;
}

export function useBoundaryFallbackTest() {
  const [state, setState] = useState<BoundaryFallbackState>({
    loading: false,
    error: null,
    geojson: null,
    strategyUsed: null,
    fallbackHistory: [],
    warnings: [],
    stats: null,
  });

  const abortControllerRef = useRef<AbortController | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const runTest = useCallback(async (
    villageName?: string,
    options?: BoundaryFallbackOptions
  ) => {
    // Cancel previous request if still pending
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    // Prevent duplicate requests while loading
    if (state.loading) return;

    // Create new AbortController for this request
    abortControllerRef.current = new AbortController();

    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const result = await dataApi.testBoundaryFallback(villageName, {
        skip_user_upload: options?.skipUserUpload,
        force_bbox: options?.forceBbox,
      });

      // Check if request was aborted
      if (abortControllerRef.current?.signal.aborted) return;

      if (result.success) {
        setState({
          loading: false,
          error: null,
          geojson: result.geojson ?? null,
          strategyUsed: result.strategy_used ?? null,
          fallbackHistory: result.fallback_history ?? [],
          warnings: result.warnings ?? [],
          stats: result.stats ?? null,
        });
      } else {
        setState(prev => ({
          ...prev,
          loading: false,
          error: result.error ?? '生成失败',
          fallbackHistory: result.fallback_history ?? [],
        }));
      }
    } catch (err) {
      // Ignore abort errors
      if (err instanceof Error && err.name === 'AbortError') return;

      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      setState(prev => ({
        ...prev,
        loading: false,
        error: errorMessage,
      }));
    }
  }, [state.loading]);

  const clearTest = useCallback(() => {
    setState({
      loading: false,
      error: null,
      geojson: null,
      strategyUsed: null,
      fallbackHistory: [],
      warnings: [],
      stats: null,
    });
  }, []);

  return { ...state, runTest, clearTest };
}