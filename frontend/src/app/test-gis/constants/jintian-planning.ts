// ============================================
// Jintian Village Planning Data Constants
// ============================================
// 基于 docs/layer3_完整报告.md 提取的金田村真实规划数据

import type {
  VillagePlanningScheme,
  PlanningZone,
  FacilityPoint,
  DevelopmentAxis,
  LocationBias,
  AdjacencyRule,
} from '../types/planning';

// ============================================
// Geographic Constants
// ============================================

// 金田村中心坐标 (WGS84)
// 来源：backend/api/gis_test.py JINTIAN_TEST_CENTER
export const JINTIAN_CENTER: [number, number] = [116.044146, 24.818629];

// 规划区域总面积 (km²)
// 来源：报告提到林地约1867公顷 + 耕地85.2公顷
export const JINTIAN_TOTAL_AREA_KM2 = 4.0;

// ============================================
// Planning Zones - 用地分区
// ============================================
// 来源：layer3_完整报告.md 空间结构规划

const createLocationBias = (
  direction: LocationBias['direction'],
  reference_feature?: string
): LocationBias => ({
  direction,
  reference_feature,
});

const createAdjacencyRule = (
  adjacent_to: string[],
  avoid_adjacent_to: string[]
): AdjacencyRule => ({
  adjacent_to,
  avoid_adjacent_to,
});

export const JINTIAN_ZONES: PlanningZone[] = [
  {
    zone_id: 'Z01',
    land_use: 'residential',
    area_ratio: 0.03,
    location_bias: createLocationBias('center', '靠近村委会'),
    adjacency: createAdjacencyRule(['public_service'], ['industrial']),
    density: 'medium',
    description: '村庄建设区 - 集中布局居民住宅',
  },
  {
    zone_id: 'Z02',
    land_use: 'agricultural',
    area_ratio: 0.50,
    location_bias: createLocationBias('south', '避开地质灾害隐患点'),
    adjacency: createAdjacencyRule(['residential', 'ecological'], []),
    density: 'low',
    description: '农业生产区 - 林下药材种植区（灵芝、黄精）',
  },
  {
    zone_id: 'Z03',
    land_use: 'ecological',
    area_ratio: 0.40,
    location_bias: createLocationBias('edge', '商业林区'),
    adjacency: createAdjacencyRule(['agricultural'], ['industrial']),
    density: 'low',
    description: '生态保护区 - 森林覆盖区，发展林下经济',
  },
  {
    zone_id: 'Z04',
    land_use: 'public_service',
    area_ratio: 0.02,
    location_bias: createLocationBias('center', '村庄核心位置'),
    adjacency: createAdjacencyRule(['residential'], ['industrial']),
    density: 'high',
    description: '公共服务用地 - 村委会、文化活动站、卫生站',
  },
  {
    zone_id: 'Z05',
    land_use: 'industrial',
    area_ratio: 0.05,
    location_bias: createLocationBias('west', '远离居住区'),
    adjacency: createAdjacencyRule([], ['residential', 'public_service']),
    density: 'low',
    description: '产业发展区 - 农产品初加工中心',
  },
];

// ============================================
// Facility Points - 公共设施
// ============================================
// 来源：layer3_完整报告.md 公共设施配置

export const JINTIAN_FACILITIES: FacilityPoint[] = [
  {
    facility_id: 'F01',
    facility_type: '村委会',
    status: 'existing',
    location_hint: '村庄中心位置',
    service_radius: 500,
    priority: 'high',
    description: '现状保留，作为村庄行政服务中心',
  },
  {
    facility_id: 'F02',
    facility_type: '文化活动站',
    status: 'new',
    location_hint: '靠近村委会，结合船灯舞非遗展示',
    service_radius: 300,
    priority: 'medium',
    description: '规划新建，用于非遗文化展示与体验',
  },
  {
    facility_id: 'F03',
    facility_type: '卫生站',
    status: 'new',
    location_hint: '居住区内，服务半径覆盖全村',
    service_radius: 400,
    priority: 'high',
    description: '规划新建，满足村民基本医疗需求',
  },
  {
    facility_id: 'F04',
    facility_type: '农产品加工中心',
    status: 'new',
    location_hint: '产业发展区西侧',
    service_radius: 200,
    priority: 'medium',
    description: '规划新建，包含烘干与初加工设施',
  },
  {
    facility_id: 'F05',
    facility_type: '电商直播基地',
    status: 'new',
    location_hint: '靠近村委会，交通便利',
    service_radius: 150,
    priority: 'low',
    description: '规划新建，打通农产品销售渠道',
  },
];

