import type { GISLayerConfig } from '@/types/message/message-types';

export const ROAD_ACTION_LABELS: Record<string, string> = {
  new: '规划新建',
  widen: '规划拓宽',
  harden: '规划硬化',
  repair: '规划修复',
  reuse_existing: '利用现状',
  planned: '规划道路',
};

export const ROAD_ACTION_COLORS: Record<string, { stroke: string; width: number }> = {
  new: { stroke: '#D73027', width: 5.5 },
  widen: { stroke: '#F28E2B', width: 5 },
  harden: { stroke: '#7B61A8', width: 4.5 },
  repair: { stroke: '#1B9E77', width: 4.5 },
  reuse_existing: { stroke: '#4C78A8', width: 3.5 },
  planned: { stroke: '#D73027', width: 5 },
};

export function getRoadActionKey(properties: Record<string, unknown>): string {
  const action = String(
    properties.construction_action ?? properties.road_action ?? properties.action ?? 'planned',
  ).trim();
  return action || 'planned';
}

export function getRoadActionLabel(properties: Record<string, unknown>): string {
  const explicit = String(properties.action_label ?? '').trim();
  if (explicit) return explicit;
  return ROAD_ACTION_LABELS[getRoadActionKey(properties)] || '规划道路';
}

export function getRoadLabelText(properties: Record<string, unknown>): string {
  const routeName = String(properties.route_name ?? properties.project_name ?? '').trim();
  const actionLabel = getRoadActionLabel(properties);
  if (routeName && actionLabel) return `${routeName} · ${actionLabel}`;
  return routeName || actionLabel;
}

export function getRoadLineColor(properties: Record<string, unknown>, layer?: GISLayerConfig): string {
  const color = String(properties.color ?? properties.stroke ?? '').trim();
  if (color) return color;
  const action = getRoadActionKey(properties);
  const actionStyles = layer?.style?.actionStyles;
  if (actionStyles && typeof actionStyles === 'object') {
    const style = (actionStyles as Record<string, Record<string, unknown>>)[action];
    const fromStyle = String(style?.color ?? '').trim();
    if (fromStyle) return fromStyle;
  }
  return ROAD_ACTION_COLORS[action]?.stroke || ROAD_ACTION_COLORS.planned.stroke;
}

export function getRoadLineWidth(properties: Record<string, unknown>, layer?: GISLayerConfig): number {
  const weight = Number(properties.weight);
  if (Number.isFinite(weight) && weight > 0) return weight;
  const action = getRoadActionKey(properties);
  const actionStyles = layer?.style?.actionStyles;
  if (actionStyles && typeof actionStyles === 'object') {
    const style = (actionStyles as Record<string, Record<string, unknown>>)[action];
    const fromStyle = Number(style?.width);
    if (Number.isFinite(fromStyle) && fromStyle > 0) return fromStyle;
  }
  return ROAD_ACTION_COLORS[action]?.width || ROAD_ACTION_COLORS.planned.width;
}

export function isRoadPlanningLayer(layer: GISLayerConfig): boolean {
  const role = String(layer.metadata?.displayRole || '');
  return layer.layerType === 'planned_road'
    || role.includes('road')
    || layer.layerName === '现状道路'
    || (layer.layerName === 'road' && Boolean(layer.metadata?.path));
}
