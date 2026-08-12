/**
 * GIS Constants Module
 *
 * Synchronized with backend: src/tools/core/map_renderer.py
 * Contains tile sources, planning styles, and type definitions.
 */

import type { GISLayerConfig } from '@/types/message/message-types';

// Tile source identifiers
export const TILE_SOURCES = {
  AMAP: 'amap',
  TIANDITU: 'tianditu',
  GEOQ: 'geoq',
  OSM: 'osm',
} as const;

export type TileSourceType = typeof TILE_SOURCES[keyof typeof TILE_SOURCES];

export function normalizeTileSource(source?: string | null): TileSourceType {
  const normalized = String(source ?? '').trim().toLowerCase();
  if (!normalized) return TILE_SOURCES.AMAP;
  if (normalized === 'gaode' || normalized === '高德') return TILE_SOURCES.AMAP;
  if (normalized === 'openstreetmap') return TILE_SOURCES.OSM;
  if (
    normalized === TILE_SOURCES.AMAP
    || normalized === TILE_SOURCES.TIANDITU
    || normalized === TILE_SOURCES.GEOQ
    || normalized === TILE_SOURCES.OSM
  ) {
    return normalized as TileSourceType;
  }
  return TILE_SOURCES.AMAP;
}

// Tianditu base tile layer types
export const TIANDITU_TILE_LAYERS = {
  VECTOR: 'vec',   // Vector map (planning法定底图)
  IMAGE: 'img',    // Satellite image
  TERRAIN: 'ter',  // Terrain hillshade
} as const;

// Tianditu annotation layer types
export const TIANDITU_ANNOTATION_LAYERS = {
  VECTOR: 'cva',   // Vector annotation
  IMAGE: 'cia',    // Image annotation
  TERRAIN: 'cta',  // Terrain annotation
} as const;

// Base map type configuration
export const BASE_MAP_TYPES = {
  vector: { label: '矢量线划', tile: 'vec', annotation: 'cva' },
  image: { label: '卫星影像', tile: 'img', annotation: 'cia' },
  terrain: { label: '地形晕渲', tile: 'ter', annotation: 'cta' },
} as const;

export type BaseMapType = keyof typeof BASE_MAP_TYPES;

