import { useEffect, useMemo, useRef } from 'react';

import { DIMENSIONS_BY_LAYER } from '../config/dimensions';
import { AgentPhase } from '../constants';
import { usePlanningStore } from '../store';

type CompletedDimensions = {
  layer1: string[];
  layer2: string[];
  layer3: string[];
};

function countCompletedDimensions(completedDimensions: CompletedDimensions): number {
  return ([1, 2, 3] as const).reduce((sum, layer) => {
    const layerKey = `layer${layer}` as keyof CompletedDimensions;
    return sum + (completedDimensions[layerKey]?.length ?? 0);
  }, 0);
}

function areAllLayersComplete(completedDimensions: CompletedDimensions): boolean {
  return ([1, 2, 3] as const).every((layer) => {
    const done = completedDimensions[`layer${layer}`]?.length ?? 0;
    const total = DIMENSIONS_BY_LAYER[layer]?.length ?? 0;
    return total > 0 && done >= total;
  });
}

export function useAnalysisCompletion() {
  const sessionId = usePlanningStore((state) => state.sessionId);
  const status = usePlanningStore((state) => state.status);
  const phase = usePlanningStore((state) => state.phase);
  const completedDimensions = usePlanningStore((state) => state.completedDimensions);
  const latchedCompleteRef = useRef(false);

  useEffect(() => {
    latchedCompleteRef.current = false;
  }, [sessionId]);

  return useMemo(() => {
    const totalDimensions = ([1, 2, 3] as const).reduce(
      (sum, layer) => sum + (DIMENSIONS_BY_LAYER[layer]?.length ?? 0),
      0,
    );
    const completedCount = countCompletedDimensions(completedDimensions);
    const allLayersComplete = areAllLayersComplete(completedDimensions);

    const isCompleteNow = status === 'completed'
      || phase === AgentPhase.COMPLETED
      || allLayersComplete
      || (totalDimensions > 0 && completedCount >= totalDimensions);

    if (isCompleteNow) {
      latchedCompleteRef.current = true;
    } else if (!sessionId || status === 'idle' || status === 'failed') {
      latchedCompleteRef.current = false;
    }

    const isComplete = latchedCompleteRef.current || isCompleteNow;

    return {
      totalDimensions,
      completedDimensions: completedCount,
      isComplete,
      progressPercent: totalDimensions > 0
        ? Math.min(100, Math.round((completedCount / totalDimensions) * 100))
        : 0,
    };
  }, [completedDimensions, phase, sessionId, status]);
}
