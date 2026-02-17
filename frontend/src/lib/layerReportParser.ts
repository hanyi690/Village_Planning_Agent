/**
 * Layer Report Parser
 * 解析 Markdown 报告，提取维度结构
 *
 * 修复版本 2026-02-07:
 * - 使用 matchAll() 精确提取标题和内容，避免包含 ## 标题行
 * - 添加完整的中文标题到图标的精确映射（28个维度）
 * - 支持向后兼容旧格式报告（无 ## 标题）
 * - 正确提取子章节（### 三级标题）
 */

export interface ParsedSubsection {
  title: string;
  content: string;
}

export interface ParsedDimension {
  name: string;
  content: string;
  subsections: ParsedSubsection[];
  icon: string;
}

/**
 * Extract subsections from dimension content
 * @param content - Dimension content (without the ## title line)
 * @returns Array of parsed subsections with ### titles
 */
function extractSubsections(content: string): ParsedSubsection[] {
  const subsections: ParsedSubsection[] = [];
  const subsectionRegex = /^###\s+(.+)$/gm;
  const matches = Array.from(content.matchAll(subsectionRegex));

  if (matches.length === 0) return subsections;

  for (let i = 0; i < matches.length; i++) {
    const title = matches[i][1]?.trim();
    const startIndex = matches[i].index + matches[i][0].length;
    const endIndex = i < matches.length - 1
      ? matches[i + 1].index
      : content.length;

    const subContent = content.substring(startIndex, endIndex).trim();
    if (title) {
      subsections.push({ title, content: subContent });
    }
  }

  return subsections;
}

/**
 * Parse layer report markdown into structured dimensions
 * @param markdown - Full markdown report content
 * @returns Array of parsed dimensions with icon mappings
 */
export function parseLayerReport(markdown: string): ParsedDimension[] {
  if (!markdown) return [];

  const dimensions: ParsedDimension[] = [];

  // 检测是新格式（有 ## 标题）还是旧格式
  const hasHeaders = /^##\s+.+$/m.test(markdown);

  if (!hasHeaders) {
    // 旧格式 - 作为单个维度处理
    return [{
      name: '综合分析',
      content: markdown.trim(),
      subsections: [],
      icon: 'fa-file-alt'
    }];
  }

  // 新格式 - 查找所有 ## 二级标题及其位置
  const headerRegex = /^##\s+(.+)$/gm;
  const matches = Array.from(markdown.matchAll(headerRegex));

  if (matches.length === 0) {
    return [{
      name: '综合分析',
      content: markdown.trim(),
      subsections: [],
      icon: 'fa-file-alt'
    }];
  }

  // 提取标题之间的内容（自动排除 ## 标题行）
  for (let i = 0; i < matches.length; i++) {
    const match = matches[i];
    const title = match[1]?.trim() || `维度 ${i + 1}`;

    // 计算内容边界
    const startIndex = match.index + match[0].length;
    const endIndex = i < matches.length - 1
      ? matches[i + 1].index
      : markdown.length;

    // 提取内容（自动排除 ## 标题行）
    let content = markdown.substring(startIndex, endIndex).trim();

    // 提取子章节（### 三级标题）
    const subsections = extractSubsections(content);

    dimensions.push({
      name: title,
      content,
      subsections,
      icon: getDimensionIcon(title),
    });
  }

  return dimensions;
}

/**
 * Get Font Awesome icon class for dimension name
 * @param dimensionName - Full Chinese title of the dimension section
 * @returns Font Awesome icon class string
 */