// ============================================
// Development Axes - 发展轴线
// ============================================
// 来源：layer3_完整报告.md "沿Y122乡道东西向发展"

export const JINTIAN_AXES: DevelopmentAxis[] = [
  {
    axis_id: 'A01',
    axis_type: 'primary',
    direction: 'east-west',
    reference_feature: 'Y122乡道',
    description: '主要发展轴 - 沿Y122乡道东西向发展',
  },
  {
    axis_id: 'A02',
    axis_type: 'secondary',
    direction: 'north-south',
    reference_feature: '村内次要道路',
    description: '次要发展轴 - 连接居住区与农业生产区',
  },
];

// ============================================
// Complete Planning Scheme
// ============================================

export const JINTIAN_PLANNING_SCHEME: VillagePlanningScheme = {
  zones: JINTIAN_ZONES,
  facilities: JINTIAN_FACILITIES,
  axes: JINTIAN_AXES,
  rationale:
    '基于金田村"人少地碎林多"的资源禀赋，确立"林下生态药业"与"古檀文化旅游"双主导产业，规避耕地破碎劣势，最大化林地优势',
  development_axes: ['沿Y122乡道东西向发展'],
  total_area_km2: JINTIAN_TOTAL_AREA_KM2,
};

// ============================================
// Alternative Schemes for Testing
// ============================================

// 简化方案 - 用于快速测试
export const SIMPLE_PLANNING_SCHEME: VillagePlanningScheme = {
  zones: [
    {
      zone_id: 'Z01',
      land_use: 'residential',
      area_ratio: 0.35,
      location_bias: { direction: 'center' },
      density: 'medium',
    },
    {
      zone_id: 'Z02',
      land_use: 'public_service',
      area_ratio: 0.15,
      location_bias: { direction: 'center' },
      density: 'high',
    },
    {
      zone_id: 'Z03',
      land_use: 'agricultural',
      area_ratio: 0.30,
      location_bias: { direction: 'south' },
      density: 'low',
    },
    {
      zone_id: 'Z04',
      land_use: 'ecological',
      area_ratio: 0.15,
      location_bias: { direction: 'edge' },
      density: 'low',
    },
    {
      zone_id: 'Z05',
      land_use: 'industrial',
      area_ratio: 0.05,
      location_bias: { direction: 'west' },
      density: 'low',
    },
  ],
  facilities: [
    {
      facility_id: 'F01',
      facility_type: '村委会',
      status: 'existing',
      location_hint: '村庄中心位置',
      service_radius: 500,
      priority: 'high',
    },
    {
      facility_id: 'F02',
      facility_type: '文化活动站',
      status: 'new',
      location_hint: '靠近村委会',
      service_radius: 300,
      priority: 'medium',
    },
    {
      facility_id: 'F03',
      facility_type: '卫生站',
      status: 'new',
      location_hint: '居住区内',
      service_radius: 400,
      priority: 'high',
    },
  ],
  axes: [
    {
      axis_id: 'A01',
      axis_type: 'primary',
      direction: 'east-west',
      description: '主要发展轴',
    },
    {
      axis_id: 'A02',
      axis_type: 'secondary',
      direction: 'north-south',
      description: '次要发展轴',
    },
  ],
  rationale: '基于现状分析的规划布局',
  development_axes: ['沿东西向主干道发展'],
  total_area_km2: 2.0,
};