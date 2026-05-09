/**
 * Report Parser Types and Utilities
 * 用于解析层级报告 markdown 内容
 */

// 正则表达式提升到模块顶层，避免每次解析重新编译
const DIMENSION_PATTERN = /^##\s+(.+)\n([\s\S]*?)(?=^##\s+|^$)/gm;
const SUBSECTION_PATTERN = /^###\s+(.+)\n([\s\S]*?)(?=^###\s+|^##\s+|^$)/gm;

/**
 * 子节内容
 */
export interface ParsedSubsection {
  title: string;
  content: string;
}

/**
 * 解析后的维度
 */
export interface ParsedDimension {
  key?: string;
  name: string;
  content: string;
  icon?: string;
  subsections: ParsedSubsection[];
}

/**
 * 获取维度的唯一键
 * 优先使用 key，否则使用 name
 */
export function getDimensionKey(dimension: ParsedDimension): string {
  return dimension.key || dimension.name;
}

/**
 * 解析层级报告 markdown 内容
 * 支持 ## 标题格式的维度解析
 *
 * @param content - markdown 格式的层级报告内容
 * @returns 解析后的维度数组
 */
export function parseLayerReport(content: string): ParsedDimension[] {
  if (!content || content.trim().length === 0) {
    return [];
  }

  const dimensions: ParsedDimension[] = [];

  // 重置正则表达式状态（重要：正则对象有内部状态）
  DIMENSION_PATTERN.lastIndex = 0;

  let match;
  while ((match = DIMENSION_PATTERN.exec(content)) !== null) {
    const name = match[1].trim();
    const rawContent = match[2].trim();

    if (name && rawContent) {
      // 尝试解析子节（### 标题）
      const subsections: ParsedSubsection[] = [];
      let mainContent = rawContent;

      // 优化：只使用 indexOf 一次判断
      const firstSubsectionIndex = rawContent.indexOf('### ');
      if (firstSubsectionIndex !== -1) {
        // 重置子节正则状态
        SUBSECTION_PATTERN.lastIndex = 0;

        // 提取子节内容
        let subMatch;
        while ((subMatch = SUBSECTION_PATTERN.exec(rawContent)) !== null) {
          subsections.push({
            title: subMatch[1].trim(),
            content: subMatch[2].trim(),
          });
        }
        // 主内容为第一个 ### 之前的内容
        mainContent = firstSubsectionIndex > 0
          ? rawContent.substring(0, firstSubsectionIndex).trim()
          : '';
      }

      dimensions.push({
        name,
        content: mainContent || rawContent,
        subsections,
      });
    }
  }

  // 如果没有解析到 ## 标题，返回原始内容作为单个维度
  if (dimensions.length === 0 && content.trim().length > 0) {
    dimensions.push({
      name: '规划内容',
      content: content.trim(),
      subsections: [],
    });
  }

  return dimensions;
}