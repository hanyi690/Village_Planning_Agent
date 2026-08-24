import { planningApi } from '@/features/planning/api';
import { fetchCurrentSourceLayers } from '@/features/planning/utils/offline-basemap';

describe('catalog-backed current layer cache', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('deduplicates concurrent requests per village without sharing another village cache', async () => {
    const requests: string[] = [];
    jest.spyOn(planningApi, 'getCurrentSourceLayers').mockImplementation(async (villageName) => {
      const resolvedVillage = villageName ?? '';
      requests.push(resolvedVillage);
      return {
        schema_version: '1.0',
        village_name: resolvedVillage,
        source: 'data_catalog',
        center: null,
        layers: [],
        rasters: [],
        diagnostics: [],
      };
    });

    await Promise.all([
      fetchCurrentSourceLayers('村庄 A'),
      fetchCurrentSourceLayers('村庄 A'),
    ]);
    await fetchCurrentSourceLayers('村庄 B');

    expect(requests).toEqual(['村庄 A', '村庄 B']);
  });
});
