/**
 * 维度配置文件
 * 统一管理所有维度的中文名称、图标和显示顺序
 */

// 维度名称映射
export const DIMENSION_NAMES: Record<string, string> = {
  // Layer 1: 现状分析
  location: '区位与对外交通分析',
  socio_economic: '社会经济分析',
  villager_wishes: '村民意愿与诉求分析',
  superior_planning: '上位规划与政策导向分析',
  natural_environment: '自然环境分析',
  land_use: '土地利用分析',
  traffic: '道路交通分析',
  public_services: '公共服务设施分析',
  infrastructure: '基础设施分析',
  ecological_green: '生态绿地分析',
  architecture: '建筑分析',
  historical_culture: '历史文化与乡愁保护分析',

  // Layer 2: 规划思路
  resource_endowment: '资源禀赋分析',
  planning_positioning: '规划定位分析',
  development_goals: '发展目标分析',
  planning_strategies: '规划策略分析',

  // Layer 3: 详细规划
  industry: '产业规划',
  spatial_structure: '空间结构规划',
  land_use_planning: '土地利用规划',
  settlement_planning: '居民点规划',
  traffic_planning: '道路交通规划',
  public_service: '公共服务设施规划',
  infrastructure_planning: '基础设施规划',
  ecological: '生态绿地规划',
  disaster_prevention: '防震减灾规划',
  heritage: '历史文保规划',
  landscape: '村庄风貌指引',
  project_bank: '建设项目库',
};

// 维度图标映射
export const DIMENSION_ICONS: Record<string, string> = {
  // Layer 1: 现状分析
  location: '📍',
  socio_economic: '👥',
  villager_wishes: '💭',
  superior_planning: '📋',
  natural_environment: '🌿',
  land_use: '🏗️',
  traffic: '🚗',
  public_services: '🏛️',
  infrastructure: '🔧',
  ecological_green: '🌳',
  architecture: '🏠',
  historical_culture: '🏛️',

  // Layer 2: 规划思路
  resource_endowment: '💎',
  planning_positioning: '🎯',
  development_goals: '🎯',
  planning_strategies: '📊',

  // Layer 3: 详细规划
  industry: '🏭',
  spatial_structure: '🗺️',
  land_use_planning: '📐',
  settlement_planning: '🏘️',
  traffic_planning: '🛣️',
  public_service: '🏥',
  infrastructure_planning: '🔨',
  ecological: '🌲',
  disaster_prevention: '🛡️',
  heritage: '🏰',
  landscape: '🎨',
  project_bank: '📦',
};

// 按层级分组的维度（控制显示顺序）
export const DIMENSIONS_BY_LAYER: Record<number, string[]> = {
  1: [
    'location',
    'socio_economic',
    'villager_wishes',
    'superior_planning',
    'natural_environment',
    'land_use',
    'traffic',
    'public_services',
    'infrastructure',
    'ecological_green',
    'architecture',
    'historical_culture',
  ],
  2: [
    'resource_endowment',
    'planning_positioning',
    'development_goals',
    'planning_strategies',
  ],
  3: [
    'industry',
    'spatial_structure',
    'land_use_planning',
    'settlement_planning',
    'traffic_planning',
    'public_service',
    'infrastructure_planning',
    'ecological',
    'disaster_prevention',
    'heritage',
    'landscape',
    'project_bank',
  ],
};

/**
 * 获取维度中文名称
 * @param key 维度键名
 * @returns 维度中文名称，如果找不到则返回原始键名
 */
export const getDimensionName = (key: string): string => {
  return DIMENSION_NAMES[key] || key;
};

/**
 * 获取维度图标
 * @param key 维度键名
 * @returns 维度图标，如果找不到则返回默认图标
 */
export const getDimensionIcon = (key: string): string => {
  return DIMENSION_ICONS[key] || '📄';
};

/**
 * 获取指定层级的所有维度键名
 * @param layer 层级编号（1、2、3）
 * @returns 维度键名数组
 */
export const getDimensionsByLayer = (layer: number): string[] => {
  return DIMENSIONS_BY_LAYER[layer] || [];
};

/**
 * 获取指定层级的所有维度配置（包含名称和图标）
 * @param layer 层级编号（1、2、3）
 * @returns 维度配置数组
 */
export const getDimensionConfigsByLayer = (layer: number): Array<{
  key: string;
  name: string;
  icon: string;
}> => {
  return getDimensionsByLayer(layer).map(key => ({
    key,
    name: getDimensionName(key),
    icon: getDimensionIcon(key),
  }));
};