// Planning color styles (synchronized with backend PLANNING_STYLES)
export const PLANNING_COLORS = {
  // Boundary styles (行政边界 - 线状渲染，无填充)
  boundary: {
    '行政边界': { stroke: '#333333', width: 2, fillOpacity: 0 },
  },
  planning_scope: {
    '规划村范围（GHCFW）': { stroke: '#17202a', width: 2.5, fillOpacity: 0 },
  },
  final_landuse: {
    '农业用地': { fill: '#F5F8DC', stroke: '#8B7355' },
    '生态用地': { fill: '#68B167', stroke: '#2E8B57' },
    '村庄建设用地': { fill: '#EF8D7B', stroke: '#B84D3D' },
    '交通与水利用地': { fill: '#8EB6D8', stroke: '#416B8C' },
  },
  land_use_zone: {
    'V 村庄建设空间': { fill: '#EF8D7B', stroke: '#B84D3D' },
    'N 非村庄建设空间': { fill: '#AEB8C4', stroke: '#647182' },
    'E 非建设空间': { fill: '#8FCF85', stroke: '#3F7D43' },
  },
  construction_control: {
    '允许建设区': { fill: '#EE7B67', stroke: '#B84736' },
    '限制建设区': { fill: '#D7DFA2', stroke: '#87943D' },
    '有条件建设区': { fill: '#F2C15B', stroke: '#B77900' },
    '禁止建设区': { fill: '#4F9F73', stroke: '#246747' },
  },
  // Function zone styles (polygon fill) - GB/T 21010 + 市级国土空间规划制图规范配色
  function_zone: {
    // 耕地 RGB(245,248,220) - 农业空间黄色系
    '农业用地': { fill: '#F5F8DC', stroke: '#8B7355' },
    // 园地 RGB(191,233,170)
    // 林地 RGB(104,177,103) - 生态空间绿色冷色系
    '生态绿地': { fill: '#68B167', stroke: '#2E8B57' },
    // 草地 RGB(205,245,122)
    // 城镇住宅 RGB(255,211,128) / 农村宅基地 RGB(255,211,128) - 城镇空间红色暖色系
    '居住用地': { fill: '#FFD380', stroke: '#B8860B' },
    // 商业服务业 RGB(255,0,0)
    '商业用地': { fill: '#FF0000', stroke: '#CC0000' },
    // 工业用地 RGB(187,150,116)
    '产业用地': { fill: '#BB9674', stroke: '#8B6914' },
    // 公共管理与公共服务 - 蓝色系
    '公共服务用地': { fill: '#4A90D9', stroke: '#1E3A5F' },
    // 交通运输 RGB(0,0,255)
    '交通用地': { fill: '#0000FF', stroke: '#0066CC' },
    // 水域 RGB(135,206,235)
    '水域': { fill: '#87CEEB', stroke: '#4169E1' },
  },
  // Facility point styles (marker colors by status)
  facility_point: {
    '现状保留': { fill: 'green', stroke: '#006400' },
    // Red instead of blue: project/facility annotations are marked 规划新建 in
    // gis-normalize, and a sea of blue dots confused users.  Red matches the
    // planning-drawing convention for new facilities.
    '规划新建': { fill: '#EF4444', stroke: '#991B1B' },
    '规划改扩建': { fill: 'orange', stroke: '#CC8400' },
    '规划迁建': { fill: 'purple', stroke: '#800080' },
  },
  hazard_point: {
    '大型': { fill: '#B91C1C', stroke: '#7F1D1D' },
    '中型': { fill: '#EF4444', stroke: '#991B1B' },
    '小型': { fill: '#F97316', stroke: '#C2410C' },
    '未分级': { fill: '#F59E0B', stroke: '#B45309' },
  },
  // Development axis styles (line styles)
  development_axis: {
    primary: { stroke: '#FF0000', width: 3, label: '发展主轴' },
    secondary: { stroke: '#00AA00', width: 2, label: '发展副轴' },
    traffic: { stroke: '#0000FF', width: 3, label: '交通主轴' },
    corridor: { stroke: '#00FF00', width: 2, label: '景观轴线' },
  },
  // Sensitivity zone styles (polygon fill)
  sensitivity_zone: {
    high: { fill: '#FF0000', stroke: '#CC0000', label: '高敏感区' },
    medium: { fill: '#FFFF00', stroke: '#CCCC00', label: '中敏感区' },
    low: { fill: '#00FF00', stroke: '#00CC00', label: '低敏感区' },
    buffer: { fill: '#FFA500', stroke: '#CC8400', label: '缓冲区' },
  },
  // Isochrone styles (time-based)
  isochrone: {
    '5min': { fill: '#00FF00', stroke: '#00CC00' },
    '10min': { fill: '#FFFF00', stroke: '#CCCC00' },
    '15min': { fill: '#FFA500', stroke: '#CC8400' },
  },
  // Settlement zone styles (居民点分类)
  settlement_zone: {
    '保留村庄': { fill: '#228B22', stroke: '#006400' },
    '迁并村庄': { fill: '#FF6B6B', stroke: '#CC0000' },
    '新建村庄': { fill: '#4A90D9', stroke: '#1E3A5F' },
  },
  // Planning zone styles (规划分区 — 与现状功能区色系不同)
  planning_zone: {
    '农田保护区': { fill: '#FFE4B5', stroke: '#DAA520' },
    '村庄建设区': { fill: '#FF6347', stroke: '#CC4F39' },
    '生态保护区': { fill: '#2E8B57', stroke: '#1B5E20' },
    '一般农业区': { fill: '#98FB98', stroke: '#66CD66' },
    '生态林': { fill: '#5D9473', stroke: '#32654B' },
    '商品林': { fill: '#7EA96B', stroke: '#557C45' },
    '耕地': { fill: '#E8D18A', stroke: '#B19136' },
    '园地': { fill: '#C7D996', stroke: '#8AA354' },
    '宅基地': { fill: '#E9A092', stroke: '#BD6758' },
    '对外交通用地': { fill: '#9EB7D5', stroke: '#5B789B' },
    '公共设施用地': { fill: '#BDA8D4', stroke: '#80659F' },
    '村庄内部道路用地': { fill: '#C9B48A', stroke: '#8D7651' },
    '水域': { fill: '#8CC7E8', stroke: '#4386AE' },
    '水利设施用地': { fill: '#9AB7D8', stroke: '#5A789C' },
  },
  // Infrastructure styles (基础设施)
  infrastructure: {
    '县道': { stroke: '#555555', width: 2, label: '县道' },
    '乡道': { stroke: '#808080', width: 1.5, label: '乡道' },
    '道路': { stroke: '#666666', width: 2, label: '道路' },
    '河流': { stroke: '#00BFFF', width: 2.5, label: '河流' },
  },
  // Recommended road-plan segments (Stage 5 output)
  planned_road: {
    new: { stroke: '#D73027', width: 5.5, label: '规划新建' },
    widen: { stroke: '#F28E2B', width: 5, label: '规划拓宽' },
    harden: { stroke: '#7B61A8', width: 4.5, label: '规划硬化' },
    repair: { stroke: '#1B9E77', width: 4.5, label: '规划修复' },
    reuse_existing: { stroke: '#4C78A8', width: 3.5, label: '利用现状' },
    planned: { stroke: '#D73027', width: 5, label: '规划道路' },
  },
} as const;

