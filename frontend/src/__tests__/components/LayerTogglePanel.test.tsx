import { render, screen } from '@testing-library/react';

import LayerTogglePanel from '@/features/planning/components/gis/LayerTogglePanel';
import type { GISLayerConfig } from '@/types/message/message-types';

const geojson: GISLayerConfig['geojson'] = {
  type: 'FeatureCollection',
  features: [{
    type: 'Feature',
    properties: {},
    geometry: {
      type: 'Polygon',
      coordinates: [[[116, 24], [116.1, 24], [116.1, 24.1], [116, 24]]],
    },
  }],
};

function renderPanel(metadata: GISLayerConfig['metadata']) {
  render(<LayerTogglePanel
    layers={[{
      geojson,
      layerType: 'planning_scope',
      layerName: '规划范围',
      metadata,
    }]}
    visibleTypes={new Set(['planning_scope'])}
    onToggle={jest.fn()}
  />);
}

describe('LayerTogglePanel planning evidence', () => {
  it('does not claim L1-L3 evidence for unrelated legacy metadata', () => {
    renderPanel({ generation_mode: 'legacy' });

    expect(screen.queryByText(/依据/)).not.toBeInTheDocument();
  });

  it('shows report evidence only when the new planning basis exists', () => {
    renderPanel({
      planningBasis: {
        report_count: 28,
        content_characters: 11198,
        source_layers: [1, 2, 3],
      },
      dataQuality: { status: 'ready' },
      validation: { status: 'pass', violations: [] },
    });

    expect(screen.getByText(/依据 L1\/L2\/L3 · 28 项成果/)).toBeInTheDocument();
    expect(screen.getByText('真实地块齐全')).toBeInTheDocument();
    expect(screen.getByText('校核通过')).toBeInTheDocument();
  });
});
