import { renderHook, waitFor } from '@testing-library/react';

import { planningApi } from '@/features/planning/api';
import { useDeliverySync } from '@/features/planning/hooks/useDelivery';
import { usePlanningStore } from '@/features/planning/store/planningStore';
import type { GISLayerConfig } from '@/types/message/message-types';

jest.mock('@/features/planning/api', () => ({
  planningApi: {
    getDelivery: jest.fn(),
    getRenderLayers: jest.fn(),
    getArtifact: jest.fn(),
  },
}));

const getDelivery = planningApi.getDelivery as jest.MockedFunction<typeof planningApi.getDelivery>;
const getRenderLayers = planningApi.getRenderLayers as jest.MockedFunction<typeof planningApi.getRenderLayers>;
const getArtifact = planningApi.getArtifact as jest.MockedFunction<typeof planningApi.getArtifact>;

describe('useDeliverySync', () => {
  beforeEach(() => {
    usePlanningStore.getState().resetConversation();
    jest.clearAllMocks();
  });

  it('clears stale layers when the authoritative map-layers projection is empty', async () => {
    const previousLayers: GISLayerConfig[] = [];
    usePlanningStore.setState({
      sessionId: 'session-empty-map',
      status: 'completed',
      gisLayers: { v1_previous_snapshot: previousLayers },
    });
    getDelivery.mockResolvedValue({
      schema_version: '1.0',
      session_id: 'session-empty-map',
      available: true,
      delivery_status: 'diagnostic_only',
      statutory_complete: false,
      snapshot_checksum: 'sha256:empty',
      deferral_summary: {},
      diagnostic_summary: {},
      deliverables: [],
      downloads: [],
    });
    getRenderLayers.mockResolvedValue({
      session_id: 'session-empty-map',
      layers: [],
      snapshot_checksum: 'sha256:empty',
      delivery_status: 'no_planning_output',
    });
    getArtifact.mockRejectedValue(new Error('render_layers is not present'));

    renderHook(() => useDeliverySync());

    await waitFor(() => {
      expect(getRenderLayers).toHaveBeenCalled();
      expect(usePlanningStore.getState().gisLayers).toEqual({});
    });
  });
});
