'use client';

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import MapView, { type MapFeatureFocus } from '@/features/planning/components/gis/MapView';
import ChatInput from '@/features/planning/components/ChatInput';
import MessageList from '@/features/planning/components/chat/MessageList';
import PlanningTextViewer from '@/features/planning/components/PlanningTextViewer';
import ReportViewer from '@/features/planning/components/layout/ReportViewer';
import AnalysisProgressBanner from '@/features/planning/components/layout/AnalysisProgressBanner';
import OverviewLockedPlaceholder from '@/features/planning/components/layout/OverviewLockedPlaceholder';
import PlanningBootstrapPanel from '@/features/planning/components/layout/PlanningBootstrapPanel';
import { usePlanningBootstrapStage } from '@/features/planning/hooks/usePlanningBootstrapStage';
import { DIMENSIONS_BY_LAYER, getDimensionName } from '@/features/planning/config/dimensions';
import { useActiveAnalysisFocus } from '@/features/planning/hooks/useActiveAnalysisFocus';
import {
  ENTITY_BROWSER_CURRENT,
  ENTITY_BROWSER_PLANNED,
  LAYER_FILTER_ICONS,
  PANEL_TITLE_ICON,
  QUICK_LAYER_GROUP_ICONS,
  SPATIAL_RELATIONS,
  SIDEBAR_NAV_ICONS,
  WORKBENCH_BRAND_ICON,
  WORKBENCH_METRIC_ICONS,
  EntityBrowserRow,
  RelationDot,
  WorkbenchIcon,
  getSpatialRelation,
  renderLayerDoneIcon,
} from '@/features/planning/constants/workbench-icons';
import { faRotateRight, faTrash } from '@fortawesome/free-solid-svg-icons';
import type { IconDefinition } from '@fortawesome/fontawesome-svg-core';
import { FILE_ACCEPT, NAV_KEYS } from '@/features/planning/constants';
import { PlanningProvider, usePlanningActions, usePlanningStore } from '@/features/planning/store';
import { planningApi } from '@/features/planning/api';
import { createBaseMessage, createErrorMessage } from '@/features/planning/utils/message-helpers';
import { logger } from '@/features/planning/utils/logger';
import { normalizeGisLayers } from '@/features/planning/utils/gis-normalize';
import { fetchCurrentSourceLayers, type CurrentSourceLayersResult } from '@/features/planning/utils/offline-basemap';
import { getSessionIdFromUrl } from '@/features/planning/utils/session-url';
import { loadJintianDemoInput } from '@/features/planning/utils/demo-input';
import { syncIfEventSeqBehind } from '@/features/planning/utils/event-sync';
import { actionForHumanReview } from '@/features/planning/utils/interrupt-resume';
import {
  getWorkbenchNavFromUrl,
  resolveDefaultWorkbenchNav,
  setWorkbenchNavInUrl,
  type OverviewPanel,
  type WorkbenchView,
} from '@/features/planning/utils/workbench-nav';
import LlmStatusBanner from '@/features/planning/components/LlmStatusBanner';
import DeliveryStatusBanner from '@/features/planning/components/DeliveryStatusBanner';
import { IntermediateArtifactsPanel } from '@/features/planning/components/IntermediateArtifactsPanel';
import EvidenceQueryPanel from '@/features/planning/components/EvidenceQueryPanel';
import ExportDialog from '@/features/planning/components/ExportDialog';
import DeliveryCompliancePanel from '@/features/planning/components/DeliveryCompliancePanel';
import { isCapabilityEnabled, isNavItemEnabled } from '@/features/planning/config/v1-capabilities';
import type { PlanningParams } from '@/features/planning/types';
import type { Message } from '@/features/planning/types';
import type { GISLayerConfig } from '@/types/message/message-types';
import type { EvidenceFeatureRef, PositioningTraceResponse, PositioningTraceStep } from '@/features/planning/api/types';

type WorkbenchBaseMap = 'general' | 'amap';

type LayerFilter = 'all' | 'current' | 'planning' | 'constraints' | 'roads';

interface RoadProject {
  projectId?: string;
  routeName?: string;
  plannedWidthM?: number;
  status?: string;
  recommendedLengthM?: number;
  reviewLengthM?: number;
  hardViolations?: string[];
}

interface RoadProcess {
  road_target_count?: number;
  planning_node_count?: number;
  candidate_count?: number;
  recommended_segment_count?: number;
  recommended_segment_count_all?: number;
  recommended_segment_count_displayed?: number;
  validation?: { passed?: boolean; status?: string };
  kg?: { constraint_count?: number };
}

interface CompleteResultPayload {
  villageName?: string;
  layerCount?: number;
  layers?: Array<Record<string, unknown>>;
  roadProcess?: RoadProcess;
  roadProjects?: RoadProject[];
}

interface SpatialWorkflowStep {
  label: string;
  stage: string;
  status: 'recorded' | 'pending';
  value: string;
  expectedArtifactKeys: string[];
  registeredArtifactKeys: string[];
  humanReports: HumanReadablePlanningReport[];
}

interface HumanReadablePlanningReport {
  dimensionKey: string;
  title: string;
  statements: string[];
  claimCount: number;
  hasReportBody: boolean;
  projectHints: IntentProjectHint[];
}

interface IntentProjectHint {
  category: string;
  dimensionTitle: string;
  statement: string;
}

const SPATIAL_WORKFLOW_STAGES: Array<{
  stages: string[];
  label: string;
  artifactKeys: string[];
}> = [
  {
    stages: ['L3'],
    label: 'L3 规划意图',
    artifactKeys: ['l3_gate', 'planning_program'],
  },
  {
    stages: ['TARGET_PROJECTION'],
    label: '目标投影',
    artifactKeys: ['target_projection'],
  },
  { stages: ['GROUND'], label: '空间落位', artifactKeys: ['grounding_result'] },
  {
    stages: ['SELECT'],
    label: '候选选址',
    artifactKeys: ['demand_portfolio', 'suitability_surface', 'portfolio_decision', 'site_selection'],
  },
  {
    stages: ['EXECUTE'],
    label: '空间执行',
    artifactKeys: ['execution_plan', 'execution_result', 'parcel_changeset', 'planned_state', 'planning_scenario'],
  },
  {
    stages: ['VALIDATE', 'RECONCILE'],
    label: '关系与几何校验',
    artifactKeys: ['validation_report', 'final_relation_validation', 'reconciliation_report'],
  },
  {
    stages: ['DELIVER', 'RENDER'],
    label: '空间成果交付',
    artifactKeys: [
      'delivery_manifest',
      'layout_configs',
      'render_layers',
      'delivery_spatial_snapshot',
      'export_result',
      'render_artifacts',
    ],
  },
];

const SPATIAL_ARTIFACT_GROUPS: Array<{ label: string; keys: string[] }> = [
  {
    label: '目标与落地',
    keys: [
      'target_projection',
      'grounding_result',
      'demand_portfolio',
      'suitability_surface',
      'portfolio_decision',
      'site_selection',
    ],
  },
  {
    label: '空间执行',
    keys: ['execution_plan', 'execution_result', 'parcel_changeset', 'planned_state', 'planning_scenario'],
  },
  {
    label: '校验与交付',
    keys: [
      'validation_report',
      'final_relation_validation',
      'reconciliation_report',
      'delivery_manifest',
      'layout_configs',
      'render_layers',
      'delivery_spatial_snapshot',
      'export_result',
      'render_artifacts',
    ],
  },
];

const SPATIAL_ARTIFACT_KEY_SET = new Set(SPATIAL_ARTIFACT_GROUPS.flatMap((group) => group.keys));

const SPATIAL_ARTIFACT_LABELS: Record<string, string> = {
  l3_gate: 'L3 规划闸门',
  planning_program: '规划程序草案',
  target_projection: '目标投影',
  grounding_result: '空间落位结果',
  demand_portfolio: '需求组合',
  suitability_surface: '适宜性面',
  portfolio_decision: '组合决策',
  site_selection: '选址结果',
  execution_plan: '执行计划',
  execution_result: '执行结果',
  parcel_changeset: '地块变更集',
  planned_state: '规划状态',
  planning_scenario: '规划情景',
  validation_report: '校验报告',
  final_relation_validation: '最终关系校验',
  reconciliation_report: '一致性报告',
  delivery_manifest: '交付清单',
  layout_configs: '空间布局配置',
  render_layers: '渲染图层',
  delivery_spatial_snapshot: '交付空间快照',
  export_result: '导出结果',
  render_artifacts: '渲染产物',
};

function summarizeSpatialTraceStep(step: PositioningTraceStep | undefined): string {
  if (!step) return '后端尚未到达该阶段';
  const outputs = step.outputs || {};
  const parts: string[] = [];
  const labels: Record<string, string> = {
    word_count: '正文',
    claim_count: '判断',
    claims_with_evidence: '有证据判断',
    intervention_count: '干预事项',
    llm_rewrites_applied: 'LLM 二次改写',
    target_projection_node: '目标投影节点',
    grounding_candidate_count: '落位候选',
    candidate_count: '候选线',
    recommended_segment_count: '推荐段',
    road_target_count: '道路项目',
  };
  for (const [key, value] of Object.entries(outputs)) {
    const label = labels[key];
    if (!label || value == null || value === '') continue;
    if (typeof value === 'object') {
      parts.push(`${label}已登记`);
    } else if (typeof value === 'boolean') {
      parts.push(`${label}${value ? '已应用' : '未应用'}`);
    } else {
      parts.push(`${label} ${value}${key === 'word_count' ? ' 字' : ' 项'}`);
    }
    if (parts.length >= 2) break;
  }
  return parts.join(' · ') || `已记录 ${step.step_name || step.stage}`;
}

const INTENT_PROJECT_ACTIONS: Array<{ category: string; patterns: RegExp[] }> = [
  {
    category: '改造提升',
    patterns: [/改造/, /整治/, /修缮/, /提升改造/, /扩建/, /更新/],
  },
  {
    category: '完善补齐',
    patterns: [/完善(?:[^。；]*)(?:设施|配套|体系|覆盖|服务)/, /补齐/, /健全/],
  },
  {
    category: '保护管控',
    patterns: [/保护/, /保育/, /生态修复/, /修复/, /管控/, /避让/, /划定[^。；]*(?:保护|红线|生态|农田|缓冲区|廊道)/],
  },
  {
    category: '规划布局',
    patterns: [/布局/, /组团式/, /划定[^。；]*(?:建设区|发展区|分区)/, /确定为重点发展区/],
  },
  {
    category: '建设配置',
    patterns: [
      /新建/,
      /(?<!划定)建设[^。；]*(?:设施|中心|道路|基地|园|站|工程|场所|厕所|广场|区|点|所|池|廊道|服务)/,
      /设置[^。；]*(?:处|座|点|中心|设施|基站|变压器)/,
      /建立[^。；]*(?:体系|平台|中心|设施)/,
    ],
  },
];

function extractIntentProjectHints(statements: string[], dimensionTitle: string): IntentProjectHint[] {
  const seen = new Set<string>();
  const hints: IntentProjectHint[] = [];
  for (const statement of statements) {
    const action = INTENT_PROJECT_ACTIONS.find(({ patterns }) => patterns.some((pattern) => pattern.test(statement)));
    if (!action) continue;
    const key = `${action.category}:${statement}`;
    if (seen.has(key)) continue;
    seen.add(key);
    hints.push({ category: action.category, dimensionTitle, statement });
  }
  return hints;
}

function parseHumanReadablePlanningReport(dimensionKey: string, content: string): HumanReadablePlanningReport | null {
  const trimmed = content.trim();
  if (!trimmed) return null;

  const title = getDimensionName(dimensionKey) || dimensionKey;
  if (!trimmed.startsWith('{')) {
    return {
      dimensionKey,
      title,
      statements: [],
      claimCount: 0,
      hasReportBody: true,
      projectHints: [],
    };
  }

  try {
    const parsed = JSON.parse(trimmed) as Record<string, unknown>;
    const reportBody = typeof parsed.report_body === 'string' ? parsed.report_body.trim() : '';
    const claims = Array.isArray(parsed.claims) ? parsed.claims : [];
    const statements = claims
      .map((claim) => {
        if (!claim || typeof claim !== 'object') return '';
        const statement = (claim as { statement?: unknown }).statement;
        return typeof statement === 'string' ? statement.trim() : '';
      })
      .filter(Boolean);
    return {
      dimensionKey,
      title,
      statements,
      claimCount: statements.length,
      hasReportBody: Boolean(reportBody),
      projectHints: extractIntentProjectHints(statements, title),
    };
  } catch {
    return null;
  }
}

function buildHumanReadablePlanningReports(reports: Record<string, string>): HumanReadablePlanningReport[] {
  return Object.entries(reports || {})
    .map(([dimensionKey, content]) => parseHumanReadablePlanningReport(dimensionKey, content))
    .filter((report): report is HumanReadablePlanningReport => Boolean(report))
    .filter((report) => report.statements.length > 0 || report.hasReportBody);
}

function buildSpatialWorkflowSteps(
  trace: PositioningTraceResponse | null,
  artifactKeys: Set<string>,
  layer3Reports: Record<string, string>,
): SpatialWorkflowStep[] {
  const reports = trace?.reports || [];
  const humanReports = buildHumanReadablePlanningReports(layer3Reports);
  return SPATIAL_WORKFLOW_STAGES.map(({ stages, label, artifactKeys: expectedArtifactKeys }) => {
    const stageReports = reports.filter((report) => {
      if (stages.includes('L3')) return report.stage === 'L3';
      return stages.includes(report.stage);
    });
    const latest = stageReports[stageReports.length - 1];
    return {
      label,
      stage: latest?.stage || stages.join(' / '),
      status: latest ? 'recorded' : 'pending',
      value: summarizeSpatialTraceStep(latest),
      expectedArtifactKeys,
      registeredArtifactKeys: expectedArtifactKeys.filter((key) => artifactKeys.has(key)),
      humanReports: stages.includes('L3') ? humanReports : [],
    };
  });
}

