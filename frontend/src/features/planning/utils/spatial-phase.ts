import type { HumanReviewItem } from '../api/types';

const SPATIAL_PHASES = new Set([
  'post_l3',
  'target_projection',
  'ground',
  'select',
  'execute',
  'validate',
  'reconcile',
  'deliver',
]);

export function isSpatialWorkflowPhase(phase: string | null | undefined): boolean {
  if (!phase) return false;
  return SPATIAL_PHASES.has(phase) || phase === 'completed';
}

export function pausedStageToLayer(pausedStage: string | null | undefined): number | null {
  const stage = String(pausedStage || '').trim().toLowerCase();
  if (stage === 'l1' || stage === 'layer1') return 1;
  if (stage === 'l2' || stage === 'layer2') return 2;
  if (stage === 'l3' || stage === 'layer3') return 3;
  return null;
}

export function isL3HumanReview(
  humanReview: {
    paused_stage?: string;
    items?: HumanReviewItem[] | Array<Record<string, unknown>>;
  } | null | undefined,
): boolean {
  if (!humanReview?.items?.length) return false;
  if (pausedStageToLayer(humanReview.paused_stage) === 3) return true;
  return humanReview.items.some((item) => {
    const stage = String((item as HumanReviewItem).stage || '').toLowerCase();
    return stage === 'l3' || stage === 'layer3';
  });
}

export function shouldAutoStartSpatialPolling(input: {
  phase: string;
  hasGisLayers: boolean;
  humanReviewPending?: boolean;
  postL3Status?: string | null;
}): boolean {
  if (input.hasGisLayers) return false;
  if (input.humanReviewPending) return false;
  if (input.postL3Status === 'auto_continue') return true;
  return isSpatialWorkflowPhase(input.phase);
}
