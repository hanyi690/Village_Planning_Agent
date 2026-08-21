import { DIMENSIONS_BY_LAYER } from '@/features/planning/config/dimensions';
import { usePlanningStore } from '@/features/planning/store/planningStore';

function fullLayerReports(layer: 1 | 2 | 3) {
  const dims = DIMENSIONS_BY_LAYER[layer];
  return Object.fromEntries(dims.map((dim) => [dim, 'x'.repeat(200)]));
}

const layer2CompleteState = {
  step_mode: true,
  phase: 'layer2',
  completedLayers: { 1: true, 2: true, 3: false },
  reports: {
    layer1: fullLayerReports(1),
    layer2: fullLayerReports(2),
    layer3: {},
  },
  dimensionProgress: {},
  executingDimensions: [] as string[],
  completedDimensions: {
    layer1: DIMENSIONS_BY_LAYER[1],
    layer2: DIMENSIONS_BY_LAYER[2],
    layer3: [] as string[],
  },
  layerDimensionCount: {
    1: DIMENSIONS_BY_LAYER[1].length,
    2: DIMENSIONS_BY_LAYER[2].length,
    3: DIMENSIONS_BY_LAYER[3].length,
  },
};

describe('planning store step-mode review inference', () => {
  beforeEach(() => {
    usePlanningStore.getState().resetConversation();
    usePlanningStore.getState().clearMessages();
  });

  it('does not infer L2 review while L3 is in progress', () => {
    const dim = DIMENSIONS_BY_LAYER[3][0];
    usePlanningStore.setState({
      step_mode: true,
      status: 'planning',
      phase: 'layer3',
      completedLayers: { 1: true, 2: true, 3: false },
      reports: {
        layer1: fullLayerReports(1),
        layer2: fullLayerReports(2),
        layer3: { [dim]: 'x'.repeat(200) },
      },
      dimensionProgress: {
        [`3_${dim}`]: {
          dimensionKey: dim,
          dimensionName: dim,
          layer: 3,
          status: 'completed',
          wordCount: 200,
        },
      },
      executingDimensions: [],
      completedDimensions: {
        layer1: DIMENSIONS_BY_LAYER[1],
        layer2: DIMENSIONS_BY_LAYER[2],
        layer3: [dim],
      },
      layerDimensionCount: {
        1: DIMENSIONS_BY_LAYER[1].length,
        2: DIMENSIONS_BY_LAYER[2].length,
        3: DIMENSIONS_BY_LAYER[3].length,
      },
    });

    usePlanningStore.getState().handleSSEEvent({
      type: 'execution_resumed',
      data: { seq: 1 },
    });

    expect(usePlanningStore.getState().pendingReviewLayer).toBeNull();
  });

  it('infers L2 review when paused at the layer boundary', () => {
    usePlanningStore.setState({
      ...layer2CompleteState,
      status: 'paused',
      previous_layer: 2,
    });

    usePlanningStore.getState().handleSSEEvent({
      type: 'layer_paused',
      data: { layer: 2, layer_name: 'Strategy', seq: 2 },
    });

    expect(usePlanningStore.getState().pendingReviewLayer).toBe(2);
  });

  it('does not re-infer L2 review while backend resume is in flight', () => {
    usePlanningStore.setState({
      ...layer2CompleteState,
      status: 'planning',
      previous_layer: 2,
    });

    usePlanningStore.getState().handleSSEEvent({
      type: 'execution_resumed',
      data: { seq: 3 },
    });

    expect(usePlanningStore.getState().pendingReviewLayer).toBeNull();
  });
});
