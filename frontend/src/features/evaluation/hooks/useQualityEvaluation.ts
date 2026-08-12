import { useCallback, useEffect, useRef, useState } from 'react';

import {
  evaluationApi,
  type EvaluationResult,
} from '@/features/evaluation/api';

const EVALUATION_TIMEOUT_MS = 120_000;

export interface QualityEvaluationState {
  result: EvaluationResult | null;
  loading: boolean;
  error: string;
  runEvaluation: () => Promise<void>;
  loadExisting: () => Promise<void>;
  resetError: () => void;
}

export function useQualityEvaluation(sessionId: string): QualityEvaluationState {
  const [result, setResult] = useState<EvaluationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const runAbortRef = useRef<AbortController | null>(null);
  const runTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearRunTimers = useCallback(() => {
    if (runTimeoutRef.current) {
      clearTimeout(runTimeoutRef.current);
      runTimeoutRef.current = null;
    }
    runAbortRef.current = null;
  }, []);

  const loadExisting = useCallback(async () => {
    if (!sessionId) {
      setResult(null);
      return;
    }

    try {
      const status = await evaluationApi.getStatus(sessionId);
      if (status.has_result) {
        const data = await evaluationApi.getResults(sessionId);
        setResult(data);
      } else {
        setResult(null);
      }
    } catch {
      setResult(null);
    }
  }, [sessionId]);

  useEffect(() => {
    void loadExisting();
  }, [loadExisting]);

  useEffect(() => {
    return () => {
      runAbortRef.current?.abort();
      clearRunTimers();
    };
  }, [clearRunTimers, sessionId]);

  const runEvaluation = useCallback(async () => {
    if (!sessionId || loading) return;

    runAbortRef.current?.abort();
    clearRunTimers();

    const controller = new AbortController();
    runAbortRef.current = controller;
    runTimeoutRef.current = setTimeout(() => controller.abort(), EVALUATION_TIMEOUT_MS);

    setLoading(true);
    setError('');

    try {
      const response = await evaluationApi.run(sessionId, controller.signal);
      if (response.result) {
        setResult(response.result);
      } else {
        const fresh = await evaluationApi.getResults(sessionId);
        setResult(fresh);
      }
    } catch (err) {
      if (controller.signal.aborted) {
        setError('评估超时或已取消，请检查后端是否运行后重试');
      } else {
        setError(err instanceof Error ? err.message : '评估失败');
      }
    } finally {
      clearRunTimers();
      setLoading(false);
    }
  }, [clearRunTimers, loading, sessionId]);

  const resetError = useCallback(() => setError(''), []);

  return {
    result,
    loading,
    error,
    runEvaluation,
    loadExisting,
    resetError,
  };
}
