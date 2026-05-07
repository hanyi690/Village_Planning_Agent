/**
 * Report Parser Types and Utilities
 * 用于解析层级报告 markdown 内容
 */

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
  // 匹配 ## 标题作为维度分隔
  const dimensionPattern = /^##\s+(.+)\n([\s\S]*?)(?=^##\s+|^$)/gm;

  let match;
  while ((match = dimensionPattern.exec(content)) !== null) {
    const name = match[1].trim();
    const rawContent = match[2].trim();

    if (name && rawContent) {
      // 尝试解析子节（### 标题）
      const subsections: ParsedSubsection[] = [];
      const subsectionPattern = /^###\s+(.+)\n([\s\S]*?)(?=^###\s+|^##\s+|^$)/gm;

      let subMatch;
      let mainContent = rawContent;

      // 检查是否有子节
      if (rawContent.includes('### ')) {
        // 提取子节内容
        while ((subMatch = subsectionPattern.exec(rawContent)) !== null) {
          subsections.push({
            title: subMatch[1].trim(),
            content: subMatch[2].trim(),
          });
        }
        // 主内容为第一个 ### 之前的内容
        const firstSubsectionIndex = rawContent.indexOf('### ');
        if (firstSubsectionIndex > 0) {
          mainContent = rawContent.substring(0, firstSubsectionIndex).trim();
        } else {
          mainContent = '';
        }
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