// Default fallback colors
export const DEFAULT_COLORS = { fill: '#CCCCCC', stroke: '#666666' };

// Type helper for feature colors
export type FeatureColors = { fill: string; stroke: string };
export type LineColors = { stroke: string; width: number };

// Layer type definition (keys of PLANNING_COLORS)
export type LayerType = keyof typeof PLANNING_COLORS;

// Layer type Chinese labels (single source, used by MapView + LegendPanel)
export const LAYER_TYPE_LABELS: Record<LayerType, string> = {
  boundary: '行政边界',
  planning_scope: '规划村范围',
  final_landuse: '期末地类图斑',
  land_use_zone: '土地用途分区',
  construction_control: '建设用地管制区',
  function_zone: '功能区',
  facility_point: '设施点',
  hazard_point: '地质灾害点',
  sensitivity_zone: '敏感区',
  infrastructure: '基础设施',
  planned_road: '规划道路',
  isochrone: '等时圈',
  planning_zone: '规划分区',
  development_axis: '发展轴',
  settlement_zone: '居民点分类',
};

// Ordered category fields used by both map rendering and the dynamic legend.
// Keeping this in one place prevents a layer from being colored by one field
// while its legend is grouped by another.
export const LAYER_CATEGORY_FIELDS: Partial<Record<LayerType, readonly string[]>> = {
  // zone_type first: it holds the four broad categories (农业用地/生态用地/…)
  // that the final_landuse palette is keyed by.  GHYTMC holds detailed codes
  // (耕地/园地/…) that do not match the palette and previously fell back to gray.
  final_landuse: ['zone_type', 'GHYTMC', 'assigned_zone'],
  land_use_zone: ['YTFQMC', 'zone_type'],
  construction_control: ['GZFQMC', 'zone_type'],
  function_zone: ['zone_type', 'land_use'],
  planning_zone: ['assigned_zone', 'zone_type', 'GHYTMC'],
  facility_point: ['status', 'facility_type'],
  hazard_point: ['hazard_scale', 'hazard_type'],
  sensitivity_zone: ['sensitivity_level', 'protection_type'],
  infrastructure: ['infra_type', 'RN'],
  planned_road: ['construction_action', 'road_action', 'action'],
  development_axis: ['axis_type'],
  isochrone: ['time_minutes'],
  settlement_zone: ['zone_type', 'settlement_type'],
};

export const LAYER_CATEGORY_LABELS: Record<string, string> = {
  existing: '现状保留',
  new: '规划新建',
  planned: '规划新建',
  expansion: '规划改扩建',
  relocation: '规划迁建',
  high: '高敏感区',
  medium: '中敏感区',
  low: '低敏感区',
  buffer: '缓冲区',
  primary: '发展主轴',
  secondary: '发展副轴',
  traffic: '交通主轴',
  corridor: '景观轴线',
  road: '道路',
  widen: '规划拓宽',
  harden: '规划硬化',
  repair: '规划修复',
  reuse_existing: '利用现状',
  construction_zone: '现状建设用地边界',
};