export function getDimensionIcon(dimensionName: string): string {
  // 精确中文标题映射（优先级最高）
  const exactTitleMap: Record<string, string> = {
    // Layer 1 - 现状分析 (12 dimensions)
    '区位与对外交通分析': 'fa-location-dot',
    '社会经济分析': 'fa-chart-line',
    '村民意愿与诉求分析': 'fa-users',
    '上位规划与政策导向分析': 'fa-landmark',
    '自然环境与生态本底分析': 'fa-leaf',
    '土地利用与合规性分析': 'fa-ruler-combined',
    '道路交通与街巷空间分析': 'fa-road',
    '公共服务设施承载力分析': 'fa-hospital',
    '基础设施现状分析': 'fa-bolt',
    '生态绿地与开敞空间分析': 'fa-tree',
    '聚落形态与建筑风貌分析': 'fa-home',
    '历史文化与乡愁保护分析': 'fa-university',

    // Layer 2 - 规划思路 (4 dimensions)
    '资源禀赋分析': 'fa-gift',
    '规划定位分析': 'fa-map-pin',
    '发展目标分析': 'fa-flag',
    '规划策略分析': 'fa-chess',

    // Layer 3 - 详细规划 (12 dimensions)
    '产业规划': 'fa-industry',
    '空间结构规划': 'fa-project-diagram',
    '土地利用规划': 'fa-ruler-combined',
    '居民点规划': 'fa-home',
    '道路交通规划': 'fa-road',
    '公服设施规划': 'fa-hospital',
    '基础设施规划': 'fa-bolt',
    '生态绿地规划': 'fa-tree',
    '防震减灾规划': 'fa-life-ring',
    '历史文保规划': 'fa-landmark',
    '村庄风貌指引': 'fa-city',
    '建设项目库': 'fa-tasks',
  };

  // 优先检查精确匹配
  if (exactTitleMap[dimensionName]) {
    return exactTitleMap[dimensionName];
  }

  // 回退到关键词匹配（保持灵活性）
  const keywordIconMap: Record<string, string> = {
    // 区位相关
    '区位': 'fa-location-dot',
    '位置': 'fa-map-marker-alt',
    '地理': 'fa-globe-asia',
    '坐标': 'fa-crosshairs',

    // 社会经济
    '社会': 'fa-users',
    '经济': 'fa-chart-line',
    '人口': 'fa-user-friends',
    '产业': 'fa-industry',
    '行政区划': 'fa-sitemap',
    '行政': 'fa-landmark',

    // 自然环境
    '自然': 'fa-tree',
    '环境': 'fa-leaf',
    '生态': 'fa-seedling',
    '气候': 'fa-cloud-sun',
    '地形': 'fa-mountain',
    '地质': 'fa-gem',
    '水文': 'fa-water',
    '林地': 'fa-tree',
    '田园': 'fa-tractor',
    '土地': 'fa-ruler-combined',

    // 道路交通
    '道路': 'fa-road',
    '交通': 'fa-car',
    '对外交通': 'fa-exchange-alt',
    '内部交通': 'fa-road',
    '交通设施': 'fa-bus',
    '步道': 'fa-hiking',

    // 公共服务
    '公共': 'fa-building',
    '服务': 'fa-concierge-bell',
    '公共服务': 'fa-hospital',
    '设施': 'fa-hospital',
    '公共服务设施': 'fa-clinic-medical',

    // 基础设施
    '基础': 'fa-tools',
    '基础设施': 'fa-bolt',
    '供水': 'fa-faucet',
    '排水': 'fa-sink',
    '电力': 'fa-bolt',
    '通信': 'fa-broadcast-tower',

    // 绿地与活动
    '绿地': 'fa-seedling',
    '活动': 'fa-running',
    '活动场地': 'fa-square',
    '广场': 'fa-square',

    // 建筑
    '建筑': 'fa-home',
    '房屋': 'fa-house',
    '民居': 'fa-home',
    '风貌': 'fa-city',

    // 历史文化
    '历史': 'fa-landmark',
    '文化': 'fa-music',
    '传统': 'fa-scroll',
    '民俗': 'fa-mask',
    '古迹': 'fa-monument',
    '非遗': 'fa-palette',
    '历史文化': 'fa-university',

    // 规划相关
    '规划': 'fa-drafting-compass',
    '思路': 'fa-lightbulb',
    '方案': 'fa-clipboard-list',
    '策略': 'fa-chess',
    '布局': 'fa-th-large',
    '总体': 'fa-project-diagram',

    // 产业规划
    '产业规划': 'fa-industry',
    '农业': 'fa-wheat',
    '工业': 'fa-factory',
    '旅游': 'fa-plane',
    '服务业': 'fa-store',

    // 生态与环境
    '生态绿地': 'fa-tree',
    '环境保护': 'fa-leaf',
    '生态修复': 'fa-recycle',
    '绿化': 'fa-seedling',

    // 防震减灾
    '防震': 'fa-house-crack',
    '减灾': 'fa-life-ring',
    '防洪': 'fa-water',
    '消防': 'fa-fire-extinguisher',

    // 资源
    '资源': 'fa-box',
    '禀赋': 'fa-gift',
    '资源禀赋': 'fa-treasure-chest',

    // 发展目标
    '目标': 'fa-bullseye',
    '发展目标': 'fa-flag',
    '定位': 'fa-map-pin',

    // 项目
    '项目': 'fa-tasks',
    '建设项目': 'fa-hard-hat',
    '近期': 'fa-calendar-check',
    '远期': 'fa-calendar-alt',

    // 报告相关
    '报告': 'fa-file-alt',
    '说明': 'fa-info-circle',
    '总结': 'fa-list-ol',
  };

  // Try to find a matching keyword in the dimension name
  for (const [keyword, icon] of Object.entries(keywordIconMap)) {
    if (dimensionName.includes(keyword)) {
      return icon;
    }
  }

  // Default icon
  return 'fa-folder-open';
}

/**
 * Extract dimension names from report content
 * @param markdown - Full markdown report content
 * @returns Array of dimension names
 */
export function extractDimensionNames(markdown: string): string[] {
  const dimensions = parseLayerReport(markdown);
  return dimensions.map(d => d.name);
}

/**
 * Get report summary statistics
 * @param markdown - Full markdown report content
 * @returns Statistics object
 */
export function getReportStats(markdown: string) {
  const dimensions = parseLayerReport(markdown);
  const wordCount = markdown.length;

  return {
    wordCount,
    dimensionCount: dimensions.length,
    dimensionNames: dimensions.map(d => d.name),
    subsectionCount: dimensions.reduce((sum, d) => sum + d.subsections.length, 0),
  };
}