function IntentProjectOverview({
  projects,
  claimCount,
  dimensionCount,
  workflowSteps,
}: {
  projects: IntentProjectHint[];
  claimCount: number;
  dimensionCount: number;
  workflowSteps: SpatialWorkflowStep[];
}) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [listOpen, setListOpen] = useState(false);
  const selectedProject = projects[selectedIndex] || projects[0];
  const categoryCounts = Array.from(new Set(projects.map((project) => project.category))).map((category) => ({
    category,
    count: projects.filter((project) => project.category === category).length,
  }));

  useEffect(() => {
    if (selectedIndex >= projects.length) setSelectedIndex(0);
  }, [projects.length, selectedIndex]);

  if (!selectedProject) {
    return (
      <div className="mt-2 rounded-xl border border-[#e5f0eb] bg-[#f8fcfa] px-3 py-2.5 text-[10px] leading-4 text-[#78968b]">
        当前 claims 主要是现状判断或规划原则，尚未形成可归类的实施项目。
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-xl border border-[#cfe8dc] bg-[#f7fcf9] p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold text-[#2d7e61]">规划意图 · 实施项目</div>
          <div className="mt-0.5 text-[10px] text-[#78968b]">
            {projects.length} 条真实项目线索 · {dimensionCount} 个维度 · {claimCount} 条结构化判断
          </div>
        </div>
        <button
          type="button"
          onClick={() => setListOpen(true)}
          className="shrink-0 rounded-lg border border-[#bfe2d1] bg-white px-2 py-1 text-[10px] font-medium text-[#2d7e61] hover:bg-[#e8f6ef]"
        >
          查看全部
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {categoryCounts.map(({ category, count }) => (
          <span
            key={category}
            className="rounded-full bg-white px-2 py-1 text-[9px] text-[#397b62] ring-1 ring-[#dceee5]"
          >
            {category} {count}
          </span>
        ))}
      </div>
      <div className="mt-3 rounded-xl border border-[#dceee5] bg-white p-3 shadow-sm">
        <div className="flex flex-wrap items-center gap-1.5 text-[9px]">
          <span className="rounded-full bg-[#e8f6ef] px-2 py-1 font-semibold text-[#2d7e61]">
            {selectedProject.category}
          </span>
          <span className="rounded-full bg-[#f1f7f4] px-2 py-1 text-[#6e8d81]">
            来源 · {selectedProject.dimensionTitle}
          </span>
        </div>
        <p className="mt-2 break-words text-[12px] leading-6 text-[#3f6256]">{selectedProject.statement}</p>
      </div>
      <div className="mt-2 rounded-lg bg-white px-2.5 py-2 text-[10px] leading-4 text-[#78968b]">
        下方“空间链路”按真实后端阶段承接当前项目线索；未到达阶段不会显示示意结果。
      </div>

      {listOpen && (
        <div className="fixed inset-0 z-[75] flex items-center justify-center bg-[#17382d]/25 p-4 backdrop-blur-[1px]">
          <div className="flex h-[min(780px,calc(100vh-32px))] w-[min(1040px,calc(100vw-32px))] flex-col overflow-hidden rounded-2xl border border-[#cfe8dc] bg-[#fbfefc] shadow-2xl">
            <div className="flex shrink-0 items-center justify-between border-b border-[#e1eee8] bg-white px-5 py-3">
              <div>
                <div className="text-sm font-semibold text-[#2d6653]">规划意图 · 实施项目线索</div>
                <div className="mt-0.5 text-[11px] text-[#78968b]">
                  来自真实 L3 claims；左侧选择项目，右侧查看它与空间链路的关系
                </div>
              </div>
              <button
                type="button"
                onClick={() => setListOpen(false)}
                className="rounded-lg border border-[#d8e9e1] px-3 py-1.5 text-xs text-[#527467] hover:bg-[#eef8f3]"
              >
                关闭
              </button>
            </div>
            <div className="grid min-h-0 flex-1 md:grid-cols-[340px_minmax(0,1fr)]">
              <div className="min-h-0 overflow-y-auto border-b border-[#e1eee8] bg-[#f4faf7] p-3 md:border-b-0 md:border-r">
                <div className="mb-2 flex flex-wrap gap-1">
                  {categoryCounts.map(({ category, count }) => (
                    <span
                      key={category}
                      className="rounded-full bg-white px-2 py-1 text-[10px] text-[#397b62] ring-1 ring-[#dceee5]"
                    >
                      {category} {count}
                    </span>
                  ))}
                </div>
                <div className="space-y-1.5">
                  {projects.map((project, index) => (
                    <button
                      key={`${project.dimensionTitle}-${index}`}
                      type="button"
                      onClick={() => setSelectedIndex(index)}
                      className={`w-full rounded-xl border p-2.5 text-left transition ${selectedIndex === index ? 'border-[#78c7a5] bg-white shadow-sm' : 'border-transparent bg-white/65 hover:border-[#cfe8dc]'}`}
                    >
                      <div className="flex items-center gap-1.5">
                        <span className="rounded-full bg-[#e8f6ef] px-1.5 py-0.5 text-[9px] text-[#397b62]">
                          {project.category}
                        </span>
                        <span className="truncate text-[9px] text-[#8aa59a]">{project.dimensionTitle}</span>
                      </div>
                      <div className="mt-1 line-clamp-2 text-[11px] leading-5 text-[#55786b]">{project.statement}</div>
                    </button>
                  ))}
                </div>
              </div>
              <div className="min-h-0 overflow-y-auto p-5">
                <div className="rounded-2xl border border-[#cfe8dc] bg-white p-4 shadow-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-[#e8f6ef] px-2.5 py-1 text-[10px] font-semibold text-[#2d7e61]">
                      {selectedProject.category}
                    </span>
                    <span className="text-[11px] text-[#78968b]">{selectedProject.dimensionTitle}</span>
                  </div>
                  <p className="mt-3 break-words text-[14px] leading-7 text-[#365b4e]">{selectedProject.statement}</p>
                </div>
                <div className="mt-4 rounded-2xl border border-[#dceee5] bg-white p-4">
                  <div className="text-[12px] font-semibold text-[#315f50]">从意图到空间成果</div>
                  <div className="mt-1 text-[11px] leading-5 text-[#78968b]">
                    这里展示当前会话真实到达的阶段，不把尚未生成的空间结果填成示意数据。
                  </div>
                  <div className="mt-4 space-y-2">
                    {workflowSteps.map((step, index) => {
                      const ready = step.status === 'recorded' || step.registeredArtifactKeys.length > 0;
                      return (
                        <div key={step.label} className="flex items-center gap-3">
                          <div
                            className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${ready ? 'bg-[#42b48a] text-white' : 'bg-[#eef3f0] text-[#9aada6]'}`}
                          >
                            {ready ? '✓' : index + 1}
                          </div>
                          <div className="min-w-0 flex-1 rounded-xl border border-[#edf4f0] px-3 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-[11px] font-semibold text-[#527467]">{step.label}</span>
                              <span className={`text-[10px] ${ready ? 'text-[#2d7e61]' : 'text-[#9aada6]'}`}>
                                {ready ? '已记录' : '尚未到达'}
                              </span>
                            </div>
                            <div className="mt-0.5 text-[10px] text-[#8aa59a]">{step.value}</div>
                            {step.registeredArtifactKeys.length > 0 && (
                              <div className="mt-1 text-[10px] text-[#397b62]">
                                artifact：
                                {step.registeredArtifactKeys
                                  .map((key) => SPATIAL_ARTIFACT_LABELS[key] || key)
                                  .join('、')}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

type SpatialSidebarTab = 'assistant' | 'spatial' | 'kg';
type SpatialAssistantMode = 'locator' | 'chat';

function layerMergeKey(layer: GISLayerConfig): string {
  const path = String(layer.metadata?.path ?? '');
  return `${layer.layerName}::${path}`;
}

function mergeGisLayerSources(staticLayers: GISLayerConfig[], liveLayers: GISLayerConfig[]): GISLayerConfig[] {
  if (!liveLayers.length) return staticLayers;
  if (!staticLayers.length) return liveLayers;

  const merged = new Map<string, GISLayerConfig>();
  for (const layer of staticLayers) {
    merged.set(layerMergeKey(layer), layer);
  }
  for (const layer of liveLayers) {
    merged.set(layerMergeKey(layer), layer);
  }
  return [...merged.values()];
}

const FILTERS: Array<{ key: LayerFilter; label: string }> = [
  { key: 'all', label: '全部成果' },
  { key: 'current', label: '现状' },
  { key: 'planning', label: '规划' },
  { key: 'constraints', label: '约束' },
  { key: 'roads', label: '道路' },
];

const CONTROL_NAMES = ['永久基本农田', '生态保护红线', '历史文化保护', '村庄建设边界'];

function featureCount(layer?: GISLayerConfig): number {
  return layer ? (layer.featureCount ?? layer.geojson.features.length) : 0;
}

function v1LayerGroup(layer: GISLayerConfig): string {
  return String(layer.metadata?.v1_layer_type ?? '').toLowerCase();
}

function v1LayerName(layer: GISLayerConfig): string {
  return String(layer.metadata?.v1_layer_name ?? '').toLowerCase();
}

function isV1PlannedLanduse(layer: GISLayerConfig): boolean {
  const name = v1LayerName(layer);
  return v1LayerGroup(layer) === 'planned' && (name === 'complete_planned_landuse' || name === 'planned_landuse');
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value);
}

function layerRole(layer: GISLayerConfig): string {
  return String(layer.metadata?.displayRole ?? '');
}

const REFERENCE_DISPLAY_ROLES = new Set([
  'original_planning_reference',
  'historical_planned_road_reference',
  'source_annotation',
  'stage5_full_network',
]);

function isReferenceDisplayRole(role: string): boolean {
  return REFERENCE_DISPLAY_ROLES.has(role);
}

function isLegacyCadArtifact(layer: GISLayerConfig): boolean {
  const path = String(layer.metadata?.path ?? '');
  return path.includes('/project/') && ['lines', 'polygons', 'points'].includes(layer.layerName);
}

function isNoiseLayer(layer: GISLayerConfig): boolean {
  const path = String(layer.metadata?.path ?? '');
  return path.includes('/api/amap/') || path.includes('/api/tianditu/') || path.includes('/demo/');
}

function matchesFilter(layer: GISLayerConfig, filter: LayerFilter): boolean {
  if (layer.visible === false) return false;
  if (isNoiseLayer(layer)) return false;
  if (isLegacyCadArtifact(layer)) return false;

  const name = layer.layerName;
  const role = layerRole(layer);

  if (filter === 'all') {
    return true;
  }
  if (filter === 'roads') {
    return (
      layer.layerType === 'planned_road' ||
      role.includes('road') ||
      role === 'stage5_full_network' ||
      name === '现状道路' ||
      name === 'road' ||
      name === 'lines'
    );
  }
  if (filter === 'constraints') {
    return (
      role === 'control_reference' ||
      layer.layerType === 'construction_control' ||
      layer.layerType === 'hazard_point' ||
      CONTROL_NAMES.some((item) => name.includes(item)) ||
      ['farmland_protection', 'ecological_protection', 'historical_protection', 'construction_zone'].includes(name)
    );
  }
  if (filter === 'current') {
    return (
      name.includes('现状') ||
      role === 'source_annotation' ||
      (layer.dataAuthority === 'authoritative_current' && !name.includes('规划'))
    );
  }

  if (v1LayerGroup(layer) === 'planned' || v1LayerGroup(layer) === 'overlay') return true;
  if (role === 'source_annotation') return false;
  if (name.includes('现状')) return false;
  if (role === 'control_reference' || layer.layerType === 'hazard_point') return false;

  if (isReferenceDisplayRole(role)) return true;

  return (
    layer.layerType === 'boundary' ||
    name === '国土空间用途规划' ||
    String(layer.layerType) === 'custom_functional_zone' ||
    String(layer.layerType) === 'facility' ||
    layer.layerType === 'planned_road' ||
    role === 'spatial_structure' ||
    layer.layerType === 'development_axis' ||
    role === 'road_review_corridor' ||
    name.includes('规划') ||
    name.includes('Stage5') ||
    name.includes('空间结构') ||
    layer.layerType === 'planning_zone'
  );
}

function isFacilityAnnotationLayer(layer: GISLayerConfig): boolean {
  return layer.layerType === 'facility_point' && layerRole(layer) === 'source_annotation';
}

function matchesQuickLayer(layer: GISLayerConfig, key: string): boolean {
  const name = layer.layerName;
  const path = layer.metadata?.path ?? '';
  const role = layerRole(layer);
  const isCurrent = path.includes('/current/') || name.includes('现状');
  const isPlanned = path.includes('/planned/') || name === '国土空间用途规划';
  const isProject = path.includes('/project/');

  switch (key) {
    case 'current-landuse':
      return (
        role === 'current_landuse' ||
        name === '现状地块' ||
        name.includes('现状用地') ||
        (name === 'landuse' && isCurrent)
      );
    case 'current-roads':
      return role === 'current_road' || name === '现状道路' || (name === 'road' && isCurrent);
    case 'facilities':
      return (
        String(layer.layerType) === 'facility' ||
        (layer.layerType === 'facility_point' && (role === 'source_annotation' || !role))
      );
    case 'hazards':
      return layer.layerType === 'hazard_point';
    case 'planned-landuse':
      return isV1PlannedLanduse(layer) || name === '国土空间用途规划' || (name === 'landuse' && isPlanned);
    case 'custom-zones':
      return String(layer.layerType) === 'custom_functional_zone' || (name === 'polygons' && isProject);
    case 'structure':
      return role === 'spatial_structure' || (name === 'polygons' && isPlanned);
    case 'reference-roads':
      return role === 'historical_planned_road_reference' || (name === 'road' && path.includes('/planned/'));
    case 'stage5-final':
      return (
        layer.layerType === 'planned_road' &&
        role !== 'stage5_full_network' &&
        (name.includes('本轮') || (name === 'lines' && isProject))
      );
    case 'stage5-full':
      return role === 'stage5_full_network' || (name === 'lines' && isProject);
    case 'farmland':
      return name.includes('永久基本农田') || name === 'farmland_protection';
    case 'ecology':
      return name.includes('生态保护') || name === 'ecological_protection';
    case 'heritage':
      return name.includes('历史文化') || name === 'historical_protection';
    case 'construction':
      return name.includes('村庄建设边界') || name === 'construction_zone';
    default:
      return false;
  }
}

function SidebarNav({ activeId, onNavigate }: { activeId: SidebarNavId; onNavigate: (id: SidebarNavId) => void }) {
  const groups: Array<{
    title: string;
    items: Array<{ id: SidebarNavId; label: string; hint?: string }>;
  }> = [
    {
      title: '规划总览',
      items: [
        { id: 'overview-task', label: '任务设置', hint: '填写村情与规划任务' },
        {
          id: 'overview-analysis',
          label: '分层分析',
          hint: 'L1/L2/L3 维度报告',
        },
        { id: 'overview-document', label: '规划文本', hint: '目录式成果阅读' },
        {
          id: 'overview-evaluation',
          label: '质量评估',
          hint: '忠实度与引用核验',
        },
      ],
    },
    {
      title: '效果图纸',
      items: [{ id: 'drawings', label: '空间成果图', hint: 'GIS 图层与约束检查' }],
    },
    {
      title: '数据中心',
      items: [
        { id: 'data-kg', label: '知识图谱检查', hint: 'L1/L2 证据与空间链' },
        { id: 'data-metrics', label: '指标报表', hint: '实体统计与图层计数' },
        { id: 'data-compliance', label: '用地合规', hint: '平衡表与出口闸门' },
        {
          id: 'data-suitability',
          label: '双评价适宜性',
          hint: '生态/农业/建设适宜',
        },
      ],
    },
  ];

  return (
    <nav className="space-y-4">
      {groups.map((group) => (
        <section key={group.title}>
          <div className="px-3 text-[12px] font-semibold text-[#244f43]">{group.title}</div>
          <div className="mt-1.5 space-y-1">
            {group.items
              .filter((item) => isNavItemEnabled(item.id))
              .map((item) => {
                const active = item.id === activeId;
                const previewOnly =
                  item.id === 'overview-analysis' ||
                  item.id === 'overview-document' ||
                  item.id === 'overview-evaluation';
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onNavigate(item.id)}
                    className={`w-full rounded-xl px-3 py-2.5 text-left transition-colors ${
                      active
                        ? 'bg-white font-semibold text-[#168a65] shadow-[0_4px_16px_rgba(38,119,92,0.08)]'
                        : previewOnly
                          ? 'text-[#8aa59a] hover:bg-white/60'
                          : 'text-[#7ea294] hover:bg-white/60'
                    }`}
                  >
                    <div className="flex items-center gap-2 text-[13px]">
                      <span
                        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-lg text-[11px] ${active ? 'bg-[#e1f4eb] text-[#2d8c6d]' : 'text-[#9ab8ad]'}`}
                      >
                        <WorkbenchIcon icon={SIDEBAR_NAV_ICONS[item.id]} />
                      </span>
                      <span>{item.label}</span>
                    </div>
                    {item.hint && (
                      <div
                        className={`mt-0.5 text-[10px] leading-4 ${active ? 'pl-8 text-[#8aa59a]' : 'pl-8 text-[#a8c2b8]'}`}
                      >
                        {item.hint}
                      </div>
                    )}
                  </button>
                );
              })}
          </div>
        </section>
      ))}
    </nav>
  );
}