// Detailed landuse codes → broad categories (shared by normalize, map, legend)
export const LANDUSE_TO_ZONE: Record<string, string> = {
  '耕地': '农业用地',
  '园地': '农业用地',
  '水田': '农业用地',
  '旱地': '农业用地',
  '设施农用地': '农业用地',
  '林地': '生态用地',
  '商品林': '生态用地',
  '生态林': '生态用地',
  '草地': '生态用地',
  '湿地': '生态用地',
  '田坎': '生态用地',
  '裸土地': '生态用地',
  '其他土地': '生态用地',
  '水域': '交通与水利用地',
  '交通运输用地': '交通与水利用地',
  '水利设施用地': '交通与水利用地',
  '村庄内部道路用地': '交通与水利用地',
  '对外交通用地': '交通与水利用地',
  '城镇住宅用地': '村庄建设用地',
  '农村宅基地': '村庄建设用地',
  '宅基地': '村庄建设用地',
  '商业服务业设施用地': '村庄建设用地',
  '商业用地': '村庄建设用地',
  '工业用地': '村庄建设用地',
  '公共管理与公共服务用地': '村庄建设用地',
  '公共服务用地': '村庄建设用地',
  '公共设施用地': '村庄建设用地',
  '产业用地': '村庄建设用地',
  '居住用地': '村庄建设用地',
  '特殊用地': '村庄建设用地',
};

export function classifyLanduseZone(properties: Record<string, unknown>): string | undefined {
  const value = String(properties.GHYTMC ?? properties.DLMC ?? properties.SDDLMC ?? '').trim();
  if (!value) return undefined;
  if (LANDUSE_TO_ZONE[value]) return LANDUSE_TO_ZONE[value];
  for (const [key, zone] of Object.entries(LANDUSE_TO_ZONE)) {
    if (value.includes(key)) return zone;
  }
  return undefined;
}

export function resolveCategoryValue(
  properties: Record<string, unknown>,
  fields: readonly string[],
): string | undefined {
  for (const field of fields) {
    const value = properties[field];
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      return String(value).trim();
    }
  }
  return undefined;
}

const STYLE_DRIVEN_DISPLAY_ROLES = new Set([
  'control_reference',
  'spatial_structure',
  'road_review_corridor',
  'historical_planned_road_reference',
]);

export function isStyleDrivenLayer(
  layer: Pick<GISLayerConfig, 'metadata' | 'layerType' | 'style'>,
): boolean {
  const role = String(layer.metadata?.displayRole || '');
  return STYLE_DRIVEN_DISPLAY_ROLES.has(role);
}

function legendGeometryType(layerType: LayerType): LegendItem['type'] {
  if (
    layerType === 'boundary'
    || layerType === 'planning_scope'
    || layerType === 'development_axis'
    || layerType === 'infrastructure'
    || layerType === 'planned_road'
  ) {
    return 'line';
  }
  if (layerType === 'facility_point' || layerType === 'hazard_point') {
    return 'point';
  }
  return 'polygon';
}

function getRenderingPalette(
  layerType: LayerType,
  layer?: Pick<GISLayerConfig, 'metadata' | 'layerName'>,
): Record<string, Record<string, unknown>> {
  const role = String(layer?.metadata?.displayRole || '');
  if (
    layerType === 'function_zone'
    && role !== 'control_reference'
    && role !== 'spatial_structure'
  ) {
    return PLANNING_COLORS.final_landuse as Record<string, Record<string, unknown>>;
  }
  return PLANNING_COLORS[layerType] as Record<string, Record<string, unknown>>;
}

function getCategoryFields(layerType: LayerType, layer?: GISLayerConfig): readonly string[] {
  const role = String(layer?.metadata?.displayRole || '');
  if (layerType === 'function_zone') {
    if (role === 'control_reference' || role === 'spatial_structure') return [];
    return LAYER_CATEGORY_FIELDS.final_landuse || ['zone_type', 'DLMC', 'SDDLMC', 'GHYTMC'];
  }
  return LAYER_CATEGORY_FIELDS[layerType] || ['zone_type'];
}

