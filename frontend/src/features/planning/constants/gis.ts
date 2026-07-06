/**
 * GIS Constants Module
 *
 * Synchronized with backend: src/tools/core/map_renderer.py
 * Contains tile sources, planning styles, and type definitions.
 */

// Tile source identifiers
export const TILE_SOURCES = {
  TIANDITU: 'tianditu',
  GEOQ: 'geoq',
  OSM: 'osm',
} as const;

export type TileSourceType = typeof TILE_SOURCES[keyof typeof TILE_SOURCES];

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
    '规划新建': { fill: 'blue', stroke: '#00008B' },
    '规划改扩建': { fill: 'orange', stroke: '#CC8400' },
    '规划迁建': { fill: 'purple', stroke: '#800080' },
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
  },
  // Infrastructure styles (基础设施)
  infrastructure: {
    '县道': { stroke: '#555555', width: 2, label: '县道' },
    '乡道': { stroke: '#808080', width: 1.5, label: '乡道' },
    '道路': { stroke: '#666666', width: 2, label: '道路' },
    '河流': { stroke: '#00BFFF', width: 2.5, label: '河流' },
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
  function_zone: '功能区',
  facility_point: '设施点',
  sensitivity_zone: '敏感区',
  infrastructure: '基础设施',
  isochrone: '等时圈',
  planning_zone: '规划分区',
  development_axis: '发展轴',
  settlement_zone: '居民点分类',
};

// Legend item interface (matching LegendPanel component expectations)
export interface LegendItem {
  label: string;
  color: string;
  type: 'polygon' | 'line' | 'point';
  borderColor?: string;
  lineWidth?: number;
}

// Get legend items for a layer type
export function getLegendForLayerType(layerType: LayerType): LegendItem[] {
  const items: LegendItem[] = [];
  const layerColors = PLANNING_COLORS[layerType];

  if (!layerColors) return items;

  // Determine geometry type based on layer type
  const type: 'polygon' | 'line' | 'point' =
    layerType === 'boundary' || layerType === 'development_axis' || layerType === 'infrastructure' ? 'line' :
    layerType === 'facility_point' ? 'point' : 'polygon';

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