function DataCenterPanel({
  panel,
  sessionId,
  projectName,
  payload,
  layers,
  roadProjects,
  positioningTrace,
  spatialWorkflowSteps,
  spatialArtifactKeys,
  typeCount,
  totalFeatures,
  currentParcels,
  plannedParcels,
  constraints,
  onOpenDrawings,
}: {
  panel: DataPanel;
  sessionId: string | null;
  projectName?: string;
  payload: CompleteResultPayload | null;
  layers: GISLayerConfig[];
  roadProjects: RoadProject[];
  positioningTrace: PositioningTraceResponse | null;
  spatialWorkflowSteps: SpatialWorkflowStep[];
  spatialArtifactKeys: Set<string>;
  typeCount: number;
  totalFeatures: number;
  currentParcels: number;
  plannedParcels: number;
  constraints: number;
  onOpenDrawings: () => void;
}) {
  const recordedSpatialSteps = spatialWorkflowSteps.filter((step) => step.status === 'recorded').length;
  const l1L2Reports =
    positioningTrace?.reports.filter((report) => report.stage === 'L1' || report.stage === 'L2').length ?? 0;
  const hasDeliverySnapshot = spatialArtifactKeys.has('delivery_spatial_snapshot');

  if (panel === 'compliance') {
    if (!sessionId) {
      return (
        <section className="min-h-[420px] rounded-2xl border border-dashed border-[#cfe4da] bg-[#f8fcf9] p-8 text-center text-[12px] text-[#8aa59a]">
          请先启动规划会话后再运行用地平衡与合规闸门分析
        </section>
      );
    }
    return <DeliveryCompliancePanel sessionId={sessionId} projectName={projectName || payload?.villageName} />;
  }

  if (panel === 'suitability') {
    return (
      <section className="min-h-[420px] rounded-2xl border border-dashed border-[#cfe4da] bg-[#f8fcf9] p-8 text-center text-[12px] text-[#8aa59a]">
        双评价适宜性分析在 v1 后端已下线；适宜性结果已内化到 SELECT/EXECUTE 空间决策链，请查看空间成果图与交付投影。
      </section>
    );
  }

  if (panel === 'metrics') {
    return (
      <section className="min-h-[620px] overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-sm">
        <PanelTitle title="指标报表" note={`${payload?.villageName ?? '金田村'} · ${layers.length} 图层`} />
        <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            icon={WORKBENCH_METRIC_ICONS.spatialFeatures}
            value={totalFeatures}
            label="空间要素"
            note={`${typeCount} 类实体`}
          />
          <MetricCard
            icon={WORKBENCH_METRIC_ICONS.currentParcels}
            value={currentParcels}
            label="现状地块"
            note="Parcel"
          />
          <MetricCard
            icon={WORKBENCH_METRIC_ICONS.plannedParcels}
            value={plannedParcels}
            label="规划地块"
            note="PlannedParcel"
          />
          <MetricCard icon={WORKBENCH_METRIC_ICONS.constraints} value={constraints} label="管控约束" note="Zone" />
        </div>
        <div className="border-t border-[#edf4f0] p-4">
          <button
            type="button"
            onClick={onOpenDrawings}
            className="rounded-xl border border-[#cfe4da] bg-[#f4fbf8] px-4 py-3 text-[12px] font-medium text-[#2d7e61] transition hover:bg-[#eaf7f1]"
          >
            打开空间成果图查看图层叠加 →
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="min-h-[620px] overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-sm">
      <PanelTitle title="知识图谱与空间链" note="L1/L2 证据 · 空间交付" />
      <div className="space-y-4 p-4 text-[12px] leading-6 text-[#4a6d61]">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            icon={WORKBENCH_METRIC_ICONS.kgConstraints}
            value={l1L2Reports}
            label="L1/L2 记录"
            note="真实过程记录"
          />
          <MetricCard
            icon={WORKBENCH_METRIC_ICONS.spatialFeatures}
            value={recordedSpatialSteps}
            label="空间阶段"
            note={`${spatialWorkflowSteps.length} 个阶段`}
          />
          <MetricCard
            icon={WORKBENCH_METRIC_ICONS.plannedParcels}
            value={spatialArtifactKeys.size}
            label="空间产物"
            note="artifact 索引"
          />
          <MetricCard
            icon={WORKBENCH_METRIC_ICONS.validation}
            value={hasDeliverySnapshot ? 1 : 0}
            label="DELIVER 快照"
            note={hasDeliverySnapshot ? '已登记' : '尚未到达'}
          />
        </div>
        <div className="rounded-xl border border-[#e1eee8] bg-[#f8fbf9] p-4">
          <h4 className="text-[13px] font-semibold text-[#2d6f56]">空间链实际记录</h4>
          <div className="mt-3 space-y-2">
            {spatialWorkflowSteps.map((step, index) => (
              <div key={step.label} className="flex items-center justify-between gap-3 rounded-lg bg-white px-3 py-2">
                <span className="text-[#5f8174]">
                  {index + 1}. {step.label}
                </span>
                <span
                  className={`text-right font-semibold ${step.status === 'recorded' ? 'text-[#2d8c6d]' : 'text-[#9aada6]'}`}
                >
                  {step.status === 'recorded' ? step.value : '尚未到达'}
                </span>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] leading-5 text-[#8aa59a]">
            状态来自后端 positioning-trace；道路不是主流程，而是 EXECUTE 结果中的一个专题子项。
          </p>
        </div>
        <div className="rounded-xl border border-[#e1eee8] bg-[#f8fbf9] p-4">
          <h4 className="text-[13px] font-semibold text-[#2d6f56]">空间专题子项</h4>
          <div className="mt-3 space-y-2">
            {roadProjects.length === 0 && (
              <p className="text-[#8aa59a]">当前没有后端已交付的道路专题结果；这不代表整个空间链没有数据。</p>
            )}
            {roadProjects.map((project) => (
              <div key={project.projectId} className="rounded-lg border border-[#dcebe4] bg-white px-3 py-2">
                <div className="font-semibold text-[#385e52]">{project.routeName}</div>
                <div className="mt-1 text-[11px] text-[#6d8b80]">
                  {project.status === 'recommended' ? '推荐实施' : '待工程复核'}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function MetricCard({
  icon,
  value,
  label,
  note,
}: {
  icon: IconDefinition;
  value: number | string;
  label: string;
  note: string;
}) {
  return (
    <div className="flex min-w-0 items-center gap-3 rounded-2xl border border-[#e1eee8] bg-white px-4 py-3 shadow-[0_8px_24px_rgba(46,104,82,0.05)]">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#def3e9] text-lg text-[#258b69]">
        <WorkbenchIcon icon={icon} style={{ width: 18, height: 18 }} />
      </div>
      <div className="min-w-0">
        <div className="truncate text-[22px] font-semibold leading-6 tabular-nums text-[#23875f]">
          {typeof value === 'number' ? formatNumber(value) : value}
        </div>
        <div className="mt-1 truncate text-[11px] text-[#718f83]">
          {label} · {note}
        </div>
      </div>
    </div>
  );
}

function PanelTitle({ title, note }: { title: string; note?: string }) {
  return (
    <div className="flex items-center justify-between border-b border-[#edf4f0] px-4 py-3">
      <h3 className="flex items-center gap-2 text-[14px] font-semibold text-[#264f43]">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-[#e8f5ef] text-[#2d8c6d]">
          <WorkbenchIcon icon={PANEL_TITLE_ICON} style={{ width: 12, height: 12 }} />
        </span>
        {title}
      </h3>
      {note && <span className="text-[11px] text-[#9ab2a8]">{note}</span>}
    </div>
  );
}

function StepModeToggle({
  enabled,
  loading,
  compact,
  onChange,
}: {
  enabled: boolean;
  loading?: boolean;
  compact?: boolean;
  onChange: (enabled: boolean) => void;
}) {
  return (
    <div className={`flex items-center gap-2 ${compact ? '' : 'justify-between gap-3'}`}>
      {!compact && (
        <div>
          <div className="text-[12px] font-semibold text-[#25785b]">步骤模式</div>
          <p className="mt-0.5 text-[11px] text-[#718f83]">
            {enabled ? '每层完成后暂停，等待审核再进入下一层。' : '自动连续完成 L1 → L2 → L3。'}
          </p>
        </div>
      )}
      {compact && <span className="text-[11px] text-[#55796c]">步骤模式</span>}
      <button
        type="button"
        onClick={() => onChange(!enabled)}
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${loading ? 'opacity-70' : ''} ${enabled ? 'bg-[#3fb288]' : 'bg-[#c5d9cf]'}`}
        aria-label="切换步骤模式"
        aria-busy={loading}
        title={enabled ? '已开启：每层暂停审核' : '已关闭：自动连续分析'}
      >
        <span
          className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow transition-transform ${enabled ? 'left-6' : 'left-1'}`}
        />
      </button>
    </div>
  );
}

type OverviewLevel = 'L1 现状分析' | 'L2 规划思路' | 'L3 详细规划';
type DataPanel = 'kg' | 'metrics' | 'compliance' | 'suitability';
type SidebarNavId =
  | 'overview-task'
  | 'overview-analysis'
  | 'overview-document'
  | 'overview-evaluation'
  | 'drawings'
  | 'data-kg'
  | 'data-metrics'
  | 'data-compliance'
  | 'data-suitability';

const EXAMPLE_TASKS: Record<OverviewLevel, string> = {
  'L1 现状分析':
    '分析金田村现状用地、道路、公共服务设施、居民点和产业基础，识别永久基本农田、生态保护红线、历史文化保护与地质灾害约束，形成现状问题清单。',
  'L2 规划思路':
    '结合现状分析和知识图谱，形成“一核引领、一带串联、三区协同”的空间结构，明确产业、生态、生活功能分区及项目布局原则。',
  'L3 详细规划':
    '在现状分析和规划思路基础上生成规划地块、项目设施、用途指标和道路方案，按约束闸门、候选选线、评分与校验流程输出完整成果。验收窄切片：在当前 GIS 已登记的 BSM=441426211000049280 宅基地内落地 300 平方米防灾疏散场地，保留未占用部分并记录邻接地块。[SPATIAL_DEMO_NARROW_SLICE source_parcel_bsm=441426211000049280;footprint_area_m2=300]',
};

const OVERVIEW_LEVELS: OverviewLevel[] = ['L1 现状分析', 'L2 规划思路', 'L3 详细规划'];

const OVERVIEW_PANELS: Array<{
  id: OverviewPanel;
  label: string;
  note: string;
  icon: IconDefinition;
}> = [
  {
    id: 'task',
    label: '任务设置',
    note: '村情与规划要求',
    icon: SIDEBAR_NAV_ICONS['overview-task'],
  },
  {
    id: 'analysis',
    label: '详细分析',
    note: '28 个专题维度',
    icon: SIDEBAR_NAV_ICONS['overview-analysis'],
  },
  {
    id: 'document',
    label: '规划文本',
    note: '专题报告汇编',
    icon: SIDEBAR_NAV_ICONS['overview-document'],
  },
  ...(isCapabilityEnabled('qualityEvaluation')
    ? [
        {
          id: 'evaluation' as const,
          label: '质量评估',
          note: '忠实度与引用',
          icon: SIDEBAR_NAV_ICONS['overview-evaluation'],
        },
      ]
    : []),
];

function statusLabel(status: string): string {
  switch (status) {
    case 'planning':
      return '生成中';
    case 'paused':
      return '待审核';
    case 'revising':
      return '修订中';
    case 'collecting':
      return '收集中';
    case 'completed':
      return '已完成';
    default:
      return status || '待命';
  }
}

function OverviewWorkspaceHeader({
  overviewPanel,
  sessionId,
  status,
  stepMode,
  stepModeLoading,
  onPanelChange,
  onStepModeChange,
  evaluationActions,
}: {
  overviewPanel: OverviewPanel;
  sessionId: string | null;
  status: string;
  stepMode: boolean;
  stepModeLoading: boolean;
  completedLayers: Record<1 | 2 | 3, boolean>;
  onPanelChange: (panel: OverviewPanel) => void;
  onStepModeChange: (enabled: boolean) => void;
  evaluationActions?: {
    loading: boolean;
    hasResult: boolean;
    onRun: () => void;
    onRefresh: () => void;
  };
}) {
  return (
    <div className="relative z-30 flex shrink-0 items-center justify-between gap-3 border-b border-[#e5efe9] bg-white px-3 py-2">
      <div className="flex min-w-0 items-center gap-1 rounded-lg bg-[#f3f8f5] p-0.5">
        {OVERVIEW_PANELS.map((panel) => {
          const active = overviewPanel === panel.id;
          return (
            <button
              key={panel.id}
              type="button"
              onClick={() => onPanelChange(panel.id)}
              className={`rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors ${
                active ? 'bg-white text-[#1f7a59] shadow-sm' : 'text-[#5d7f72] hover:text-[#2d8c6d]'
              }`}
            >
              {panel.label}
            </button>
          );
        })}
      </div>
      <div className="flex shrink-0 items-center gap-2 text-[10px] text-[#8aa59a]">
        {evaluationActions && (
          <div className="flex items-center gap-2">
            {evaluationActions.hasResult && (
              <button
                type="button"
                onClick={evaluationActions.onRefresh}
                disabled={evaluationActions.loading}
                className="rounded-lg border border-[#d5e9df] px-2.5 py-1 text-[11px] text-[#52766a] hover:bg-[#f4faf7] disabled:cursor-not-allowed disabled:opacity-50"
              >
                刷新结果
              </button>
            )}
            <button
              type="button"
              onClick={evaluationActions.onRun}
              disabled={evaluationActions.loading}
              aria-busy={evaluationActions.loading}
              className="rounded-lg bg-[#3fb288] px-3 py-1.5 text-[11px] font-medium text-white hover:bg-[#319a75] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {evaluationActions.loading ? '评估中…' : evaluationActions.hasResult ? '重新评估' : '运行评估'}
            </button>
          </div>
        )}
        {sessionId && (
          <span className="rounded-full bg-[#eef6f1] px-2 py-0.5 font-medium text-[#3a8f6f]">
            {statusLabel(status)}
          </span>
        )}
        <StepModeToggle compact enabled={stepMode} loading={stepModeLoading} onChange={onStepModeChange} />
      </div>
    </div>
  );
}

function OverviewLevelTabs({ value, onChange }: { value: OverviewLevel; onChange: (level: OverviewLevel) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {OVERVIEW_LEVELS.map((level, index) => {
        const active = value === level;
        return (
          <button
            key={level}
            type="button"
            onClick={() => onChange(level)}
            className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] font-medium transition-colors ${
              active
                ? 'border-[#3fb288] bg-[#3fb288] text-white shadow-sm'
                : 'border-[#d6e8df] bg-white text-[#5d7f72] hover:border-[#9fd4bc]'
            }`}
          >
            <span
              className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] ${active ? 'bg-white/20' : 'bg-[#eef6f1] text-[#3a8f6f]'}`}
            >
              {index + 1}
            </span>
            {level}
          </button>
        );
      })}
    </div>
  );
}

interface PlanningTaskPanelProps {
  overviewLevel: OverviewLevel;
  onOverviewLevelChange: (level: OverviewLevel) => void;
  projectName: string;
  villageData: string;
  taskDescription: string;
  constraintsText: string;
  province: string;
  city: string;
  county: string;
  township: string;
  villageName: string;
  planningPeriod: string;
  planningError: string;
  stepMode: boolean;
  stepModeLoading: boolean;
  onChange: (field: string, value: string) => void;
  onFillExample: () => void | Promise<void>;
  onStart: () => void;
  onStepModeChange: (enabled: boolean) => void;
  isStarting?: boolean;
  villageDataFiles: File[];
  taskFiles: File[];
  constraintFiles: File[];
  onFilesChange: (field: 'villageDataFiles' | 'taskFiles' | 'constraintFiles', files: File[]) => void;
}

function TaskFilePicker({ id, files, onChange }: { id: string; files: File[]; onChange: (files: File[]) => void }) {
  return (
    <div className="mt-2 rounded-lg border border-dashed border-[#cfe4da] bg-[#f8fcfa] px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={id} className="cursor-pointer text-[11px] font-medium text-[#3a8f6f]">
          上传附件
          <input
            id={id}
            type="file"
            multiple
            accept={FILE_ACCEPT}
            className="sr-only"
            onChange={(event) => {
              onChange([...files, ...Array.from(event.target.files || [])]);
              event.currentTarget.value = '';
            }}
          />
        </label>
        <span className="text-[10px] text-[#8aa59a]">
          {files.length ? `${files.length} 个文件` : '可选 · 非 GIS 文件将由 MinerU 转为 Markdown'}
        </span>
      </div>
      {files.length > 0 && (
        <div className="mt-1.5 space-y-1">
          {files.map((file, index) => (
            <div
              key={`${file.name}-${file.size}-${index}`}
              className="flex items-center justify-between gap-2 text-[10px] text-[#6d8c80]"
            >
              <span className="min-w-0 truncate">{file.name}</span>
              <button
                type="button"
                onClick={() => onChange(files.filter((_, itemIndex) => itemIndex !== index))}
                className="shrink-0 text-[#b36a55] hover:underline"
              >
                移除
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PlanningTaskPanel(props: PlanningTaskPanelProps) {
  const fieldClass =
    'mt-1.5 w-full rounded-xl border border-[#d6e8df] bg-[#fbfdfc] px-3 py-2.5 text-[12px] font-normal outline-none transition focus:border-[#43aa82] focus:bg-white focus:ring-2 focus:ring-[#dff3ea]';
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 pb-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#dcebe4] bg-gradient-to-r from-[#f3faf7] to-white px-3 py-3">
          <div className="min-w-0">
            <div className="text-[12px] font-semibold text-[#2d7e61]">规划任务模板</div>
            <p className="mt-0.5 text-[11px] leading-5 text-[#718f83]">
              一键加载完整现状报告；GIS 仅来自当前 session 已准入的 DATA catalog。
            </p>
            <div className="mt-2">
              <OverviewLevelTabs value={props.overviewLevel} onChange={props.onOverviewLevelChange} />
            </div>
          </div>
          <button
            type="button"
            onClick={props.onFillExample}
            className="shrink-0 rounded-lg bg-[#3fb288] px-3.5 py-2 text-[11px] font-semibold text-white shadow-sm hover:bg-[#359f7b]"
          >
            一键加载完整示例
          </button>
        </div>
        <div className="grid gap-3 xl:grid-cols-3">
          <section className="rounded-2xl border border-[#dcebe4] bg-white p-4 shadow-sm">
            <h3 className="mb-3 flex items-center gap-2 text-[14px] font-bold text-[#284f43]">
              <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-[#e8f5ef] text-[11px] text-[#2d8c6d]">
                1
              </span>
              基本信息
            </h3>
            <label className="block text-[12px] font-semibold">
              项目名称<span className="text-rose-500"> *</span>
              <input
                value={props.projectName}
                onChange={(event) => props.onChange('projectName', event.target.value)}
                placeholder="例如：金田村村庄规划（2026—2035年）"
                className={fieldClass}
              />
            </label>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <label className="text-[11px] font-semibold">
                省份
                <input
                  value={props.province}
                  onChange={(event) => props.onChange('province', event.target.value)}
                  placeholder="广东省"
                  className={fieldClass}
                />
              </label>
              <label className="text-[11px] font-semibold">
                城市
                <input
                  value={props.city}
                  onChange={(event) => props.onChange('city', event.target.value)}
                  placeholder="梅州市"
                  className={fieldClass}
                />
              </label>
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2">
              <label className="text-[11px] font-semibold">
                县区
                <input
                  value={props.county}
                  onChange={(event) => props.onChange('county', event.target.value)}
                  placeholder="平远县"
                  className={fieldClass}
                />
              </label>
              <label className="text-[11px] font-semibold">
                乡镇
                <input
                  value={props.township}
                  onChange={(event) => props.onChange('township', event.target.value)}
                  placeholder="泗水镇"
                  className={fieldClass}
                />
              </label>
              <label className="text-[11px] font-semibold">
                村庄
                <input
                  value={props.villageName}
                  onChange={(event) => props.onChange('villageName', event.target.value)}
                  placeholder="金田村"
                  className={fieldClass}
                />
              </label>
            </div>
            <label className="mt-3 block text-[12px] font-semibold">
              规划期限
              <input
                value={props.planningPeriod}
                onChange={(event) => props.onChange('planningPeriod', event.target.value)}
                placeholder="例如：2026—2035年"
                className={fieldClass}
              />
            </label>
          </section>
          <section className="rounded-2xl border border-[#dcebe4] bg-white p-4 shadow-sm">
            <h3 className="mb-3 flex items-center gap-2 text-[14px] font-bold text-[#284f43]">
              <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-[#e8f5ef] text-[11px] text-[#2d8c6d]">
                2
              </span>
              村庄数据
            </h3>
            <label className="block text-[12px] font-semibold">
              村庄基础数据<span className="text-rose-500"> *</span>
              <textarea
                value={props.villageData}
                onChange={(event) => props.onChange('villageData', event.target.value)}
                placeholder="请输入人口、面积、自然资源、产业基础、公共设施、历史文化等基础情况。"
                rows={8}
                className={`${fieldClass} resize-y leading-5`}
              />
            </label>
            <TaskFilePicker
              id="village-data-file-upload"
              files={props.villageDataFiles}
              onChange={(files) => props.onFilesChange('villageDataFiles', files)}
            />
            <div className="mt-3 rounded-lg bg-[#eef8f3] px-3 py-2 text-[11px] leading-5 text-[#5f8174]">
              GIS 图层只从当前 session 的已准入 DATA catalog 加载；一键示例不会注入
              隐式 GIS 文件。非 GIS 附件会先由 MinerU 转成 Markdown；图表保留为文本表格，图片先登记为待补充的多模态证据，不阻塞规划。
            </div>
          </section>
          <section className="rounded-2xl border border-[#dcebe4] bg-white p-4 shadow-sm">
            <h3 className="mb-3 flex items-center gap-2 text-[14px] font-bold text-[#284f43]">
              <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-[#e8f5ef] text-[11px] text-[#2d8c6d]">
                3
              </span>
              规划要求
            </h3>
            <label className="block text-[12px] font-semibold">
              任务描述<span className="text-rose-500"> *</span>
              <textarea
                value={props.taskDescription}
                onChange={(event) => props.onChange('taskDescription', event.target.value)}
                placeholder="请输入规划目标、重点任务和希望生成的成果。"
                rows={4}
                className={`${fieldClass} resize-y leading-5`}
              />
            </label>
            <TaskFilePicker
              id="task-description-file-upload"
              files={props.taskFiles}
              onChange={(files) => props.onFilesChange('taskFiles', files)}
            />
            <label className="mt-3 block text-[12px] font-semibold">
              规划约束
              <textarea
                value={props.constraintsText}
                onChange={(event) => props.onChange('constraintsText', event.target.value)}
                placeholder="请输入农田、生态红线、历史保护、建设边界和灾害风险等约束。"
                rows={3}
                className={`${fieldClass} resize-y leading-5`}
              />
            </label>
            <TaskFilePicker
              id="constraints-file-upload"
              files={props.constraintFiles}
              onChange={(files) => props.onFilesChange('constraintFiles', files)}
            />
          </section>
        </div>
        {props.planningError && (
          <p className="mt-3 rounded-xl bg-red-50 p-3 text-xs text-red-600">{props.planningError}</p>
        )}
        <div className="mt-3 rounded-xl border border-[#dcebe4] bg-[#f8fbf9] px-3 py-2.5">
          <StepModeToggle enabled={props.stepMode} loading={props.stepModeLoading} onChange={props.onStepModeChange} />
        </div>
      </div>
      <div className="shrink-0 border-t border-[#e5efe9] bg-white/95 px-4 py-3 backdrop-blur-sm">
        <div className="flex justify-center">
          <button
            onClick={props.onStart}
            disabled={props.isStarting || !props.projectName.trim() || !props.taskDescription.trim()}
            className="rounded-full bg-[#3fb288] px-10 py-3 text-[13px] font-semibold text-white shadow-md transition hover:bg-[#359f7b] disabled:bg-[#acd8c7]"
          >
            {props.isStarting ? '正在启动…' : '开始规划 →'}
          </button>
        </div>
      </div>
    </div>
  );
}

function PlanningAnalysisWorkspace({
  isPaused,
  onApprove,
  onGoToTask,
  onExport,
  chatPanel,
  sessionConnected,
}: {
  isPaused: boolean;
  onApprove: () => void;
  onGoToTask: () => void;
  onExport?: () => void;
  chatPanel: React.ReactNode;
  sessionConnected: boolean;
}) {
  const reports = usePlanningStore((state) => state.reports);
  const status = usePlanningStore((state) => state.status);
  const dimensionProgress = usePlanningStore((state) => state.dimensionProgress);
  const streamingContent = usePlanningStore((state) => state.streamingContent);
  const selectedNavigationKey = usePlanningStore((state) => state.selectedNavigationKey);
  const setSelectedNavigationKey = usePlanningStore((state) => state.setSelectedNavigationKey);
  const executingDimensions = usePlanningStore((state) => state.executingDimensions);
  const pendingReviewLayer = usePlanningStore((state) => state.pendingReviewLayer);
  const humanReview = usePlanningStore((state) => state.humanReview);
  const reviewActionLabel =
    actionForHumanReview({
      pending_items: humanReview?.items ?? [],
    }) === 'retry'
      ? '重试并继续'
      : '批准继续';
  const [activeLayer, setActiveLayer] = useState<1 | 2 | 3>(1);
  const [sidebarWidth, setSidebarWidth] = useState(212);
  const sidebarResizeRef = useRef<{ start: number; value: number } | null>(null);

  const layerTabs: Array<{ layer: 1 | 2 | 3; label: string; short: string }> = [
    { layer: 1, label: 'L1 现状', short: '现状' },
    { layer: 2, label: 'L2 思路', short: '思路' },
    { layer: 3, label: 'L3 详规', short: '详规' },
  ];

  const totalDimensions = useMemo(
    () => [1, 2, 3].reduce((sum, layer) => sum + DIMENSIONS_BY_LAYER[layer].length, 0),
    [],
  );
  const completedCount = useMemo(
    () =>
      [1, 2, 3].reduce(
        (sum, layer) => sum + Object.keys(reports[`layer${layer}` as 'layer1' | 'layer2' | 'layer3'] ?? {}).length,
        0,
      ),
    [reports],
  );

  useEffect(() => {
    if (!selectedNavigationKey?.startsWith('dim:')) return;
    const layer = Number.parseInt(selectedNavigationKey.slice(4).split('_')[0] || '1', 10);
    if (layer >= 1 && layer <= 3) setActiveLayer(layer as 1 | 2 | 3);
  }, [selectedNavigationKey]);

  const isOverview = selectedNavigationKey === NAV_KEYS.OVERVIEW;

  const getDimensionTone = useCallback(
    (layer: number, dimension: string) => {
      const progressKey = `${layer}_${dimension}`;
      const layerReports = reports[`layer${layer}` as 'layer1' | 'layer2' | 'layer3'] ?? {};
      const completed =
        Object.prototype.hasOwnProperty.call(layerReports, dimension) ||
        dimensionProgress[progressKey]?.status === 'completed';
      const streaming = !!streamingContent[progressKey] && !completed;
      const executing = executingDimensions.includes(progressKey);
      if (executing || streaming) return 'running' as const;
      if (completed) return 'done' as const;
      return 'pending' as const;
    },
    [dimensionProgress, executingDimensions, reports, streamingContent],
  );

  const selectLayer = useCallback(
    (layer: 1 | 2 | 3) => {
      setActiveLayer(layer);
      const firstDim = DIMENSIONS_BY_LAYER[layer][0];
      if (firstDim) {
        setSelectedNavigationKey(NAV_KEYS.dim(`${layer}_${firstDim}`));
      }
    },
    [setSelectedNavigationKey],
  );

  const progressPercent = totalDimensions > 0 ? Math.round((completedCount / totalDimensions) * 100) : 0;
  const activeAnalysisFocus = useActiveAnalysisFocus();
  const showAnalysisProgress = Boolean(
    activeAnalysisFocus &&
    (status === 'planning' || status === 'revising' || status === 'collecting' || executingDimensions.length > 0),
  );

  const beginSidebarResize = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const handle = event.currentTarget;
      handle.setPointerCapture(event.pointerId);
      sidebarResizeRef.current = { start: event.clientX, value: sidebarWidth };
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'col-resize';
      const move = (moveEvent: PointerEvent) => {
        const active = sidebarResizeRef.current;
        if (!active) return;
        setSidebarWidth(Math.max(168, Math.min(320, active.value + (moveEvent.clientX - active.start))));
      };
      const up = () => {
        sidebarResizeRef.current = null;
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', up);
        handle.removeEventListener('pointercancel', up);
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
      handle.addEventListener('pointercancel', up);
    },
    [sidebarWidth],
  );

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#f8fbf9]">
      <div className="shrink-0 border-b border-[#e5efe9] bg-gradient-to-r from-white via-white to-[#f4faf7] px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center rounded-xl border border-[#dcebe4] bg-[#f3f8f5] p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]">
            {layerTabs.map((tab) => {
              const layerReports = reports[`layer${tab.layer}` as 'layer1' | 'layer2' | 'layer3'] ?? {};
              const done = Object.keys(layerReports).length;
              const total = DIMENSIONS_BY_LAYER[tab.layer].length;
              const layerActive = !isOverview && activeLayer === tab.layer;
              return (
                <button
                  key={tab.layer}
                  type="button"
                  onClick={() => selectLayer(tab.layer)}
                  className={`rounded-lg px-3 py-1.5 text-[11px] font-medium transition-all ${
                    layerActive
                      ? 'bg-white text-[#1f7a59] shadow-sm ring-1 ring-[#dcebe4]'
                      : 'text-[#5d7f72] hover:bg-white/70 hover:text-[#2d8c6d]'
                  }`}
                >
                  <span>{tab.label}</span>
                  <span
                    className={`ml-1.5 tabular-nums text-[10px] ${layerActive ? 'text-[#5bb896]' : 'text-[#9ab2a8]'}`}
                  >
                    {done}/{total}
                  </span>
                </button>
              );
            })}
            <span className="mx-0.5 h-5 w-px bg-[#dcebe4]" />
            <button
              type="button"
              onClick={() => setSelectedNavigationKey(NAV_KEYS.OVERVIEW)}
              className={`rounded-lg px-3 py-1.5 text-[11px] font-medium transition-all ${
                isOverview
                  ? 'bg-white text-[#1f7a59] shadow-sm ring-1 ring-[#dcebe4]'
                  : 'text-[#5d7f72] hover:bg-white/70 hover:text-[#2d8c6d]'
              }`}
            >
              总览
            </button>
          </div>

          <div className="min-w-[140px] flex-1 max-w-[220px]">
            <div className="flex items-center justify-between text-[10px] text-[#8aa59a]">
              <span>整体进度</span>
              <span className="tabular-nums font-medium text-[#3a8f6f]">
                {completedCount}/{totalDimensions}
              </span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#e7f2ed]">
              <div
                className="h-full rounded-full bg-gradient-to-r from-[#6fd0a8] to-[#3fb288] transition-all duration-500"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
          </div>

          {showAnalysisProgress && activeAnalysisFocus && (
            <AnalysisProgressBanner
              focus={activeAnalysisFocus}
              completedCount={completedCount}
              totalCount={totalDimensions}
              compact
            />
          )}

          {onExport && (
            <button
              type="button"
              onClick={onExport}
              className="rounded-lg border border-[#dcebe4] bg-white px-3 py-1.5 text-[11px] font-medium text-[#3a8f6f] hover:bg-[#f4faf7]"
            >
              导出成果
            </button>
          )}

          {isPaused && (
            <div className="flex w-full flex-wrap items-center gap-3 rounded-xl border border-[#f0d7a5] bg-[#fff8e8] px-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="text-[12px] font-semibold text-[#8a6420]">
                  L{pendingReviewLayer || activeLayer} 已完成，正在等待审核
                </div>
                <div className="mt-0.5 text-[11px] text-[#a07a3a]">
                  {reviewActionLabel === '重试并继续'
                    ? '当前维度需要重新请求 provider；重试成功后会继续后续规划链。'
                    : '步骤模式开启时，需要点击「批准继续」才会生成下一层报告（L2/L3）。'}
                </div>
              </div>
              <button
                type="button"
                onClick={onApprove}
                className="rounded-lg bg-[#3fb288] px-4 py-2 text-[12px] font-semibold text-white shadow-sm shadow-emerald-100 hover:bg-[#359f7b]"
              >
                {reviewActionLabel} → 继续
              </button>
            </div>
          )}
        </div>
      </div>

      <div
        className="grid min-h-0 flex-1"
        style={{
          gridTemplateColumns: isOverview ? 'minmax(0,1fr)' : `minmax(168px,${sidebarWidth}px) 6px minmax(0,1fr)`,
        }}
      >
        {!isOverview && (
          <>
            <aside className="min-h-0 overflow-y-auto border-r border-[#e5efe9] bg-white/90 py-2 backdrop-blur-sm">
              <div className="px-3 pb-2 text-[11px] font-semibold tracking-wide text-[#9ab2a8]">
                L{activeLayer} · {layerTabs.find((tab) => tab.layer === activeLayer)?.short}专题
              </div>
              {DIMENSIONS_BY_LAYER[activeLayer].map((dimension) => {
                const navKey = NAV_KEYS.dim(`${activeLayer}_${dimension}`);
                const selected = selectedNavigationKey === navKey;
                const tone = getDimensionTone(activeLayer, dimension);
                return (
                  <button
                    key={dimension}
                    type="button"
                    onClick={() => setSelectedNavigationKey(navKey)}
                    className={`relative mx-2 mb-1 flex w-[calc(100%-16px)] items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-[13px] transition-all ${
                      selected
                        ? 'border border-[#c9e8db] bg-[#eef8f3] font-semibold text-[#1f7a59] shadow-sm'
                        : 'border border-transparent text-[#5d7f72] hover:border-[#e5efe9] hover:bg-[#fafcfb]'
                    }`}
                  >
                    {selected && <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-[#3fb288]" />}
                    <span
                      className={`h-2.5 w-2.5 shrink-0 rounded-full ${
                        tone === 'done'
                          ? 'bg-[#3fb288]'
                          : tone === 'running'
                            ? 'bg-[#e6a23c] animate-pulse'
                            : 'bg-[#d5e5dd]'
                      }`}
                    />
                    <span className="min-w-0 flex-1 truncate leading-5">{getDimensionName(dimension)}</span>
                  </button>
                );
              })}
            </aside>
            <div
              onPointerDown={beginSidebarResize}
              className="group relative touch-none cursor-col-resize"
              title="拖动调整专题列表宽度"
            >
              <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-[#dcebe4] transition-all group-hover:w-1 group-hover:bg-[#3fb288]" />
            </div>
          </>
        )}

        <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-tl-xl bg-[#fbfcfb] shadow-[inset_1px_0_0_rgba(229,239,233,0.6)]">
          <ReportViewer
            variant="embedded"
            hideOverviewDimensionGrid
            chatPanel={chatPanel}
            sessionConnected={sessionConnected}
            onGoToTaskSettings={onGoToTask}
            onStartPlanning={() => undefined}
            onViewProcess={() => undefined}
          />
        </div>
      </div>
    </div>
  );
}

const SSR_WORKBENCH_DEFAULT: { view: WorkbenchView; panel: OverviewPanel } = {
  view: 'overview',
  panel: 'task',
};

function readInitialWorkbenchState(): {
  view: WorkbenchView;
  panel: OverviewPanel;
} {
  // Must match SSR output — URL is applied in a mount effect to avoid hydration mismatch.
  return SSR_WORKBENCH_DEFAULT;
}

function UnifiedPlanningWorkbench() {
  const {
    startPlanning,
    sendChatMessage,
    approve,
    resetConversation,
    loadVillagesHistory,
    loadHistoricalSession,
    deleteSession,
    clearAllHistory,
  } = usePlanningActions();
  const sessionId = usePlanningStore((state) => state.sessionId);
  const sessionVillageName = usePlanningStore((state) => state.villageName);
  const reports = usePlanningStore((state) => state.reports);
  const status = usePlanningStore((state) => state.status);
  const villages = usePlanningStore((state) => state.villages);
  const historyLoading = usePlanningStore((state) => state.historyLoading);
  const messages = usePlanningStore((state) => state.messages);
  const completedLayers = usePlanningStore((state) => state.completedLayers);
  const isPaused = usePlanningStore((state) => state.isPaused);
  const stepMode = usePlanningStore((state) => state.step_mode);
  const setStepMode = usePlanningStore((state) => state.setStepMode);
  const planningTextRegenRequest = usePlanningStore((state) => state.planningTextRegenRequest);
  const historyError = usePlanningStore((state) => state.historyError);
  const selectedNavigationKey = usePlanningStore((state) => state.selectedNavigationKey);
  const setSelectedNavigationKey = usePlanningStore((state) => state.setSelectedNavigationKey);
  // Zustand selectors must return a stable snapshot. Flattening inside the
  // selector creates a new array on every render and causes React's
  // useSyncExternalStore to recurse until "Maximum update depth exceeded".
  const liveGisLayerGroups = usePlanningStore((state) => state.gisLayers);
  const liveGisLayers = useMemo(() => Object.values(liveGisLayerGroups).flat(), [liveGisLayerGroups]);
  const addMessage = usePlanningStore((state) => state.addMessage);
  const syncBackendState = usePlanningStore((state) => state.syncBackendState);
  const [payload, setPayload] = useState<CompleteResultPayload | null>(null);
  const [positioningTrace, setPositioningTrace] = useState<PositioningTraceResponse | null>(null);
  const [artifactKeys, setArtifactKeys] = useState<Set<string>>(() => new Set());
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<Set<LayerFilter>>(() => new Set(['current']));
  const [selectedLayerKeys, setSelectedLayerKeys] = useState<Set<string>>(() => new Set());
  const [activeRelation, setActiveRelation] = useState('相邻');
  const [baseMap, setBaseMap] = useState<WorkbenchBaseMap>('general');
  const [currentGisSource, setCurrentGisSource] = useState<CurrentSourceLayersResult | null>(null);
  const [workbenchView, setWorkbenchView] = useState<WorkbenchView>(() => readInitialWorkbenchState().view);
  const [overviewLevel, setOverviewLevel] = useState<OverviewLevel>('L3 详细规划');
  const [overviewPanel, setOverviewPanel] = useState<OverviewPanel>(() => readInitialWorkbenchState().panel);
  const [dataPanel, setDataPanel] = useState<DataPanel>('kg');
  const [showPlanningText, setShowPlanningText] = useState(false);
  const [showExportDialog, setShowExportDialog] = useState(false);
  const [rightPanelWidth, setRightPanelWidth] = useState(460);
  const [mapHeight, setMapHeight] = useState(720);
  const [showMapDetails, setShowMapDetails] = useState(false);
  const [planningError, setPlanningError] = useState('');
  const [evidenceFocus, setEvidenceFocus] = useState<MapFeatureFocus | null>(null);
  const [evidenceFocuses, setEvidenceFocuses] = useState<MapFeatureFocus[]>([]);
  const [spatialSidebarTab, setSpatialSidebarTab] = useState<SpatialSidebarTab>('assistant');
  const [spatialAssistantMode, setSpatialAssistantMode] = useState<SpatialAssistantMode>('locator');
  const [artifactDetailsOpen, setArtifactDetailsOpen] = useState(false);
  const [focusedArtifactKey, setFocusedArtifactKey] = useState<string | null>(null);
  const [projectName, setProjectName] = useState('');
  const [villageData, setVillageData] = useState('');
  const [villageDataFiles, setVillageDataFiles] = useState<File[]>([]);
  const [taskDescription, setTaskDescription] = useState('');
  const [taskFiles, setTaskFiles] = useState<File[]>([]);
  const [constraintsText, setConstraintsText] = useState('');
  const [constraintFiles, setConstraintFiles] = useState<File[]>([]);
  const [province, setProvince] = useState('');
  const [city, setCity] = useState('');
  const [county, setCounty] = useState('');
  const [township, setTownship] = useState('');
  const [villageName, setVillageName] = useState('');
  const [planningPeriod, setPlanningPeriod] = useState('');
  const [stepModeLoading, setStepModeLoading] = useState(false);
  const [isStartingPlanning, setIsStartingPlanning] = useState(false);
  const planningBootstrap = usePlanningBootstrapStage(isStartingPlanning);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);
  const resizeState = useRef<{
    kind: 'side' | 'map';
    start: number;
    value: number;
  } | null>(null);
  const hydratedReportKey = useRef('');
  const [navHydrated, setNavHydrated] = useState(false);

  const activeVillageName = useMemo(() => {
    if (!sessionId) return villageName;
    const historyVillage = villages.find((village) =>
      village.sessions.some((session) => session.session_id === sessionId),
    );
    return sessionVillageName || historyVillage?.display_name || historyVillage?.name || villageName;
  }, [sessionId, sessionVillageName, villageName, villages]);

  const activeNavId = useMemo<SidebarNavId>(() => {
    if (workbenchView === 'drawings') return 'drawings';
    if (workbenchView === 'data') {
      if (dataPanel === 'metrics') return 'data-metrics';
      if (dataPanel === 'compliance') return 'data-compliance';
      if (dataPanel === 'suitability') return 'data-suitability';
      return 'data-kg';
    }
    if (overviewPanel === 'analysis') return 'overview-analysis';
    if (overviewPanel === 'document') return 'overview-document';
    if (overviewPanel === 'evaluation') return 'overview-evaluation';
    return 'overview-task';
  }, [dataPanel, overviewPanel, workbenchView]);

  const handleSidebarNavigate = useCallback((id: SidebarNavId) => {
    switch (id) {
      case 'overview-task':
        setWorkbenchView('overview');
        setOverviewPanel('task');
        break;
      case 'overview-analysis':
        setWorkbenchView('overview');
        setOverviewPanel('analysis');
        break;
      case 'overview-document':
        setWorkbenchView('overview');
        setOverviewPanel('document');
        break;
      case 'overview-evaluation':
        setWorkbenchView('overview');
        setOverviewPanel('evaluation');
        break;
      case 'drawings':
        setWorkbenchView('drawings');
        break;
      case 'data-kg':
        setWorkbenchView('data');
        setDataPanel('kg');
        break;
      case 'data-metrics':
        setWorkbenchView('data');
        setDataPanel('metrics');
        break;
      case 'data-compliance':
        setWorkbenchView('data');
        setDataPanel('compliance');
        break;
      case 'data-suitability':
        setWorkbenchView('data');
        setDataPanel('suitability');
        break;
      default:
        break;
    }
  }, []);

  const recentSessions = useMemo(
    () =>
      villages
        .flatMap((village) =>
          village.sessions.map((session) => ({
            ...session,
            villageName: village.display_name || village.name,
            projectName: village.name,
          })),
        )
        .sort((left, right) => new Date(right.timestamp).getTime() - new Date(left.timestamp).getTime())
        .slice(0, 8),
    [villages],
  );

  const totalHistoryCount = useMemo(
    () => villages.reduce((sum, village) => sum + village.sessions.length, 0),
    [villages],
  );

  useEffect(() => {
    void loadVillagesHistory();
  }, [loadVillagesHistory]);

  // Apply view/panel from URL after mount (SSR always renders task tab).
  useEffect(() => {
    const { view, panel } = resolveDefaultWorkbenchNav(getSessionIdFromUrl());
    setWorkbenchView(view);
    setOverviewPanel(panel);
    setNavHydrated(true);
  }, []);

  useEffect(() => {
    const urlNav = getWorkbenchNavFromUrl();
    if (urlNav.nav) {
      setSelectedNavigationKey(urlNav.nav as import('@/features/planning/constants').NavigationKey);
    }
  }, [setSelectedNavigationKey]);

  useEffect(() => {
    if (!navHydrated) return;
    setWorkbenchNavInUrl({
      view: workbenchView,
      panel: workbenchView === 'overview' ? overviewPanel : undefined,
      nav: selectedNavigationKey,
    });
  }, [navHydrated, workbenchView, overviewPanel, selectedNavigationKey]);

  const prevSessionIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (!sessionId) {
      prevSessionIdRef.current = null;
      return;
    }
    if (prevSessionIdRef.current === sessionId) return;
    prevSessionIdRef.current = sessionId;
    const urlNav = getWorkbenchNavFromUrl();
    if (!urlNav.view && !urlNav.panel) {
      setWorkbenchView('overview');
      setOverviewPanel('analysis');
    }
  }, [sessionId]);

  useEffect(() => {
    if (!planningTextRegenRequest) return;
    setWorkbenchView('overview');
    setOverviewPanel('document');
  }, [planningTextRegenRequest]);

  const shouldLoadGisResult = workbenchView === 'drawings' || workbenchView === 'data';
  const hasSessionGisLayers = liveGisLayers.length > 0;
  const spatialArtifactKeys = useMemo(
    () => new Set([...artifactKeys].filter((key) => SPATIAL_ARTIFACT_KEY_SET.has(key))),
    [artifactKeys],
  );
  const spatialWorkflowSteps = useMemo(
    () => buildSpatialWorkflowSteps(positioningTrace, artifactKeys, reports.layer3),
    [artifactKeys, positioningTrace, reports.layer3],
  );
  // Source layers belong to the active session's admitted DATA catalog.
  // There is no bundled-village fallback and no cross-session reuse.
  const referenceVillageName = activeVillageName;
  const shouldLoadCurrentSource = shouldLoadGisResult && Boolean(sessionId);
  const visibleCurrentGisSource = shouldLoadCurrentSource ? currentGisSource : null;
  const showingReferenceGis = Boolean(
    shouldLoadCurrentSource && sessionId && !hasSessionGisLayers && currentGisSource?.layers?.length,
  );

  useEffect(() => {
    if (!sessionId || !shouldLoadGisResult) {
      setPositioningTrace(null);
      setArtifactKeys(new Set());
      return undefined;
    }
    let cancelled = false;
    const loadTrace = async () => {
      try {
        const [trace, artifacts] = await Promise.all([
          planningApi.getPositioningTrace(sessionId),
          planningApi.listArtifacts(sessionId),
        ]);
        if (!cancelled) {
          setPositioningTrace(trace);
          setArtifactKeys(new Set(artifacts.artifacts.map((artifact) => artifact.artifact_key)));
        }
      } catch {
        if (!cancelled) {
          setPositioningTrace(null);
          setArtifactKeys(new Set());
        }
      }
    };
    void loadTrace();
    const timer = window.setInterval(() => void loadTrace(), 8000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [sessionId, shouldLoadGisResult]);

  useEffect(() => {
    if (!shouldLoadCurrentSource) return;
    let cancelled = false;
    void fetchCurrentSourceLayers(referenceVillageName || '', sessionId || '')
      .then((result) => {
        if (!cancelled) setCurrentGisSource(result);
      })
      .catch((requestError) => {
        logger.context.warn('Current GIS source fetch failed', {
          error: String(requestError),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [referenceVillageName, sessionId, shouldLoadCurrentSource]);

  const loadResult = useCallback(
    async (force = false) => {
      void force;
      setLoading(true);
      setError('');
      try {
        const sourceLayers = await fetchCurrentSourceLayers(referenceVillageName || '', sessionId || '');
        setCurrentGisSource(sourceLayers);
        setPayload(null);
      } catch (requestError) {
        const message = requestError instanceof Error ? requestError.message : '现状 GIS 数据源加载失败';
        setError(`现状 GIS 数据源加载失败：${message}`);
      } finally {
        setLoading(false);
      }
    },
    [referenceVillageName, sessionId],
  );

  useEffect(() => {
    if (!shouldLoadCurrentSource) {
      setCurrentGisSource(null);
      setLoading(false);
      return;
    }
    void loadResult();
  }, [shouldLoadCurrentSource, loadResult]);

  useEffect(() => {
    hydratedReportKey.current = '';
    setPayload(null);
    if (!shouldLoadCurrentSource) {
      setCurrentGisSource(null);
      setLoading(false);
      return;
    }
    void loadResult();
  }, [sessionId, shouldLoadCurrentSource, loadResult]);

  useEffect(() => {
    if (!sessionId || !['planning', 'revising', 'collecting', 'paused'].includes(status)) return;
    let disposed = false;
    const syncStatus = async () => {
      try {
        const backendStatus = await planningApi.getStatus(sessionId);
        if (!disposed) {
          syncBackendState(backendStatus);
          await syncIfEventSeqBehind(sessionId, backendStatus.last_event_seq);
        }
      } catch {
        // SSE reconnect remains the primary channel; polling is only a
        // terminal-state safety net and must not add duplicate chat errors.
      }
    };
    void syncStatus();
    const timer = window.setInterval(() => void syncStatus(), 4000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [sessionId, status, syncBackendState]);

  const staticLayers = useMemo(() => {
    if (payload?.layers?.length) {
      return normalizeGisLayers(payload.layers);
    }
    return shouldLoadCurrentSource ? (currentGisSource?.layers ?? []) : [];
  }, [currentGisSource?.layers, payload?.layers, shouldLoadCurrentSource]);
  const sessionLayers = useMemo(() => normalizeGisLayers(liveGisLayers), [liveGisLayers]);
  const layers = useMemo(() => mergeGisLayerSources(staticLayers, sessionLayers), [staticLayers, sessionLayers]);
  const roadProcess = payload?.roadProcess ?? {};
  const roadProjects = payload?.roadProjects ?? [];

  const fullRoadLayer = useMemo(() => layers.find((layer) => layerRole(layer) === 'stage5_full_network'), [layers]);

  const mapLayers = useMemo(
    () =>
      layers
        .filter((layer) => {
          if (layer.visible === false) return false;
          if (isLegacyCadArtifact(layer)) return false;
          if (isNoiseLayer(layer)) return false;
          if (isFacilityAnnotationLayer(layer) && !selectedLayerKeys.has('facilities')) return false;
          const path = layer.metadata?.path ?? '';
          if (
            layer.layerName === 'polygons' &&
            String(path).includes('/project/') &&
            !selectedLayerKeys.has('custom-zones')
          )
            return false;
          const base = layer.layerType === 'boundary' || layer.layerName === '现状用地（原版底图）';
          const chip = [...selectedLayerKeys].some((key) => matchesQuickLayer(layer, key));
          const hasQuickSelection = selectedLayerKeys.size > 0;
          const group =
            !hasQuickSelection && (filters.has('all') || [...filters].some((key) => matchesFilter(layer, key)));
          return layer !== fullRoadLayer || selectedLayerKeys.has('stage5-full') ? base || chip || group : false;
        })
        .map((layer) => {
          if (layer === fullRoadLayer) return { ...layer, visible: true };
          if (layer.layerName === '国土空间用途规划') {
            return {
              ...layer,
              style: {
                ...layer.style,
                fillOpacity: 0.62,
                lineOpacity: 0.34,
                lineWidth: 0.45,
              },
            };
          }
          if (layer.layerName === '现状用地（原版底图）') {
            return {
              ...layer,
              style: {
                ...layer.style,
                fillOpacity: 0.08,
                lineOpacity: 0.12,
                lineWidth: 0.2,
              },
            };
          }
          if (layerRole(layer) === 'current_landuse' || layer.layerName === '现状地块') {
            return {
              ...layer,
              style: {
                ...layer.style,
                fillOpacity: 0.78,
                lineOpacity: 0.95,
                lineWidth: 0.85,
              },
            };
          }
          if (layer.layerName === 'landuse') {
            return {
              ...layer,
              style: {
                ...layer.style,
                fillOpacity: 0.68,
                lineOpacity: 0.85,
                lineWidth: 1.1,
              },
            };
          }
          return layer;
        }),
    [filters, fullRoadLayer, layers, selectedLayerKeys],
  );

  const displayMapLayers = useMemo(() => {
    if (baseMap !== 'amap') return mapLayers;
    return mapLayers.filter((layer) => layer.layerName !== '现状用地（原版底图）');
  }, [baseMap, mapLayers]);

  const getLayer = useCallback((predicate: (layer: GISLayerConfig) => boolean) => layers.find(predicate), [layers]);

  const currentParcels = featureCount(
    getLayer(
      (layer) =>
        layerRole(layer) === 'current_landuse' ||
        layer.layerName.includes('现状用地') ||
        (layer.layerName === 'landuse' && !!layer.metadata?.path?.includes('current')),
    ),
  );
  const deliveryPlannedParcels = layers.filter(isV1PlannedLanduse).reduce((sum, layer) => sum + featureCount(layer), 0);
  const plannedParcels =
    deliveryPlannedParcels ||
    featureCount(
      getLayer(
        (layer) =>
          layer.layerName === '国土空间用途规划' ||
          (layer.layerName === 'landuse' && !!layer.metadata?.path?.includes('planned')),
      ),
    );
  const plannedOverlayFeatures = layers
    .filter((layer) => v1LayerGroup(layer) === 'overlay' && !isFacilityAnnotationLayer(layer))
    .reduce((sum, layer) => sum + featureCount(layer), 0);
  const currentRoads = featureCount(
    getLayer(
      (layer) =>
        layerRole(layer) === 'current_road' ||
        layer.layerName === '现状道路' ||
        (layer.layerName === 'road' && !!layer.metadata?.path?.includes('current')),
    ),
  );
  const referenceRoads = featureCount(
    getLayer(
      (layer) =>
        layerRole(layer) === 'historical_planned_road_reference' ||
        (layer.layerName === 'road' && !!layer.metadata?.path?.includes('planned')),
    ),
  );
  const stage5Roads = roadProcess.recommended_segment_count_all ?? roadProcess.recommended_segment_count ?? 0;
  const finalRoads = roadProjects.filter((project) => project.status === 'recommended').length;
  const hazardCount = featureCount(getLayer((layer) => layer.layerType === 'hazard_point'));
  const farmlandCount = featureCount(
    getLayer((layer) => layer.layerName.includes('永久基本农田') || layer.layerName === 'farmland_protection'),
  );
  const ecologyCount = featureCount(
    getLayer((layer) => layer.layerName.includes('生态保护') || layer.layerName === 'ecological_protection'),
  );
  const heritageCount = featureCount(
    getLayer((layer) => layer.layerName.includes('历史文化') || layer.layerName === 'historical_protection'),
  );
  const constructionCount = featureCount(
    getLayer((layer) => layer.layerName.includes('村庄建设边界') || layer.layerName === 'construction_zone'),
  );
  const customZoneCount = featureCount(getLayer((layer) => String(layer.layerType) === 'custom_functional_zone'));
  const facilities = layers
    .filter(
      (layer) =>
        String(layer.layerType) === 'facility' ||
        (layer.layerType === 'facility_point' && layerRole(layer) !== 'source_annotation'),
    )
    .reduce((sum, layer) => sum + featureCount(layer), 0);
  const CONTROL_LAYER_NAMES = new Set([
    'construction_zone',
    'farmland_protection',
    'ecological_protection',
    'historical_protection',
  ]);
  const constraints = layers
    .filter(
      (layer) =>
        CONTROL_LAYER_NAMES.has(layer.layerName) ||
        layerRole(layer) === 'control_reference' ||
        layer.layerName.includes('永久基本农田') ||
        layer.layerName.includes('生态保护') ||
        layer.layerName.includes('历史文化') ||
        layer.layerName.includes('村庄建设边界'),
    )
    .reduce((sum, layer) => sum + featureCount(layer), 0);
  const totalFeatures = layers.reduce((sum, layer) => sum + featureCount(layer), 0);
  const typeCount = new Set(layers.map((layer) => layer.layerType)).size;

  const mapLayersLoading = loading && !visibleCurrentGisSource?.layers?.length;

  const mapCenter = useMemo((): [number, number] => {
    if (visibleCurrentGisSource?.center) return visibleCurrentGisSource.center;
    const boundary = layers.find((layer) => layer.layerType === 'boundary' || layer.layerName === 'boundary');
    const geometry = boundary?.geojson?.features?.[0]?.geometry;
    if (geometry && (geometry.type === 'Polygon' || geometry.type === 'MultiPolygon')) {
      const ring =
        geometry.type === 'Polygon'
          ? (geometry.coordinates as [number, number][][])[0]
          : (geometry.coordinates as [number, number][][][])[0]?.[0];
      if (ring?.length) {
        const lng = ring.reduce((sum, coord) => sum + coord[0], 0) / ring.length;
        const lat = ring.reduce((sum, coord) => sum + coord[1], 0) / ring.length;
        return [lng, lat];
      }
    }
    return [116.0735, 24.8317];
  }, [visibleCurrentGisSource?.center, layers]);

  const quickGroups = [
    {
      label: '现状',
      options: [
        ['current-landuse', `地块 ${currentParcels}`],
        ['current-roads', `道路 ${currentRoads}`],
        ['facilities', `设施/标注 ${facilities}`],
        ['hazards', `灾害点 ${hazardCount}`],
      ],
    },
    {
      label: '规划',
      options: [
        ['planned-landuse', `规划地块 ${plannedParcels}`],
        ['custom-zones', `功能分区 ${customZoneCount}`],
        ['structure', '一核一带三区'],
        ['reference-roads', `既有规划路 ${referenceRoads}`],
        ['stage5-final', `本轮结论 ${finalRoads}`],
        ['stage5-full', `Stage5 全网 ${stage5Roads}`],
      ],
    },
    {
      label: '约束',
      options: [
        ['farmland', `农田保护 ${farmlandCount}`],
        ['ecology', `生态红线 ${ecologyCount}`],
        ['heritage', `历史保护 ${heritageCount}`],
        ['construction', `建设边界 ${constructionCount}`],
      ],
    },
  ] as const;

  const selectFilter = useCallback((key: LayerFilter) => {
    setFilters(new Set([key]));
    setSelectedLayerKeys(new Set());
  }, []);

  const activeFilterLabel =
    selectedLayerKeys.size > 0 ? '自选图层' : FILTERS.find((item) => filters.has(item.key))?.label || '全部成果';

  const toggleLayer = useCallback(
    (key: string) =>
      setSelectedLayerKeys((previous) => {
        const next = new Set(previous);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
      }),
    [],
  );

  const handleStartPlanning = useCallback(async () => {
    setPlanningError('');
    hydratedReportKey.current = '';
    setFilters(new Set(['current']));
    setSelectedLayerKeys(new Set());
    setPayload(null);
    if (!projectName.trim() || !taskDescription.trim() || !villageData.trim()) {
      setPlanningError('请填写项目名称、村庄基础数据和规划任务，或点击“一键填写示例”。');
      return;
    }
    if (villageData.trim().length < 10) {
      setPlanningError('村庄基础数据过短（至少 10 个字符），请补充村庄概况后再开始分析。');
      return;
    }
    setIsStartingPlanning(true);
    setWorkbenchView('overview');
    setOverviewPanel('analysis');
    try {
      await startPlanning({
        projectName: projectName.trim(),
        villageName: villageName.trim(),
        villageData: villageData.trim(),
        province: province.trim(),
        city: city.trim(),
        county: county.trim(),
        township: township.trim(),
        planningPeriod: planningPeriod.trim(),
        taskDescription,
        constraints: constraintsText,
        stepMode,
        villageDataFiles: villageDataFiles.length ? villageDataFiles : undefined,
        taskFiles: taskFiles.length ? taskFiles : undefined,
        constraintFiles: constraintFiles.length ? constraintFiles : undefined,
      } satisfies PlanningParams);
    } catch (planningFailure) {
      setOverviewPanel('task');
      setPlanningError(planningFailure instanceof Error ? planningFailure.message : '规划任务启动失败');
    } finally {
      setIsStartingPlanning(false);
    }
  }, [
    city,
    constraintFiles,
    constraintsText,
    county,
    planningPeriod,
    projectName,
    province,
    startPlanning,
    stepMode,
    taskDescription,
    taskFiles,
    township,
    villageData,
    villageDataFiles,
    villageName,
  ]);

  const handleTaskFilesChange = useCallback(
    (field: 'villageDataFiles' | 'taskFiles' | 'constraintFiles', files: File[]) => {
      if (field === 'villageDataFiles') setVillageDataFiles(files);
      if (field === 'taskFiles') setTaskFiles(files);
      if (field === 'constraintFiles') setConstraintFiles(files);
    },
    [],
  );

  const handleStepModeChange = useCallback(
    async (enabled: boolean) => {
      setStepMode(enabled);

      const { sessionId: activeSessionId, status: activeStatus } = usePlanningStore.getState();
      const shouldSyncBackend = Boolean(
        activeSessionId && ['planning', 'revising', 'paused', 'collecting'].includes(activeStatus),
      );
      if (!shouldSyncBackend) return;

      setStepModeLoading(true);
      try {
        await planningApi.updateStepMode(activeSessionId!, {
          step_mode: enabled,
        });
      } catch (error) {
        // Keep the user's local choice; only surface the sync error.
        setPlanningError(error instanceof Error ? error.message : '步骤模式同步失败，但本地设置已保留');
      } finally {
        setStepModeLoading(false);
      }
    },
    [setStepMode],
  );

  const fillExample = useCallback(async () => {
    try {
      const demo = await loadJintianDemoInput(EXAMPLE_TASKS[overviewLevel]);
      setProjectName(demo.projectName);
      setVillageData(demo.villageData);
      setTaskDescription(demo.taskDescription);
      setConstraintsText(demo.constraints);
      setProvince(demo.province);
      setCity(demo.city);
      setCounty(demo.county);
      setTownship(demo.township);
      setVillageName(demo.villageName);
      setPlanningPeriod(demo.planningPeriod);
      setPlanningError('');
    } catch (error) {
      setPlanningError(error instanceof Error ? error.message : '完整金田村现状报告加载失败，请重试。');
    }
  }, [overviewLevel]);

  const startBlankProject = useCallback(() => {
    resetConversation();
    hydratedReportKey.current = '';
    setPayload(null);
    setFilters(new Set(['all']));
    setSelectedLayerKeys(new Set());
    setProjectName('');
    setVillageData('');
    setTaskDescription('');
    setConstraintsText('');
    setPlanningError('');
    setVillageDataFiles([]);
    setTaskFiles([]);
    setConstraintFiles([]);
    setProvince('');
    setCity('');
    setCounty('');
    setTownship('');
    setVillageName('');
    setPlanningPeriod('');
    setOverviewLevel('L3 详细规划');
    setWorkbenchView('overview');
    setOverviewPanel('task');
  }, [resetConversation]);

  const openHistoricalSession = useCallback(
    async (projectName: string, historicalSessionId: string) => {
      hydratedReportKey.current = '';
      setPayload(null);
      setFilters(new Set(['all']));
      setSelectedLayerKeys(new Set());
      setVillageData('');
      setTaskDescription('');
      setConstraintsText('');
      setPlanningError('');
      await loadHistoricalSession(projectName, historicalSessionId);
      const restored = usePlanningStore.getState();
      setProjectName(restored.projectName || projectName || '');
      setVillageName(restored.villageName || '');
      setProvince(restored.province || '');
      setCity(restored.city || '');
      setCounty(restored.county || '');
      setTownship(restored.township || '');
      setPlanningPeriod(restored.planningPeriod || '');
      setWorkbenchView('overview');
      setOverviewPanel('analysis');
    },
    [loadHistoricalSession],
  );

  const handleDeleteHistoricalSession = useCallback(
    async (event: React.MouseEvent<HTMLButtonElement>, historicalSessionId: string, villageLabel: string) => {
      event.stopPropagation();
      if (!window.confirm(`确定删除「${villageLabel}」的历史会话？此操作不可恢复。`)) return;

      setDeletingSessionId(historicalSessionId);
      try {
        const deleted = await deleteSession(historicalSessionId, villageLabel);
        if (deleted && historicalSessionId === sessionId) {
          startBlankProject();
        }
      } finally {
        setDeletingSessionId(null);
      }
    },
    [deleteSession, sessionId, startBlankProject],
  );

  const handleClearAllHistory = useCallback(() => {
    if (totalHistoryCount === 0) return;
    if (!window.confirm(`确定删除全部 ${totalHistoryCount} 条历史会话？此操作不可恢复。`)) return;

    const store = usePlanningStore.getState();
    const sessionIds = store.villages.flatMap((village) => village.sessions.map((session) => session.session_id));
    const clearedActiveSession = Boolean(store.sessionId && sessionIds.includes(store.sessionId));

    store.markSessionsDeleted(sessionIds);
    store.clearVillagesHistory();
    if (clearedActiveSession) {
      startBlankProject();
    }

    void clearAllHistory(sessionIds);
  }, [clearAllHistory, startBlankProject, totalHistoryCount]);

  const handleTaskFieldChange = useCallback((field: string, value: string) => {
    const setters: Record<string, (next: string) => void> = {
      projectName: setProjectName,
      villageData: setVillageData,
      taskDescription: setTaskDescription,
      constraintsText: setConstraintsText,
      province: setProvince,
      city: setCity,
      county: setCounty,
      township: setTownship,
      villageName: setVillageName,
      planningPeriod: setPlanningPeriod,
    };
    setters[field]?.(value);
  }, []);

  const handleChat = useCallback(
    async (content: string) => {
      if (!sessionId) return;
      addMessage({
        ...createBaseMessage('user'),
        type: 'text',
        content,
      } as Message);
      try {
        const result = await sendChatMessage(content);
        const reply = result.reply?.trim();
        if (result.draft_feedback || (result.dimensions && result.dimensions.length > 0)) {
          usePlanningStore.getState().setRevisionDraft({
            feedback: result.draft_feedback || content,
            dimensions: result.dimensions || [],
          });
          setWorkbenchView('overview');
          setOverviewPanel('analysis');
          addMessage({
            ...createBaseMessage('assistant'),
            type: 'text',
            content: reply || '我已将建议整理为修订草稿，并填入左侧审查框。请检查后点击「提交修订」。',
          } as Message);
          return;
        }
        addMessage({
          ...createBaseMessage('assistant'),
          type: 'text',
          content: reply || '已收到你的消息。我会结合当前规划进度处理；如需重生成，请说明具体分析维度。',
        } as Message);
      } catch (chatFailure) {
        addMessage(createErrorMessage(chatFailure instanceof Error ? chatFailure.message : '消息发送失败'));
      }
    },
    [addMessage, sendChatMessage, sessionId, setWorkbenchView, setOverviewPanel],
  );

  const focusEvidenceFeatures = useCallback((features: EvidenceFeatureRef[]) => {
    const mapped: MapFeatureFocus[] = [];
    const seen = new Set<string>();
    const addFocus = (focus: MapFeatureFocus) => {
      const key = [focus.resourceRef, focus.sourceDatasetRef, focus.sourceFeatureId].filter(Boolean).join('|');
      if (!key || seen.has(key)) return;
      seen.add(key);
      mapped.push(focus);
    };
    features.forEach((feature) => {
      const identity = feature.identity;
      if (!identity) return;
      addFocus({
        resourceRef: feature.resource_ref,
        sourceDatasetRef: identity.source_dataset_ref,
        sourceFeatureId: identity.source_feature_id,
      });
      (feature.entity_refs || []).slice(0, 6).forEach((entityRef) => {
        addFocus({ resourceRef: entityRef });
      });
    });
    setEvidenceFocuses(mapped);
    setEvidenceFocus(mapped[0] ?? null);
  }, []);

  const beginResize = useCallback(
    (kind: 'side' | 'map', event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const handle = event.currentTarget;
      handle.setPointerCapture(event.pointerId);
      resizeState.current = {
        kind,
        start: kind === 'map' ? event.clientY : event.clientX,
        value: kind === 'map' ? mapHeight : rightPanelWidth,
      };
      document.body.style.userSelect = 'none';
      document.body.style.cursor = kind === 'map' ? 'row-resize' : 'col-resize';
      const move = (moveEvent: PointerEvent) => {
        const active = resizeState.current;
        if (!active) return;
        if (active.kind === 'side')
          setRightPanelWidth(Math.max(380, Math.min(680, active.value - (moveEvent.clientX - active.start))));
        else setMapHeight(Math.max(420, Math.min(950, active.value + (moveEvent.clientY - active.start))));
      };
      const up = () => {
        resizeState.current = null;
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', up);
        handle.removeEventListener('pointercancel', up);
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
      handle.addEventListener('pointercancel', up);
    },
    [mapHeight, rightPanelWidth],
  );

  return (
    <div className="flex h-dvh min-h-[720px] flex-col overflow-hidden bg-[#f2f7f4] text-[#294c42]">
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[230px_minmax(0,1fr)]">
        <aside className="hidden h-full min-h-0 flex-col border-r border-[#dcece5] bg-[#e8f5ef] lg:flex">
          <div className="flex h-[66px] items-center gap-3 border-b border-[#dcece5] px-5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#43b88c] text-lg font-bold text-white shadow-lg shadow-emerald-200">
              村
            </div>
            <div>
              <div className="text-[16px] font-bold text-[#244e42]">村庄规划</div>
              <div className="text-[10px] uppercase tracking-[0.14em] text-[#7da396]">Village Planning</div>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-3 py-4">
            <button
              onClick={startBlankProject}
              className="flex w-full items-center justify-center gap-2 rounded-full border border-[#bcdccd] bg-white/70 px-4 py-2 text-[13px] font-medium text-[#2d8c6d] hover:bg-white"
            >
              <WorkbenchIcon icon={faRotateRight} />
              开启新项目
            </button>
            <SidebarNav activeId={activeNavId} onNavigate={handleSidebarNavigate} />
          </div>

          <div className="border-t border-[#d4e9df] p-4">
            <div className="flex items-center justify-between">
              <div className="text-[11px] font-semibold text-[#456f62]">历史记录</div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleClearAllHistory}
                  disabled={totalHistoryCount === 0}
                  className="text-[10px] text-[#5f8f7d] transition-colors hover:text-[#2d8c6d] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  清空全部
                </button>
                <button
                  type="button"
                  onClick={() => void loadVillagesHistory()}
                  className="text-[10px] text-[#5f8f7d] hover:text-[#2d8c6d]"
                >
                  刷新
                </button>
              </div>
            </div>
            <div className="mt-2 max-h-40 space-y-1 overflow-y-auto">
              {historyError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-2 py-1.5 text-[10px] text-red-700">
                  历史记录加载失败：{historyError}
                </div>
              )}
              {historyLoading && <div className="text-[11px] text-[#8aa59a]">正在加载历史会话…</div>}
              {!historyLoading && recentSessions.length === 0 && (
                <div className="text-[11px] text-[#8aa59a]">暂无历史会话。开启新项目并完成一次规划后会出现在这里。</div>
              )}
              {recentSessions.map((session) => {
                const active = session.session_id === sessionId;
                const deleting = deletingSessionId === session.session_id;
                const label = new Date(session.timestamp).toLocaleString('zh-CN', {
                  month: '2-digit',
                  day: '2-digit',
                  hour: '2-digit',
                  minute: '2-digit',
                });
                return (
                  <div
                    key={session.session_id}
                    className={`group flex items-center gap-1 rounded-lg px-1 py-0.5 transition-colors ${
                      active ? 'bg-white shadow-sm' : 'hover:bg-white/70'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => void openHistoricalSession(session.projectName, session.session_id)}
                      className={`min-w-0 flex-1 rounded-md px-1.5 py-1.5 text-left text-[11px] transition-colors ${
                        active ? 'font-semibold text-[#1f8763]' : 'text-[#6f8f83]'
                      }`}
                    >
                      <div className="truncate">{session.villageName}</div>
                      <div className="text-[10px] text-[#8aa59a]">{label}</div>
                    </button>
                    <button
                      type="button"
                      title="删除历史会话"
                      aria-label={`删除 ${session.villageName} 的历史会话`}
                      disabled={deleting}
                      onClick={(event) =>
                        void handleDeleteHistoricalSession(event, session.session_id, session.villageName)
                      }
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[#9ab2a8] transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
                    >
                      <WorkbenchIcon icon={faTrash} style={{ width: 11, height: 11 }} />
                    </button>
                  </div>
                );
              })}
            </div>
            <div className="mt-4 flex items-center gap-2 text-[12px] text-[#456f62]">
              <span className="h-8 w-8 rounded-full bg-[#ffd8e6] text-center leading-8">规</span>
              规划工作台
            </div>
          </div>
        </aside>

        <main
          className={`min-h-0 min-w-0 ${workbenchView === 'overview' ? 'flex h-full min-h-0 flex-col overflow-hidden p-2' : 'flex h-full min-h-0 flex-col overflow-y-auto p-3 pb-6 lg:p-4 lg:pb-8'}`}
        >
          <div
            className={`mx-auto flex w-full max-w-[1700px] flex-col gap-3 ${workbenchView === 'overview' ? 'min-h-0 flex-1' : 'min-h-full'}`}
          >
            <LlmStatusBanner />
            <DeliveryStatusBanner />
            <header
              className={`flex shrink-0 items-center justify-between rounded-2xl border border-[#e1eee8] bg-white shadow-[0_7px_24px_rgba(42,102,79,0.04)] ${
                workbenchView === 'overview' ? 'hidden' : 'px-5 py-3'
              }`}
            >
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#45b88b] text-lg text-white shadow-md shadow-emerald-100">
                  <WorkbenchIcon icon={WORKBENCH_BRAND_ICON} style={{ width: 18, height: 18 }} />
                </div>
                <div className="min-w-0">
                  <h1 className="truncate text-[18px] font-bold text-[#244c40]">
                    {workbenchView === 'overview'
                      ? overviewPanel === 'document'
                        ? '规划文本'
                        : overviewPanel === 'analysis'
                          ? '分层分析'
                          : '规划总览'
                      : workbenchView === 'drawings'
                        ? '空间成果图'
                        : dataPanel === 'metrics'
                          ? '指标报表'
                          : dataPanel === 'compliance'
                            ? '用地合规闸门'
                            : dataPanel === 'suitability'
                              ? '双评价适宜性'
                              : '知识图谱检查'}
                  </h1>
                  <p
                    className={`truncate text-[#78968b] ${workbenchView === 'overview' && overviewPanel === 'analysis' ? 'hidden' : 'text-[11px]'}`}
                  >
                    <b className="text-[#29906b]">
                      {activeVillageName || payload?.villageName || projectName || (sessionId ? '当前会话' : '金田村')}
                      项目
                    </b>{' '}
                    · {sessionId ? `Agent ${sessionId.slice(0, 8)}` : '等待启动规划'} · {status}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    setWorkbenchView('overview');
                    setOverviewPanel('analysis');
                  }}
                  className="rounded-xl border border-[#d5e9df] px-3 py-2 text-[12px] text-[#52766a] hover:bg-[#f4faf7]"
                >
                  ↩ 分层分析
                </button>
                {sessionId && (
                  <button
                    onClick={() => setShowExportDialog(true)}
                    className="rounded-xl border border-[#d5e9df] px-3 py-2 text-[12px] text-[#52766a] hover:bg-[#f4faf7]"
                  >
                    导出
                  </button>
                )}
                <button
                  onClick={() => void loadResult(true)}
                  className="rounded-xl bg-[#3fb288] px-3 py-2 text-[12px] font-medium text-white hover:bg-[#319a75]"
                >
                  刷新成果
                </button>
              </div>
            </header>

            <section
              className={`grid shrink-0 gap-2 rounded-2xl border border-[#e1eee8] bg-white px-4 py-3 shadow-[0_7px_24px_rgba(42,102,79,0.04)] md:grid-cols-3 ${workbenchView === 'overview' ? 'hidden' : ''}`}
            >
              {(['L1 现状分析', 'L2 规划思路', 'L3 详细规划'] as const).map((label, index) => {
                const layer = (index + 1) as 1 | 2 | 3;
                const done = completedLayers[layer];
                const firstPending = ([1, 2, 3] as const).find((item) => !completedLayers[item]) ?? 3;
                const active = layer === firstPending;
                const phaseText = done
                  ? '已完成'
                  : sessionId && active
                    ? status === 'planning'
                      ? '生成中'
                      : '待继续'
                    : '待开始';
                return (
                  <div key={label} className="min-w-0">
                    <div
                      className={`flex items-center gap-2 truncate text-[12px] font-medium ${done || active ? 'text-[#328e6d]' : 'text-[#8aa59a]'}`}
                    >
                      <span
                        className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] ${done ? 'bg-[#45b88b] text-white' : active ? 'border-2 border-[#45b88b] bg-white text-[#2f916e]' : 'border-2 border-[#ccdfd6] bg-white text-[#99afa6]'}`}
                      >
                        {renderLayerDoneIcon(done, layer)}
                      </span>
                      {label} · {phaseText}
                    </div>
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#e7f2ed]">
                      <div
                        className="h-full rounded-full bg-[#46b58a] transition-all"
                        style={{
                          width: done ? '100%' : active && status === 'planning' ? '45%' : '0%',
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </section>

            {workbenchView === 'drawings' && (
              <section className="grid shrink-0 grid-cols-2 gap-2 xl:grid-cols-4">
                <MetricCard
                  icon={WORKBENCH_METRIC_ICONS.spatialFeatures}
                  value={totalFeatures}
                  label="已加载现状数据"
                  note={`${layers.length} 个真实图层`}
                />
                <MetricCard
                  icon={WORKBENCH_METRIC_ICONS.entityTypes}
                  value={typeCount}
                  label="底图分类"
                  note="来自真实 GIS 图层"
                />
                <MetricCard
                  icon={WORKBENCH_METRIC_ICONS.plannedParcels}
                  value={plannedParcels || plannedOverlayFeatures || '—'}
                  label="规划成果"
                  note={plannedParcels || plannedOverlayFeatures ? '已返回 DELIVER 规划图层' : '等待 DELIVER 空间快照'}
                />
                <MetricCard
                  icon={WORKBENCH_METRIC_ICONS.roads}
                  value={currentRoads + referenceRoads + stage5Roads || '—'}
                  label="道路成果"
                  note={stage5Roads || finalRoads ? '已有道路链记录' : '尚未产出道路结论'}
                />
              </section>
            )}

            {workbenchView === 'drawings' && visibleCurrentGisSource && (
              <section className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-[#dcebe4] bg-[#f8fcf9] px-3 py-2 text-[11px] text-[#5f8174]">
                <span className="font-semibold text-[#347b61]">现状数据源 · DATA catalog</span>
                <span>
                  {visibleCurrentGisSource.layers.length} 个现状图层 · {totalFeatures.toLocaleString()} 个要素
                </span>
                {visibleCurrentGisSource.rasters.map((raster) => (
                  <span key={raster.source_name} className={raster.available ? 'text-[#347b61]' : 'text-[#a66a4f]'}>
                    {raster.layer_name || raster.source_name}{' '}
                    {raster.available
                      ? `已接入 · ${raster.width ?? '—'}×${raster.height ?? '—'} · ${raster.crs || '未知坐标系'}`
                      : `不可用 · ${raster.reason || '后端未提供'}`}
                  </span>
                ))}
                {visibleCurrentGisSource.diagnostics.map((diagnostic) => (
                  <span key={diagnostic} className="text-[#a66a4f]">
                    数据源提示：{diagnostic}
                  </span>
                ))}
              </section>
            )}

            {workbenchView === 'drawings' &&
              !shouldLoadCurrentSource &&
              !hasSessionGisLayers &&
              referenceVillageName && (
                <section className="shrink-0 rounded-xl border border-[#f0d9c7] bg-[#fffaf5] px-3 py-2 text-[11px] text-[#966b4f]">
                  当前 session 尚未提供村庄“{referenceVillageName}”的已准入 DATA 数据；本页不会注入其他 session 的参考图层，
                  规划图层须等待本会话 DELIVER 空间快照。
                </section>
              )}

            {workbenchView === 'overview' && (
              <section className="grid min-h-0 flex-1 gap-0" style={{ gridTemplateColumns: 'minmax(0,1fr)' }}>
                <div className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-[0_10px_32px_rgba(38,95,74,0.06)]">
                  <OverviewWorkspaceHeader
                    overviewPanel={overviewPanel}
                    sessionId={sessionId}
                    status={status}
                    stepMode={stepMode}
                    stepModeLoading={stepModeLoading}
                    completedLayers={completedLayers}
                    onPanelChange={setOverviewPanel}
                    onStepModeChange={(enabled) => void handleStepModeChange(enabled)}
                    evaluationActions={undefined}
                  />
                  <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-[#fbfcfb]">
                    {overviewPanel === 'task' ? (
                      <PlanningTaskPanel
                        overviewLevel={overviewLevel}
                        onOverviewLevelChange={setOverviewLevel}
                        projectName={projectName}
                        villageData={villageData}
                        taskDescription={taskDescription}
                        constraintsText={constraintsText}
                        province={province}
                        city={city}
                        county={county}
                        township={township}
                        villageName={villageName}
                        planningPeriod={planningPeriod}
                        planningError={planningError}
                        stepMode={stepMode}
                        stepModeLoading={stepModeLoading}
                        onChange={handleTaskFieldChange}
                        onFillExample={fillExample}
                        onStart={() => void handleStartPlanning()}
                        onStepModeChange={handleStepModeChange}
                        isStarting={isStartingPlanning}
                        villageDataFiles={villageDataFiles}
                        taskFiles={taskFiles}
                        constraintFiles={constraintFiles}
                        onFilesChange={handleTaskFilesChange}
                      />
                    ) : overviewPanel === 'analysis' ? (
                      planningBootstrap.isBootstrapping ? (
                        <PlanningBootstrapPanel headline={planningBootstrap.headline} steps={planningBootstrap.steps} />
                      ) : sessionId ? (
                        <PlanningAnalysisWorkspace
                          isPaused={isPaused}
                          onApprove={() => void approve()}
                          onGoToTask={() => setOverviewPanel('task')}
                          onExport={() => setShowExportDialog(true)}
                          sessionConnected={!!sessionId}
                          chatPanel={
                            <>
                              <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-[#fcfdfc] px-1">
                                <MessageList messages={messages} isTyping={status === 'planning'} />
                              </div>
                              <div className="shrink-0 border-t border-[#e5efe9] bg-white">
                                <ChatInput disabled={!sessionId} onSend={handleChat} />
                              </div>
                            </>
                          }
                        />
                      ) : (
                        <OverviewLockedPlaceholder variant="analysis" onGoToTask={() => setOverviewPanel('task')} />
                      )
                    ) : overviewPanel === 'evaluation' ? (
                      <section className="flex min-h-[320px] items-center justify-center rounded-2xl border border-dashed border-[#cfe4da] bg-[#f8fcf9] p-8 text-center text-[12px] text-[#8aa59a]">
                        质量评估 API 在 v1 后端已下线；请通过分层分析报告与交付合规面板核查成果。
                      </section>
                    ) : overviewPanel === 'document' ? (
                      sessionId ? (
                        <PlanningTextViewer sessionId={sessionId} embedded />
                      ) : (
                        <OverviewLockedPlaceholder variant="document" onGoToTask={() => setOverviewPanel('task')} />
                      )
                    ) : null}
                  </div>
                </div>
              </section>
            )}

            {workbenchView === 'data' && (
              <DataCenterPanel
                panel={dataPanel}
                sessionId={sessionId}
                projectName={projectName || payload?.villageName}
                payload={payload}
                layers={layers}
                roadProjects={roadProjects}
                positioningTrace={positioningTrace}
                spatialWorkflowSteps={spatialWorkflowSteps}
                spatialArtifactKeys={spatialArtifactKeys}
                typeCount={typeCount}
                totalFeatures={totalFeatures}
                currentParcels={currentParcels}
                plannedParcels={plannedParcels}
                constraints={constraints}
                onOpenDrawings={() => handleSidebarNavigate('drawings')}
              />
            )}

            {workbenchView === 'drawings' && (
              <>
                <section className="shrink-0 rounded-2xl border border-[#e1eee8] bg-white px-4 py-3 shadow-[0_7px_24px_rgba(42,102,79,0.04)]">
                  <div className="flex flex-wrap items-center gap-2 border-b border-[#edf4f0] pb-2 text-[11px]">
                    <span className="mr-1 font-medium text-[#6f8f83]">底图</span>
                    {(
                      [
                        ['general', '通用底图'],
                        ['amap', '高德地图'],
                      ] as const
                    ).map(([key, label]) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setBaseMap(key)}
                        className={`rounded-full border px-3 py-1.5 transition-colors ${baseMap === key ? 'border-[#41b58a] bg-[#e1f4eb] font-semibold text-[#248865]' : 'border-[#dbe9e2] text-[#78938a]'}`}
                      >
                        {label}
                      </button>
                    ))}
                    <span className="ml-3 mr-1 font-medium text-[#6f8f83]">综合视图</span>
                    {FILTERS.map((item) => (
                      <button
                        type="button"
                        key={item.key}
                        aria-pressed={filters.has(item.key)}
                        onClick={() => selectFilter(item.key)}
                        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 transition-colors ${filters.has(item.key) ? 'border-[#41b58a] bg-[#41b58a] font-semibold text-white' : 'border-[#d6e8df] bg-[#f8fbf9] text-[#648378] hover:border-[#79c8aa]'}`}
                      >
                        <WorkbenchIcon icon={LAYER_FILTER_ICONS[item.key]} style={{ width: 11, height: 11 }} />
                        {item.label}
                      </button>
                    ))}
                    <span className="ml-auto flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          selectFilter('planning');
                        }}
                        className="rounded-lg border border-[#b8e5d2] bg-[#edf9f3] px-2.5 py-1.5 text-[#1f8763] hover:bg-[#dff2e9]"
                      >
                        显示规划图层
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          selectFilter('roads');
                        }}
                        className="rounded-lg border border-[#f0c987] bg-[#fff7e8] px-2.5 py-1.5 text-[#9a6418] hover:bg-[#ffefd4]"
                      >
                        显示道路样式
                      </button>
                      <span className="rounded-lg bg-[#f1f7f4] px-2 py-1.5 text-[#6b897e]">
                        当前显示 {displayMapLayers.length} 图层 · {activeFilterLabel}
                      </span>
                    </span>
                  </div>
                  <div className="mt-2 space-y-1.5 text-[11px]">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-medium text-[#78958a]">图层摘要</span>
                      <span className="rounded-full bg-[#f1f7f4] px-2.5 py-1 text-[#648378]">
                        现状：{currentParcels} 地块
                      </span>
                      <span className="rounded-full bg-[#f1f7f4] px-2.5 py-1 text-[#648378]">
                        现状道路：{currentRoads}
                      </span>
                      <span
                        className={`rounded-full px-2.5 py-1 ${plannedParcels || stage5Roads ? 'bg-[#e1f4eb] text-[#248865]' : 'bg-[#fff7e8] text-[#9a7428]'}`}
                      >
                        规划：
                        {plannedParcels || plannedOverlayFeatures || stage5Roads
                          ? `${plannedParcels + plannedOverlayFeatures + stage5Roads} 项已返回`
                          : '尚未交付'}
                      </span>
                      <button
                        type="button"
                        onClick={() => setShowMapDetails((value) => !value)}
                        className="rounded-full border border-[#dcebe4] px-2.5 py-1 text-[#6c887e] hover:bg-[#f4faf7]"
                      >
                        {showMapDetails ? '收起分类' : '查看分类'}
                      </button>
                    </div>
                    {showMapDetails &&
                      quickGroups.map((group) => (
                        <div key={group.label} className="flex flex-wrap items-center gap-1.5">
                          <span className="inline-flex w-12 shrink-0 items-center gap-1 font-medium text-[#78958a]">
                            <WorkbenchIcon
                              icon={QUICK_LAYER_GROUP_ICONS[group.label]}
                              style={{ width: 10, height: 10 }}
                            />
                            {group.label}
                          </span>
                          {group.options.map(([key, label]) => {
                            const active = selectedLayerKeys.has(key);
                            return (
                              <button
                                key={key}
                                onClick={() => toggleLayer(key)}
                                className={`rounded-full border px-2.5 py-1 transition-colors ${active ? 'border-[#3fb188] bg-[#e1f4eb] font-semibold text-[#1f8763]' : 'border-[#dcebe4] bg-[#fafcfb] text-[#6c887e] hover:border-[#87cbb0]'}`}
                              >
                                {label}
                              </button>
                            );
                          })}
                        </div>
                      ))}
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="w-12 shrink-0 font-medium text-[#78958a]">KG 拓扑</span>
                      {SPATIAL_RELATIONS.map((relation) => {
                        const active = activeRelation === relation.key;
                        return (
                          <button
                            key={relation.key}
                            type="button"
                            onClick={() => setActiveRelation(relation.key)}
                            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 transition-colors ${active ? 'font-semibold' : 'border-[#e3dbea] bg-[#fcfafe] text-[#826f8e]'}`}
                            style={
                              active
                                ? {
                                    borderColor: relation.activeBorder,
                                    backgroundColor: relation.activeBg,
                                    color: relation.activeText,
                                  }
                                : undefined
                            }
                          >
                            <RelationDot color={relation.color} />
                            {relation.label}
                          </button>
                        );
                      })}
                      <span className="ml-1 text-[10px] text-[#9aada6]">
                        地图检查模式；实体证据与关系结论由 KG 模块返回
                      </span>
                    </div>
                  </div>
                </section>

                <div className="flex h-8 shrink-0 items-center gap-2 rounded-lg bg-[#e5f1eb] px-2">
                  <button
                    type="button"
                    onClick={() => setMapHeight((value) => Math.max(420, value - 80))}
                    className="h-6 rounded-md bg-white px-2 text-[11px] text-[#39745f] shadow-sm"
                    title="缩小地图"
                  >
                    −
                  </button>
                  <div
                    onPointerDown={(event) => beginResize('map', event)}
                    onDoubleClick={() => setMapHeight(720)}
                    className="group flex h-full min-w-0 flex-1 touch-none cursor-row-resize items-center justify-center"
                    title="上下拖动调整地图高度；双击复位"
                    role="separator"
                    aria-orientation="horizontal"
                    aria-label="调整地图高度"
                    aria-valuenow={mapHeight}
                    tabIndex={0}
                  >
                    <span className="h-1 w-24 rounded-full bg-[#78a995] group-hover:bg-[#2da979]" />
                    <span className="ml-2 text-[10px] text-[#527d6d]">上下拖动 · {mapHeight}px</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setMapHeight(720)}
                    className="h-6 rounded-md bg-white px-2 text-[11px] text-[#39745f] shadow-sm"
                    title="恢复默认高度"
                  >
                    复位
                  </button>
                  <button
                    type="button"
                    onClick={() => setMapHeight((value) => Math.min(950, value + 80))}
                    className="h-6 rounded-md bg-white px-2 text-[11px] text-[#39745f] shadow-sm"
                    title="放大地图"
                  >
                    ＋
                  </button>
                </div>
                <section
                  className="grid min-h-[560px] flex-1 gap-0"
                  style={{
                    gridTemplateColumns: `minmax(0,1fr) 10px minmax(380px, ${rightPanelWidth}px)`,
                  }}
                >
                  <div
                    className="relative overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-[0_10px_32px_rgba(38,95,74,0.06)]"
                    style={{ height: mapHeight }}
                  >
                    {!error && (
                      <MapView
                        layers={mapLayersLoading ? [] : displayMapLayers}
                        center={mapCenter}
                        height={`${mapHeight}px`}
                        tileSourceOverride={baseMap === 'amap' ? 'amap' : 'offline'}
                        offlineBaseMap={baseMap === 'general'}
                        fitPadding={110}
                        hoverPopup
                        maxMapLabels={36}
                        showLegend={!mapLayersLoading}
                        compactLegend
                        frameless
                        focusFeature={evidenceFocus}
                        focusFeatures={evidenceFocuses}
                      />
                    )}
                    {mapLayersLoading && (
                      <div className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-[#f7fbf9]/80">
                        <div className="h-9 w-9 animate-spin rounded-full border-4 border-[#c9e8db] border-t-[#40b388]" />
                        <div className="mt-4 text-[13px] font-medium text-[#447265]">正在读取规划成果图层…</div>
                        <div className="mt-1 text-[11px] text-[#91a9a0]">
                          {baseMap === 'amap'
                            ? '高德底图已显示，规划图层首次约 5–15 秒'
                            : '底图已显示，规划图层首次约 5–15 秒'}
                        </div>
                      </div>
                    )}
                    {loading && visibleCurrentGisSource?.layers?.length && !error && (
                      <div className="pointer-events-none absolute inset-x-0 top-3 z-20 mx-auto w-fit rounded-full border border-[#d8e9e1] bg-white/90 px-4 py-1.5 text-[11px] text-[#33765f] shadow-sm">
                        目录现状数据已显示，规划成果加载中…
                      </div>
                    )}
                    {showingReferenceGis && !mapLayersLoading && !error && (
                      <div className="pointer-events-none absolute inset-x-0 top-3 z-20 mx-auto w-fit rounded-full border border-[#d8e9e1] bg-white/90 px-4 py-1.5 text-[11px] text-[#33765f] shadow-sm">
                        当前显示本 session 的真实 DATA 现状数据；本会话 DELIVER 空间快照尚未就绪，规划图层不会被伪造
                      </div>
                    )}
                    {error ? (
                      <div className="absolute inset-0 z-40 flex flex-col items-center justify-center bg-[#f8fbf9]/95 px-8 text-center">
                        <div className="text-3xl">!</div>
                        <div className="mt-3 text-sm font-semibold text-[#8d4c3b]">成果加载失败</div>
                        <div className="mt-2 text-xs text-[#94776e]">{error}</div>
                        <button
                          onClick={() => void loadResult(true)}
                          className="mt-5 rounded-lg bg-[#42b48a] px-4 py-2 text-xs text-white"
                        >
                          重新加载
                        </button>
                      </div>
                    ) : !mapLayersLoading && mapLayers.length === 0 ? (
                      <div className="pointer-events-none absolute inset-x-0 top-3 z-20 mx-auto w-fit rounded-full border border-[#f0d7a5] bg-[#fff8e8]/95 px-4 py-1.5 text-[11px] text-[#8a6420] shadow-sm">
                        底图已加载；当前筛选无图层，请点击「全部成果」或「显示规划图层」
                      </div>
                    ) : null}
                    <div className="pointer-events-none absolute bottom-3 left-3 z-20 flex items-center gap-1.5 rounded-full border border-[#d8e9e1] bg-white/90 px-3 py-1.5 text-[11px] text-[#33765f] shadow-sm">
                      <RelationDot color="#3498db" />
                      图谱空间联动模式
                    </div>
                  </div>
                  <div
                    onPointerDown={(event) => beginResize('side', event)}
                    className="group relative cursor-col-resize touch-none"
                    role="separator"
                    aria-orientation="vertical"
                    aria-label="调整空间侧栏宽度"
                    aria-valuenow={rightPanelWidth}
                    tabIndex={0}
                    title="左右拖动调整空间侧栏宽度"
                  >
                    <span className="absolute inset-y-0 left-1/2 w-px bg-[#c9dfd5] group-hover:w-1 group-hover:bg-[#3fb288]" />
                  </div>
                  <aside className="min-h-0 overflow-y-auto pr-1">
                    <div className="sticky top-0 z-30 mb-3 flex flex-wrap gap-1 rounded-2xl border border-[#dcebe4] bg-white/95 p-1.5 shadow-sm backdrop-blur">
                      {(
                        [
                          ['assistant', '空间助手'],
                          ['spatial', '空间链路'],
                          ['kg', 'KG 模块'],
                        ] as Array<[SpatialSidebarTab, string]>
                      ).map(([tab, label]) => (
                        <button
                          key={tab}
                          type="button"
                          onClick={() => setSpatialSidebarTab(tab)}
                          className={`rounded-xl px-2.5 py-1.5 text-[11px] transition ${spatialSidebarTab === tab ? 'bg-[#dff2e9] font-semibold text-[#2d7e61]' : 'text-[#78968b] hover:bg-[#f1f8f4]'}`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    {spatialSidebarTab === 'assistant' && (
                      <div className="space-y-3">
                        <div className="overflow-hidden rounded-2xl border border-[#cfe7db] bg-gradient-to-br from-[#f7fcf9] to-white shadow-[0_10px_28px_rgba(42,102,79,0.06)]">
                          <div className="border-b border-[#e4f0ea] px-4 py-3">
                            <div className="flex items-start justify-between gap-3">
                              <div>
                                <div className="text-[13px] font-semibold text-[#285e4b]">空间助手</div>
                                <div className="mt-1 text-[10px] leading-4 text-[#78968b]">
                                  自然语言触发真实证据查询或规划对话，结果会联动地图。
                                </div>
                              </div>
                              <span className="rounded-full bg-[#dff2e9] px-2 py-1 text-[10px] font-semibold text-[#2d7e61]">
                                真实 API
                              </span>
                            </div>
                            <div className="mt-3 flex rounded-xl bg-[#edf7f1] p-1">
                              {(
                                [
                                  ['locator', '实体定位工具'],
                                  ['chat', '规划对话'],
                                ] as Array<[SpatialAssistantMode, string]>
                              ).map(([mode, label]) => (
                                <button
                                  key={mode}
                                  type="button"
                                  onClick={() => setSpatialAssistantMode(mode)}
                                  className={`flex-1 rounded-lg px-2 py-2 text-[11px] transition ${spatialAssistantMode === mode ? 'bg-white font-semibold text-[#2d7e61] shadow-sm' : 'text-[#78968b] hover:text-[#39745f]'}`}
                                >
                                  {label}
                                </button>
                              ))}
                            </div>
                          </div>
                          {spatialAssistantMode === 'locator' ? (
                            <div className="p-3">
                              <EvidenceQueryPanel
                                sessionId={sessionId}
                                villageName={villageName || payload?.villageName || ''}
                                onFocusFeatures={focusEvidenceFeatures}
                                onFocusFeature={(feature) => focusEvidenceFeatures([feature])}
                              />
                            </div>
                          ) : (
                            <div className="flex min-h-[520px] flex-col bg-[#fcfdfc]">
                              <div className="min-h-0 flex-1 overflow-y-auto px-1">
                                <MessageList messages={messages} isTyping={status === 'planning'} />
                              </div>
                              <div className="shrink-0 border-t border-[#e5efe9] bg-white">
                                <ChatInput disabled={!sessionId} onSend={handleChat} />
                              </div>
                            </div>
                          )}
                        </div>
                        {evidenceFocuses.length > 0 && spatialAssistantMode === 'locator' && (
                          <div className="rounded-xl border border-[#bfe3d0] bg-[#effaf4] px-3 py-2.5 text-[11px] text-[#2d7e61]">
                            <div className="font-semibold">地图已高亮 {evidenceFocuses.length} 个真实候选</div>
                            <div className="mt-1 text-[10px] leading-4 text-[#5b8a78]">
                              点击候选卡可缩小到单个实体；再次查询会替换本轮高亮。
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                    {spatialSidebarTab === 'kg' && (
                      <div className="overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-[0_7px_24px_rgba(42,102,79,0.04)]">
                        <PanelTitle title="KG 模块 · 实体" note="L1 / GIS 真实实体" />
                        <div className="px-3 py-3 text-[12px]">
                          <div className="mb-2 rounded-lg bg-[#dff2e9] px-3 py-1.5 font-semibold text-[#2d7e61]">
                            现状实体
                          </div>
                          {ENTITY_BROWSER_CURRENT.map((entry) => (
                            <EntityBrowserRow
                              key={entry.name}
                              entry={entry}
                              count={
                                {
                                  现状地块: currentParcels,
                                  现状道路: currentRoads,
                                  管控约束: constraints,
                                  设施与标注: facilities,
                                }[entry.name] ?? 0
                              }
                            />
                          ))}
                          <div className="mb-2 mt-3 rounded-lg bg-[#dff2e9] px-3 py-1.5 font-semibold text-[#2d7e61]">
                            规划成果
                          </div>
                          {ENTITY_BROWSER_PLANNED.map((entry) => (
                            <EntityBrowserRow
                              key={entry.name}
                              entry={entry}
                              count={
                                {
                                  规划地块: plannedParcels,
                                  既有规划道路: referenceRoads,
                                  'Stage5 道路': stage5Roads,
                                }[entry.name] ?? 0
                              }
                            />
                          ))}
                        </div>
                      </div>
                    )}

                    {spatialSidebarTab === 'spatial' && (
                      <details
                        className="overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-[0_7px_24px_rgba(42,102,79,0.04)]"
                        open={artifactDetailsOpen || Boolean(focusedArtifactKey)}
                        onToggle={(event) => setArtifactDetailsOpen(event.currentTarget.open)}
                      >
                        <summary className="cursor-pointer list-none px-3 py-3 text-[12px] font-semibold text-[#315f50] marker:hidden">
                          <span className="flex items-center justify-between gap-2">
                            <span>中间产物详情</span>
                            <span className="text-[10px] font-normal text-[#8aa59a]">按后端 artifact key 展开</span>
                          </span>
                        </summary>
                        <div className="border-t border-[#edf4f0] p-2">
                          <IntermediateArtifactsPanel sessionId={sessionId} focusKey={focusedArtifactKey} />
                        </div>
                      </details>
                    )}

                    {spatialSidebarTab === 'kg' && (
                      <div className="overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-[0_7px_24px_rgba(42,102,79,0.04)]">
                        <PanelTitle title="KG 模块 · 拓扑" note="点击上方 KG 拓扑模式切换" />
                        <div className="p-3">
                          {(() => {
                            const relationMeta = getSpatialRelation(activeRelation);
                            return (
                              <>
                                <div className="flex items-center gap-2">
                                  <span
                                    className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-semibold"
                                    style={{
                                      backgroundColor: relationMeta.activeBg,
                                      color: relationMeta.activeText,
                                    }}
                                  >
                                    <RelationDot color={relationMeta.color} />
                                    {relationMeta.label}
                                  </span>
                                  <span className="text-[10px] text-[#8da49b]">当前 KG 拓扑检查模式</span>
                                </div>
                                <p className="mt-2 text-[11px] leading-5 text-[#607b71]">
                                  {
                                    {
                                      邻近: 'KG 拓扑检查地块与设施、道路及项目点的近距离关联。',
                                      相邻: 'KG 拓扑检查地块之间是否共享边界，用于连片规划判断。',
                                      包含: 'KG 拓扑检查地块是否位于功能区或刚性管控范围内部。',
                                      相交: 'KG 拓扑检查道路、地块与生态红线等约束是否发生相交。',
                                      道路连接: spatialArtifactKeys.has('execution_result')
                                        ? 'KG 拓扑检查后端 EXECUTE 结果中的道路网络连通关系。'
                                        : '道路执行结果尚未到达；当前仅选择拓扑检查模式，不生成候选线数量。',
                                    }[activeRelation]
                                  }
                                </p>
                              </>
                            );
                          })()}
                        </div>
                      </div>
                    )}

                    {spatialSidebarTab === 'spatial' && (
                      <div className="space-y-3">
                        <div className="overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-[0_7px_24px_rgba(42,102,79,0.04)]">
                          <PanelTitle
                            title="空间链路"
                            note={positioningTrace ? `${positioningTrace.reports.length} 条真实记录` : '等待后端过程'}
                          />
                          <div className="px-4 py-3">
                            {spatialWorkflowSteps.map((step, index) => (
                              <div key={step.label} className="relative flex gap-3 pb-3 last:pb-0">
                                {index < spatialWorkflowSteps.length - 1 && (
                                  <span className="absolute left-[9px] top-5 h-full w-px bg-[#c9e6d9]" />
                                )}
                                <span
                                  className={`relative z-10 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${step.status === 'recorded' || step.registeredArtifactKeys.length > 0 ? 'bg-[#42b48a] text-white' : 'bg-[#eef3f0] text-[#9aada6]'}`}
                                >
                                  {step.status === 'recorded'
                                    ? '✓'
                                    : step.registeredArtifactKeys.length > 0
                                      ? '•'
                                      : index + 1}
                                </span>
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center justify-between gap-2">
                                    <span className="truncate text-[12px] font-medium text-[#3c6255]">
                                      {step.label}
                                    </span>
                                    <span
                                      className={`shrink-0 text-[10px] ${step.status === 'recorded' || step.registeredArtifactKeys.length > 0 ? 'text-[#3c9b76]' : 'text-[#9aada6]'}`}
                                    >
                                      {step.status === 'recorded'
                                        ? '过程已记录'
                                        : step.registeredArtifactKeys.length > 0
                                          ? '产物已登记'
                                          : '尚未到达'}
                                    </span>
                                  </div>
                                  <div className="mt-0.5 truncate text-[10px] text-[#8aa59a]">{step.value}</div>
                                  {step.humanReports.length > 0 && (
                                    <IntentProjectOverview
                                      projects={step.humanReports.flatMap((report) => report.projectHints)}
                                      claimCount={step.humanReports.reduce(
                                        (count, report) => count + report.claimCount,
                                        0,
                                      )}
                                      dimensionCount={step.humanReports.length}
                                      workflowSteps={spatialWorkflowSteps}
                                    />
                                  )}
                                  {step.registeredArtifactKeys.length > 0 ? (
                                    <div className="mt-1 flex flex-wrap gap-1">
                                      {step.registeredArtifactKeys.map((key) => (
                                        <button
                                          key={key}
                                          type="button"
                                          onClick={() => {
                                            setFocusedArtifactKey(key);
                                            setArtifactDetailsOpen(true);
                                          }}
                                          className="rounded-full bg-[#e8f6ef] px-1.5 py-0.5 text-[9px] text-[#2d7e61] transition hover:bg-[#cdeade] hover:text-[#1f6c51]"
                                          title={`查看${SPATIAL_ARTIFACT_LABELS[key] || key}详情`}
                                        >
                                          {SPATIAL_ARTIFACT_LABELS[key] || key}
                                        </button>
                                      ))}
                                    </div>
                                  ) : step.status === 'recorded' && step.expectedArtifactKeys.length > 0 ? (
                                    <div className="mt-1 text-[9px] text-[#a27a58]">阶段已记录 · 空间产物尚未登记</div>
                                  ) : null}
                                </div>
                              </div>
                            ))}
                            <div className="mt-1 rounded-lg bg-[#f5faf7] px-2.5 py-2 text-[10px] leading-4 text-[#78968b]">
                              流程状态来自 positioning-trace；未到达阶段不会用 0 项或示意结果填充。
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </aside>
                </section>
              </>
            )}
            {showPlanningText && sessionId && (
              <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/35 p-4">
                <div className="flex h-[90vh] w-[min(1180px,96vw)] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
                  <div className="flex items-center justify-between border-b px-5 py-3">
                    <b>规划文本成果</b>
                    <button
                      onClick={() => setShowPlanningText(false)}
                      className="rounded-lg border px-3 py-1.5 text-xs"
                    >
                      关闭
                    </button>
                  </div>
                  <div className="min-h-0 flex-1">
                    <PlanningTextViewer sessionId={sessionId} />
                  </div>
                </div>
              </div>
            )}
            {sessionId && (
              <ExportDialog
                sessionId={sessionId}
                isOpen={showExportDialog}
                onClose={() => setShowExportDialog(false)}
              />
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

export default function PlanningWorkbenchPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-[#f2f7f4] text-sm text-[#4d7668]">
          正在加载规划工作台…
        </div>
      }
    >
      <PlanningProvider conversationId="unified-planning-workbench">
        <UnifiedPlanningWorkbench />
      </PlanningProvider>
    </Suspense>
  );
}
