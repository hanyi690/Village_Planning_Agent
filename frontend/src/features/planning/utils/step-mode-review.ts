import { DIMENSIONS_BY_LAYER } from '../config/dimensions';

const MIN_REPORT_CHARS = 120;

export type LayerReports = {
  layer1: Record<string, string>;
  layer2: Record<string, string>;
  layer3: Record<string, string>;
};

export function layerHasActivity(
  layer: 1 | 2 | 3,
  reports: LayerReports,
  dimensionProgress: Record<string, { status?: string }>,
): boolean {
  const dims = DIMENSIONS_BY_LAYER[layer] || [];
  const layerKey = `layer${layer}` as keyof LayerReports;
  const layerReports = reports[layerKey] ?? {};

  return dims.some((dimKey) => {
    const text = layerReports[dimKey] ?? '';
    const progressKey = `${layer}_${dimKey}`;
    const progress = dimensionProgress[progressKey];
    return (
      text.length >= MIN_REPORT_CHARS
      || progress?.status === 'streaming'
      || progress?.status === 'completed'
    );
  });
}

/** Highest layer with phase, reports, progress, or in-flight execution. */
export function getHighestActiveLayer(
  reports: LayerReports,
  dimensionProgress: Record<string, { status?: string }>,
  executingDimensions: string[],
  phaseLayer: number | null,
): number {
  let highest = phaseLayer ?? 0;
  for (let layer = 1; layer <= 3; layer++) {
    if (layerHasActivity(layer as 1 | 2 | 3, reports, dimensionProgress)) {
      highest = Math.max(highest, layer);
    }
    if (executingDimensions.some((key) => key.startsWith(`${layer}_`))) {
      highest = Math.max(highest, layer);
    }
  }
  return highest;
}
