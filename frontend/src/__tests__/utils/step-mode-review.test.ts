import { DIMENSIONS_BY_LAYER } from '@/features/planning/config/dimensions';
import {
  getHighestActiveLayer,
  layerHasActivity,
} from '@/features/planning/utils/step-mode-review';

describe('step-mode-review', () => {
  it('layerHasActivity detects in-progress dimension text', () => {
    const dim = DIMENSIONS_BY_LAYER[3][0];
    expect(layerHasActivity(3, {
      layer1: {},
      layer2: {},
      layer3: { [dim]: 'x'.repeat(200) },
    }, {})).toBe(true);
  });

  it('getHighestActiveLayer prefers in-flight L3 over completed L2', () => {
    expect(getHighestActiveLayer(
      {
        layer1: Object.fromEntries(DIMENSIONS_BY_LAYER[1].map((d) => [d, 'x'.repeat(200)])),
        layer2: Object.fromEntries(DIMENSIONS_BY_LAYER[2].map((d) => [d, 'x'.repeat(200)])),
        layer3: {},
      },
      {},
      ['3_land_use'],
      2,
    )).toBe(3);
  });

  it('getHighestActiveLayer returns phase layer when no activity yet', () => {
    expect(getHighestActiveLayer(
      { layer1: {}, layer2: {}, layer3: {} },
      {},
      [],
      2,
    )).toBe(2);
  });
});
