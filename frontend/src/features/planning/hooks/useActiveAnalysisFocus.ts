import { useMemo } from 'react';

import { DIMENSIONS_BY_LAYER, getDimensionName } from '../config/dimensions';
import { usePlanningStore } from '../store';
import type { DimensionProgressItem } from '../types/base';

export type AnalysisFocusPhase = 'executing' | 'streaming' | 'queued' | 'paused';

export interface ActiveAnalysisFocus {
  progressKey: string;
  layer: number;
  dimKey: string;
  name: string;
  phase: AnalysisFocusPhase;
  status?: DimensionProgressItem['status'];
}

function parseProgressKey(progressKey: string) {
  const parts = progressKey.split('_');
  const layer = Number(parts[0]) || 1;
  const dimKey = parts.slice(1).join('_');
  return { layer, dimKey };
}

function buildFocus(
  progressKey: string,
  phase: AnalysisFocusPhase,
  dimensionProgress: Record<string, DimensionProgressItem>,
): ActiveAnalysisFocus {
  const { layer, dimKey } = parseProgressKey(progressKey);
  const progress = dimensionProgress[progressKey];
  return {
    progressKey,
    layer,
    dimKey,
    name: progress?.dimensionName || getDimensionName(dimKey),
    phase,
    status: progress?.status,
  };
}

export function useActiveAnalysisFocus(): ActiveAnalysisFocus | null {
  const status = usePlanningStore((state) => state.status);
  const executingDimensions = usePlanningStore((state) => state.executingDimensions);
  const dimensionProgress = usePlanningStore((state) => state.dimensionProgress);
  const streamingContent = usePlanningStore((state) => state.streamingContent);

  return useMemo(() => {
    if (executingDimensions.length > 0) {
      return buildFocus(executingDimensions[0], 'executing', dimensionProgress);
    }

    for (const [key, progress] of Object.entries(dimensionProgress)) {
      if (progress.status === 'streaming') {
        return buildFocus(key, 'streaming', dimensionProgress);
      }
    }

    for (const [key, content] of Object.entries(streamingContent)) {
      if (content && dimensionProgress[key]?.status !== 'completed') {
        return buildFocus(key, 'streaming', dimensionProgress);
      }
    }

    if (status === 'collecting') {
      const firstDim = DIMENSIONS_BY_LAYER[1][0];
      if (firstDim) {
        return buildFocus(`1_${firstDim}`, 'queued', dimensionProgress);
      }
    }

    if (status === 'planning' || status === 'revising' || status === 'collecting') {
      for (let layer = 1; layer <= 3; layer += 1) {
        for (const dimKey of DIMENSIONS_BY_LAYER[layer]) {
          const progressKey = `${layer}_${dimKey}`;
          const progress = dimensionProgress[progressKey];
          if (!progress || progress.status === 'pending') {
            return buildFocus(progressKey, 'queued', dimensionProgress);
          }
        }
      }
    }

    if (status === 'paused') {
      for (const [key, progress] of Object.entries(dimensionProgress)) {
        if (progress.status === 'streaming') {
          return buildFocus(key, 'paused', dimensionProgress);
        }
      }
    }

    return null;
  }, [dimensionProgress, executingDimensions, status, streamingContent]);
}
