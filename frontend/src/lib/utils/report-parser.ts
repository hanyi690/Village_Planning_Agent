// ============================================
// Report Parser - 维度报告解析工具
// ============================================

import { getDimensionsByLayer, DIMENSION_NAMES } from '@/config/dimensions';

/**
 * 解析 Markdown 报告内容，提取维度数据
 * 用于历史记录加载时构建 dimensionReports
 *
 * @param markdown - Markdown 格式的报告内容
 * @param layerNumber - 层级编号 (1, 2, 3)
 * @returns 维度键名到内容的映射
 *
 * @example
 * ```typescript
 * const markdown = `
 * ## 产业现状
 * 产业分析内容...
 *
 * ## 人口结构
 * 人口分析内容...
 * `;
 * const reports = parseDimensionReports(markdown, 1);
 * // Returns: { "产业现状": "产业分析内容...", "人口结构": "人口分析内容..." }
 * ```
 */
export function parseDimensionReports(
  markdown: string,
  layerNumber: number
): Record<string, string> {
  const dimensionKeys = getDimensionsByLayer(layerNumber);
  const result: Record<string, string> = {};

  if (!markdown) return result;

  // 匹配 ## 标题格式
  const regex = /##\s+(.+?)\n([\s\S]*?)(?=\n##\s|$)/g;
  let match;

  while ((match = regex.exec(markdown)) !== null) {
    const title = match[1].trim();
    const content = match[2].trim();

    // 尝试匹配维度键名（标题可能是英文键名或中文名称）
    const key = dimensionKeys.find(k => {
      const chineseName = DIMENSION_NAMES[k];
      return (
        title === k ||
        title.includes(k) ||
        k.includes(title) ||
        title === chineseName ||
        title.includes(chineseName) ||
        chineseName.includes(title)
      );
    });

    if (key && content) {
      result[key] = content;
    }
  }

  console.log(
    `[parseDimensionReports] Layer ${layerNumber}: found ${Object.keys(result).length} dimensions`
  );
  return result;
}

/**
 * 合并多个层级的维度报告
 *
 * @param reports - 各层级的报告数据
 * @returns 合并后的完整报告内容
 */
export function mergeDimensionReports(
  reports: Record<string, string>[]
): Record<string, string> {
  return reports.reduce((acc, report) => ({ ...acc, ...report }), {});
}

/**
 * 生成 Markdown 格式的报告
 *
 * @param dimensionReports - 维度报告映射
 * @returns Markdown 格式的完整报告
 */
export function generateMarkdownReport(
  dimensionReports: Record<string, string>,
  dimensionNames: Record<string, string> = DIMENSION_NAMES
): string {
  return Object.entries(dimensionReports)
    .map(([key, content]) => {
      const name = dimensionNames[key] || key;
      return `## ${name}\n\n${content}`;
    })
    .join('\n\n---\n\n');
}