// ============================================
// Planning Types - 前端类型定义
// ============================================
// 与后端 src/tools/core/planning_schema.py 对齐

// ============================================
// Position Bias Types
// ============================================

export type DirectionBias =
  | 'north'
  | 'south'
  | 'east'
  | 'west'
  | 'center'
  | 'edge'
  | 'northeast'
  | 'northwest'
  | 'southeast'
  | 'southwest';

export interface LocationBias {
  direction: DirectionBias;
  reference_feature?: string;
}

export interface AdjacencyRule {
  adjacent_to: string[];
  avoid_adjacent_to: string[];
}

// ============================================
// Planning Zone Types
// ============================================

export type LandUseType =
  | '居住用地'
  | '产业用地'
  | '公共服务用地'
  | '生态绿地'
  | '交通用地'
  | '水域'
  | '农业用地'
  | '商业用地'
  | 'residential'
  | 'industrial'
  | 'public_service'
  | 'ecological'
  | 'transportation'
  | 'water'
  | 'agricultural'
  | 'commercial';

export type DensityLevel = 'high' | 'medium' | 'low';

export interface PlanningZone {
  zone_id: string;
  land_use: LandUseType;
  area_ratio: number;
  location_bias: LocationBias;
  adjacency?: AdjacencyRule;
  density: DensityLevel;
  description?: string;
}

// ============================================
// Facility Point Types
// ============================================

export type FacilityStatus =
  | '现状保留'
  | '规划新建'
  | '规划改扩建'
  | '规划迁建'
  | 'existing'
  | 'new'
  | 'expansion'
  | 'relocation';

export type PriorityLevel = 'high' | 'medium' | 'low';

export interface FacilityPoint {
  facility_id: string;
  facility_type: string;
  status: FacilityStatus;
  location_hint: string;
  service_radius: number;
  priority: PriorityLevel;
  description?: string;
}

// ============================================
// Development Axis Types
// ============================================

export type AxisType = 'primary' | 'secondary' | 'corridor' | 'connector';

export type AxisDirection = 'east-west' | 'north-south' | 'radial' | 'ring';

export interface DevelopmentAxis {
  axis_id: string;
  axis_type: AxisType;
  direction: AxisDirection;
  reference_feature?: string;
  description?: string;
}

// ============================================
// Complete Planning Scheme Type
// ============================================

export interface VillagePlanningScheme {
  zones: PlanningZone[];
  facilities: FacilityPoint[];
  axes: DevelopmentAxis[];
  rationale: string;
  development_axes: string[];
  total_area_km2?: number;
}

// ============================================
// Spatial Layout Result Types
// ============================================

export interface SpatialLayoutStatistics {
  zone_count: number;
  facility_count: number;
  axis_count: number;
  total_area_km2: number;
}

export interface FallbackHistoryEntry {
  strategy: string;
  success: boolean;
  reason: string;
  stats?: {
    area_km2?: number;
    buffer_km?: number;
    feature_count?: number;
  };
}

export interface BoundaryFallbackResult {
  strategy_used: string;
  fallback_history: FallbackHistoryEntry[];
  warnings: string[];
  stats: {
    area_km2?: number;
    buffer_km?: number;
  };
}

// ============================================
// Zone Type Constants (Mirror Backend)
// ============================================

export const ZONE_TYPE_NAMES: Record<string, string> = {
  residential: '居住用地',
  industrial: '产业用地',
  public_service: '公共服务用地',
  ecological: '生态绿地',
  transportation: '交通用地',
  water: '水域',
  agricultural: '农业用地',
  commercial: '商业用地',
};

export const ZONE_TYPE_COLORS: Record<string, string> = {
  residential: '#FFD700',
  industrial: '#FF6B6B',
  public_service: '#4A90D9',
  ecological: '#90EE90',
  transportation: '#808080',
  water: '#87CEEB',
  agricultural: '#8B4513',
  commercial: '#FFA500',
};

export const FACILITY_STATUS_COLORS: Record<string, string> = {
  existing: '#228B22',
  new: '#4A90D9',
  expansion: '#FF8C00',
  relocation: '#9370DB',
};

export const getZoneColor = (zoneType: string): string => {
  return ZONE_TYPE_COLORS[zoneType] || '#CCCCCC';
};

export const getZoneName = (zoneType: string): string => {
  return ZONE_TYPE_NAMES[zoneType] || zoneType;
};

export const getFacilityColor = (status: string): string => {
  return FACILITY_STATUS_COLORS[status] || '#808080';
};