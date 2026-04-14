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
  // Function zone styles (polygon fill)
  function_zone: {
    '居住用地': { fill: '#FFD700', stroke: '#B8860B' },
    '产业用地': { fill: '#FF6B6B', stroke: '#CC0000' },
    '公共服务用地': { fill: '#4A90D9', stroke: '#1E3A5F' },
    '生态绿地': { fill: '#90EE90', stroke: '#228B22' },
    '交通用地': { fill: '#808080', stroke: '#404040' },
    '水域': { fill: '#87CEEB', stroke: '#4169E1' },
    '农业用地': { fill: '#8B4513', stroke: '#654321' },
    '商业用地': { fill: '#FFA500', stroke: '#CC8400' },
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
    '发展主轴': { stroke: '#FF0000', width: 3 },
    '发展副轴': { stroke: '#00AA00', width: 2 },
    '交通主轴': { stroke: '#0000FF', width: 3 },
    '景观轴线': { stroke: '#00FF00', width: 2 },
  },
  // Sensitivity zone styles (polygon fill)
  sensitivity_zone: {
    '高敏感区': { fill: '#FF0000', stroke: '#CC0000' },
    '中敏感区': { fill: '#FFFF00', stroke: '#CCCC00' },
    '低敏感区': { fill: '#00FF00', stroke: '#00CC00' },
    '缓冲区': { fill: '#FFA500', stroke: '#CC8400' },
  },
  // Isochrone styles (time-based)
  isochrone: {
    '5min': { fill: '#00FF00', stroke: '#00CC00' },
    '10min': { fill: '#FFFF00', stroke: '#CCCC00' },
    '15min': { fill: '#FFA500', stroke: '#CC8400' },
  },
} as const;

// Default fallback colors
export const DEFAULT_COLORS = { fill: '#CCCCCC', stroke: '#666666' };

// Zone type definitions
export const ZONE_TYPES = {
  function_zone: ['居住用地', '产业用地', '公共服务用地', '生态绿地', '交通用地', '水域', '农业用地', '商业用地'],
  facility_status: ['现状保留', '规划新建', '规划改扩建', '规划迁建'],
  development_axis: ['发展主轴', '发展副轴', '交通主轴', '景观轴线'],
  sensitivity_level: ['高敏感区', '中敏感区', '低敏感区', '缓冲区'],
} as const;

// Type helper for feature colors
export type FeatureColors = { fill: string; stroke: string };
export type LineColors = { stroke: string; width: number };