function resolvePaletteKey(
  layerType: LayerType,
  properties: Record<string, unknown>,
  fields: readonly string[],
  palette: Record<string, Record<string, unknown>>,
): string | undefined {
  const raw = resolveCategoryValue(properties, fields);
  if (raw) {
    if (raw in palette) return raw;
    const mapped = LAYER_CATEGORY_LABELS[raw];
    if (mapped && mapped in palette) return mapped;
  }

  const zone = classifyLanduseZone(properties);
  if (zone && zone in palette) return zone;

  if (layerType === 'isochrone' && raw) {
    const isoKey = raw.endsWith('min') ? raw : `${raw}min`;
    if (isoKey in palette) return isoKey;
  }

  return raw;
}

function paletteColorsForKey(
  palette: Record<string, Record<string, unknown>>,
  key: string,
): { fill?: string; stroke: string; width?: number } | null {
  const colors = palette[key];
  if (!colors) return null;
  if ('fill' in colors && typeof colors.fill === 'string') {
    return {
      fill: colors.fill,
      stroke: typeof colors.stroke === 'string' ? colors.stroke : colors.fill,
      width: typeof colors.width === 'number' ? colors.width : undefined,
    };
  }
  if ('stroke' in colors && typeof colors.stroke === 'string') {
    return {
      stroke: colors.stroke,
      width: typeof colors.width === 'number' ? colors.width : undefined,
    };
  }
  return null;
}

function buildLegendItemFromPalette(
  label: string,
  palette: Record<string, Record<string, unknown>>,
  key: string,
  geometryType: LegendItem['type'],
  options?: { group?: string; fillOpacity?: number; dashed?: boolean; lineWidth?: number },
): LegendItem | null {
  const colors = paletteColorsForKey(palette, key);
  if (!colors) return null;

  if (geometryType === 'line') {
    return {
      label,
      color: colors.stroke,
      type: 'line',
      lineWidth: options?.lineWidth ?? colors.width ?? 2,
      dashed: options?.dashed,
      group: options?.group,
    };
  }

  if (geometryType === 'point') {
    return {
      label,
      color: colors.fill || colors.stroke,
      type: 'point',
      borderColor: colors.stroke,
      group: options?.group,
    };
  }

  return {
    label,
    color: colors.fill || colors.stroke,
    type: 'polygon',
    borderColor: colors.stroke,
    fillOpacity: options?.fillOpacity,
    group: options?.group,
  };
}

function buildStyleDrivenLegendItem(layer: GISLayerConfig): LegendItem | null {
  const geometryType = legendGeometryType(layer.layerType as LayerType);
  const dashed = Array.isArray(layer.style?.lineDasharray);
  const lineWidth = typeof layer.style?.lineWidth === 'number' ? layer.style.lineWidth : 2;
  const fillOpacity = typeof layer.style?.fillOpacity === 'number' ? layer.style.fillOpacity : undefined;

  if (geometryType === 'line') {
    const color = String(layer.style?.lineColor || layer.color || '#64748b');
    return {
      label: layer.layerName,
      color,
      type: 'line',
      lineWidth,
      dashed,
      group: layer.layerName,
    };
  }

  const fill = String(layer.style?.fillColor || layer.color || '#64748b');
  const stroke = String(layer.style?.lineColor || fill);
  return {
    label: layer.layerName,
    color: fill,
    type: 'polygon',
    borderColor: stroke,
    fillOpacity,
    dashed,
    group: layer.layerName,
  };
}

function buildPlannedRoadLegendItems(layer: GISLayerConfig): LegendItem[] {
  const actionStyles = layer.style?.actionStyles;
  if (!actionStyles || typeof actionStyles !== 'object') return [];

  const presentActions = new Set<string>();
  for (const feature of layer.geojson.features || []) {
    const properties = feature.properties || {};
    const action = String(
      properties.construction_action ?? properties.road_action ?? properties.action ?? '',
    ).trim();
    if (action) presentActions.add(action);
  }

  const items: LegendItem[] = [];
  for (const [action, style] of Object.entries(actionStyles as Record<string, Record<string, unknown>>)) {
    if (presentActions.size > 0 && !presentActions.has(action)) continue;
    const label = String(style.label || LAYER_CATEGORY_LABELS[action] || action);
    const color = String(style.color || '#D73027');
    const width = typeof style.width === 'number' ? style.width : 4.5;
    items.push({
      label,
      color,
      type: 'line',
      lineWidth: width,
      group: layer.layerName,
    });
  }
  return items;
}

