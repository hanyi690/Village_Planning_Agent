import { DIMENSIONS_BY_LAYER, getDimensionName } from '../config/dimensions';
import type {
  GeneratePlanningTextRequest,
  PlanningTextDocument,
  PlanningTextVersionList,
} from '../api/types';

const LAYER_TITLES: Record<1 | 2 | 3, string> = {
  1: '第一章 现状分析',
  2: '第二章 规划思路',
  3: '第三章 详细规划',
};

type LayerReports = {
  layer1: Record<string, string>;
  layer2: Record<string, string>;
  layer3: Record<string, string>;
};

function buildMarkdown(reports: LayerReports, projectName: string): string {
  const lines: string[] = [
    `# ${projectName || '村庄规划'}文本（汇编稿）`,
    '',
    '> 由前端根据 L1/L2/L3 专题报告自动汇编，供阅读与导出；法定格式以后端 DELIVER 产物为准。',
    '',
  ];

  let articleCount = 0;
  for (const layer of [1, 2, 3] as const) {
    const layerKey = `layer${layer}` as keyof LayerReports;
    const layerReports = reports[layerKey] || {};
    const dims = DIMENSIONS_BY_LAYER[layer] || [];
    const sections = dims
      .map((dimKey) => {
        const body = (layerReports[dimKey] || '').trim();
        if (!body) return null;
        articleCount += 1;
        return `## ${getDimensionName(dimKey)}\n\n${body}`;
      })
      .filter((section): section is string => Boolean(section));

    if (sections.length === 0) continue;
    lines.push(`# ${LAYER_TITLES[layer]}`, '', ...sections, '');
  }

  if (articleCount === 0) {
    lines.push('_暂无可用报告内容，请先完成分层分析。_');
  }

  return lines.join('\n');
}

export function assemblePlanningTextDocument(
  sessionId: string,
  reports: LayerReports,
  projectName: string,
  request?: GeneratePlanningTextRequest,
): PlanningTextDocument {
  const markdown = buildMarkdown(reports, projectName);
  const now = new Date().toISOString();
  return {
    id: 1,
    session_id: sessionId,
    version: 1,
    document_id: `client-${sessionId.slice(0, 8)}`,
    markdown_content: markdown,
    json_content: {
      source: 'client_assembly',
      layers: {
        layer1: Object.keys(reports.layer1 || {}),
        layer2: Object.keys(reports.layer2 || {}),
        layer3: Object.keys(reports.layer3 || {}),
      },
    },
    article_count: markdown.split(/^## /m).length - 1,
    generated_at: now,
    status: 'completed',
    trigger_reason: request?.trigger_reason || 'manual',
    changed_dimensions: request?.changed_dimensions,
  };
}

export function assemblePlanningTextVersions(
  sessionId: string,
  doc: PlanningTextDocument | null,
): PlanningTextVersionList {
  if (!doc) {
    return { session_id: sessionId, versions: [], total: 0 };
  }
  return {
    session_id: sessionId,
    total: 1,
    versions: [{
      id: doc.id,
      version: doc.version,
      document_id: doc.document_id,
      article_count: doc.article_count,
      generated_at: doc.generated_at,
      status: doc.status,
      trigger_reason: doc.trigger_reason,
      changed_dimensions: doc.changed_dimensions,
    }],
  };
}
