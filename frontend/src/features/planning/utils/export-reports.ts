import { DIMENSIONS_BY_LAYER, getDimensionName } from '../config/dimensions';
import { downloadBlob, getLayerDisplayName } from './download';

type LayerReports = {
  layer1: Record<string, string>;
  layer2: Record<string, string>;
  layer3: Record<string, string>;
};

function layerReportEntries(layer: number, reports: LayerReports) {
  const layerKey = `layer${layer}` as keyof LayerReports;
  const layerReports = reports[layerKey] || {};
  return (DIMENSIONS_BY_LAYER[layer as 1 | 2 | 3] || [])
    .map((dimKey) => ({
      dimension_key: dimKey,
      dimension_name: getDimensionName(dimKey),
      content: layerReports[dimKey] || '',
    }))
    .filter((item) => item.content.trim().length > 0);
}

export function exportLayerJsonClient(
  sessionId: string,
  layer: number,
  reports: LayerReports,
): string {
  const payload = {
    session_id: sessionId,
    layer,
    layer_name: getLayerDisplayName(layer),
    dimensions: layerReportEntries(layer, reports),
  };
  const filename = `session_${sessionId.slice(0, 8)}_L${layer}.json`;
  downloadBlob(
    new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }),
    filename,
  );
  return filename;
}

export function exportLayerMdClient(
  sessionId: string,
  layer: number,
  reports: LayerReports,
): string {
  const entries = layerReportEntries(layer, reports);
  const lines = [
    `# ${getLayerDisplayName(layer)}`,
    '',
    `> 会话 ${sessionId}`,
    '',
    ...entries.flatMap((item) => [
      `## ${item.dimension_name}`,
      '',
      item.content,
      '',
    ]),
  ];
  const filename = `session_${sessionId.slice(0, 8)}_L${layer}.md`;
  downloadBlob(new Blob([lines.join('\n')], { type: 'text/markdown' }), filename);
  return filename;
}

export function exportPlanningTextMdClient(
  sessionId: string,
  markdown: string,
  projectName: string,
): string {
  const safeName = (projectName || '村庄规划').replace(/[\\/:*?"<>|]/g, '_');
  const filename = `${safeName}_${sessionId.slice(0, 8)}.md`;
  downloadBlob(new Blob([markdown], { type: 'text/markdown' }), filename);
  return filename;
}
