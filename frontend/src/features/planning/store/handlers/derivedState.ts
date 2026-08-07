import type { PlanningState } from '../planningStore';
import { AgentPhase, getLayerPhase } from '../../constants';
import { getDimensionsByLayer } from '../../config/dimensions';

export interface Reports {
  layer1: Record<string, string>;
  layer2: Record<string, string>;
  layer3: Record<string, string>;
}

export interface CompletedDimensions {
  layer1: string[];
  layer2: string[];
  layer3: string[];
}

export function phaseToLayer(phase: string): number | null {
  const mapping: Record<string, number> = {
    [AgentPhase.INIT]: 0,
    [AgentPhase.LAYER1]: 1,
    [AgentPhase.LAYER2]: 2,
    [AgentPhase.LAYER3]: 3,
    [AgentPhase.COMPLETED]: 3,
  };
  return mapping[phase] ?? null;
}

export function deriveCompletedDimensions(
  reports: Reports,
): CompletedDimensions {
  return {
    layer1: Object.keys(reports.layer1 || {}),
    layer2: Object.keys(reports.layer2 || {}),
    layer3: Object.keys(reports.layer3 || {}),
  };
}

function shallowEqualCompletedDimensions(
  incoming: CompletedDimensions,
  current: CompletedDimensions,
): boolean {
  const layers = ['layer1', 'layer2', 'layer3'] as const;
  for (const layer of layers) {
    const a = incoming[layer] || [];
    const b = current[layer] || [];
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      if (a[i] !== b[i]) return false;
    }
  }
  return true;
}

export function deriveUIStateInStore(state: PlanningState): void {
  const newCompletedDimensions = deriveCompletedDimensions(state.reports);

  if (
    !shallowEqualCompletedDimensions(
      newCompletedDimensions,
      state.completedDimensions,
    )
  ) {
    state.completedDimensions = newCompletedDimensions;
  }

  const totalDims = (layer: number) =>
    state.layerDimensionCount[layer] || getDimensionsByLayer(layer).length;
  state.completedLayers = {
    1: state.completedDimensions.layer1.length >= totalDims(1) && totalDims(1) > 0,
    2: state.completedDimensions.layer2.length >= totalDims(2) && totalDims(2) > 0,
    3: state.completedDimensions.layer3.length >= totalDims(3) && totalDims(3) > 0,
  };

  state.isPaused = state.status === 'paused';
  const pauseLayer = state.interruptInfo?.layer || (state.lastPauseLayer > 0 ? state.lastPauseLayer : state.previous_layer);
  state.pendingReviewLayer =
    state.isPaused && pauseLayer > 0 ? pauseLayer : null;

  const layerFromPhase = phaseToLayer(state.phase);
  state.currentLayer = state.pendingReviewLayer || layerFromPhase;
  state.currentPhase = state.currentLayer
    ? getLayerPhase(state.currentLayer)
    : 'idle';
}