// Legend item interface (matching LegendPanel component expectations)
export interface LegendItem {
  label: string;
  color: string;
  type: 'polygon' | 'line' | 'point';
  borderColor?: string;
  lineWidth?: number;
  dashed?: boolean;
  group?: string;
  fillOpacity?: number;
}

// Get legend items for a layer type
export function getLegendForLayerType(layerType: LayerType): LegendItem[] {
  const items: LegendItem[] = [];
  const layerColors = PLANNING_COLORS[layerType];

  if (!layerColors) return items;

  const type = legendGeometryType(layerType);

  for (const [key, colors] of Object.entries(layerColors)) {
    const colorConfig = colors as FeatureColors | LineColors;
    const displayLabel = (colors as Record<string, unknown>).label as string || key;

    if ('fill' in colorConfig) {
      items.push({
        label: displayLabel,
        color: colorConfig.fill,
        type,
        borderColor: colorConfig.stroke,
      });
    } else {
      items.push({
        label: displayLabel,
        color: colorConfig.stroke,
        type: 'line',
        lineWidth: colorConfig.width,
      });
    }
  }

  return items;
}

/**
 * Build legend entries from active layer data, using the same category and
 * palette resolution rules as MapView rendering.
 */
export function getLegendItemsForLayers(layerType: LayerType, layers: GISLayerConfig[]): LegendItem[] {
  const fallbackItems = getLegendForLayerType(layerType);
  const geometryType = legendGeometryType(layerType);
  const items = new Map<string, LegendItem>();

  const addItem = (item: LegendItem | null) => {
    if (!item) return;
    const key = `${item.group || ''}|${item.label}|${item.color}|${item.borderColor || ''}|${item.type}`;
    if (!items.has(key)) items.set(key, item);
  };

  for (const layer of layers) {
    if (isStyleDrivenLayer(layer)) {
      addItem(buildStyleDrivenLegendItem(layer));
      continue;
    }

    if (layer.layerType === 'planned_road' && layer.style?.actionStyles) {
      for (const item of buildPlannedRoadLegendItems(layer)) addItem(item);
      continue;
    }

    const hasFeatureColor = (layer.geojson.features || []).some(
      (feature) => Boolean((feature.properties || {}).color),
    );
    if (hasFeatureColor && layerType === 'infrastructure') {
      const group = layers.length > 1 ? layer.layerName : undefined;
      const seenColors = new Set<string>();
      for (const feature of layer.geojson.features || []) {
        const properties = feature.properties || {};
        const color = String(properties.color || '');
        if (!color || seenColors.has(color)) continue;
        seenColors.add(color);
        addItem({
          label: layer.layerName,
          color,
          type: 'line',
          lineWidth: typeof properties.weight === 'number' ? properties.weight : 2,
          group,
        });
      }
      continue;
    }

    const palette = getRenderingPalette(layerType, layer);
    const fields = getCategoryFields(layerType, layer);
    if (fields.length === 0) {
      addItem(buildStyleDrivenLegendItem(layer));
      continue;
    }

    const fillOpacity = typeof layer.style?.fillOpacity === 'number' ? layer.style.fillOpacity : undefined;
    const dashed = Array.isArray(layer.style?.lineDasharray);
    const group = layers.length > 1 ? layer.layerName : undefined;

    for (const feature of layer.geojson.features || []) {
      const properties = feature.properties || {};
      const paletteKey = resolvePaletteKey(layerType, properties, fields, palette);
      if (!paletteKey) continue;

      const label = fields.includes('time_minutes')
        ? `${paletteKey} 分钟`
        : LAYER_CATEGORY_LABELS[paletteKey] || paletteKey;

      addItem(buildLegendItemFromPalette(label, palette, paletteKey, geometryType, {
        group,
        fillOpacity,
        dashed,
        lineWidth: typeof layer.style?.lineWidth === 'number' ? layer.style.lineWidth : undefined,
      }));
    }
  }

  const resolved = Array.from(items.values());
  if (resolved.length > 0) {
    return resolved.sort((a, b) => {
      const groupCmp = (a.group || '').localeCompare(b.group || '', 'zh-CN');
      if (groupCmp !== 0) return groupCmp;
      return a.label.localeCompare(b.label, 'zh-CN');
    });
  }

  return fallbackItems;
}
