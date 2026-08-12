'use client';

import React, { useCallback, useMemo, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faChevronDown, faChevronRight, faLayerGroup } from '@fortawesome/free-solid-svg-icons';
import type { GISLayerConfig } from '@/types/message/message-types';
import { LAYER_TYPE_LABELS, type LayerType } from '../../constants/gis';

interface LayerTogglePanelProps {
  layers: GISLayerConfig[];
  visibleTypes: Set<LayerType>;
  onToggle: (type: LayerType) => void;
}

const LAYER_GROUPS: Array<{ label: string; types: LayerType[] }> = [
  { label: '标准成果', types: ['planning_scope', 'final_landuse', 'land_use_zone', 'construction_control'] },
  { label: '设施交通', types: ['infrastructure', 'planned_road', 'facility_point', 'development_axis', 'isochrone'] },
  { label: '分析参考', types: ['boundary', 'function_zone', 'planning_zone', 'sensitivity_zone', 'hazard_point', 'settlement_zone'] },
];

const VIEW_PRESETS: Array<{ key: string; label: string; types: LayerType[] }> = [
  {
    key: 'overview',
    label: '总图',
    types: [
      'boundary', 'planning_scope', 'final_landuse', 'planning_zone',
      'function_zone', 'construction_control', 'infrastructure',
      'planned_road', 'facility_point', 'development_axis', 'hazard_point',
    ],
  },
  { key: 'result', label: '成果', types: ['planning_scope', 'final_landuse'] },
  { key: 'control', label: '管控', types: ['planning_scope', 'land_use_zone', 'construction_control'] },
  { key: 'facility', label: '设施', types: ['planning_scope', 'final_landuse', 'infrastructure', 'planned_road', 'facility_point', 'development_axis'] },
  { key: 'review', label: '校核', types: ['planning_scope', 'boundary', 'function_zone', 'planning_zone', 'sensitivity_zone', 'hazard_point'] },
];

export default function LayerTogglePanel({
  layers,
  visibleTypes,
  onToggle,
}: LayerTogglePanelProps) {
  const [showDetails, setShowDetails] = useState(false);
  const presentTypes = useMemo(() => Array.from(
    new Set(layers.map((l) => l.layerType as LayerType)),
  ), [layers]);

  const applyTypes = useCallback((targetTypes: LayerType[]) => {
    const target = new Set(targetTypes.filter((type) => presentTypes.includes(type)));
    presentTypes.forEach((t) => {
      const shouldBeVisible = target.has(t);
      if (shouldBeVisible !== visibleTypes.has(t)) {
        onToggle(t);
      }
    });
  }, [presentTypes, visibleTypes, onToggle]);

  const activePreset = useMemo(() => {
    const visible = presentTypes.filter((type) => visibleTypes.has(type));
    if (visible.length === presentTypes.length) return 'all';
    for (const preset of VIEW_PRESETS) {
      const target = preset.types.filter((type) => presentTypes.includes(type));
      if (
        target.length === visible.length &&
        target.every((type) => visibleTypes.has(type))
      ) {
        return preset.key;
      }
    }
    return 'custom';
  }, [presentTypes, visibleTypes]);
  const visibleCount = presentTypes.filter((type) => visibleTypes.has(type)).length;
  const planningMetadata = useMemo(
    () => layers
      .map((layer) => layer.metadata)
      .find((metadata) => Boolean(
        metadata?.planningBasis
        || metadata?.dataQuality
        || metadata?.intentSummary
        || metadata?.validation,
      )),
    [layers],
  );
  const planningBasis = planningMetadata?.planningBasis;
  const dataQuality = planningMetadata?.dataQuality;
  const intentSummary = planningMetadata?.intentSummary;
  const validation = planningMetadata?.validation;
  const roadMetadata = useMemo(
    () => layers.find((layer) => layer.layerType === 'planned_road')?.metadata,
    [layers],
  );
  const roadSteps = roadMetadata?.processTrace?.steps || [];
  const qualityLabel = dataQuality?.status === 'ready'
    ? '真实地块齐全'
    : dataQuality?.status === 'degraded'
      ? '基础数据待补充'
      : dataQuality?.status === 'blocked'
        ? '仅解析规划意图'
        : '';
  const validationLabel = validation?.status === 'pass'
    ? '校核通过'
    : validation?.status === 'fail'
      ? '校核未通过'
      : validation?.status === 'error'
        ? '校核异常'
        : '待校核';

  if (presentTypes.length === 0) return null;

  return (
    <div className="border-b border-slate-100 px-2 py-1.5">
      <div className="flex items-center gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          <FontAwesomeIcon icon={faLayerGroup} className="text-slate-400" style={{ width: 11, height: 11 }} />
          <span className="shrink-0 text-[10px] font-medium text-slate-500">视图</span>
          <div className="flex min-w-0 overflow-hidden rounded border border-slate-200 bg-slate-50">
            {VIEW_PRESETS.map((preset) => (
              <button
                key={preset.key}
                type="button"
                onClick={() => applyTypes(preset.types)}
                className={`h-6 border-r border-slate-200 px-2 text-[10px] last:border-r-0 ${activePreset === preset.key ? 'bg-white font-medium text-emerald-700 shadow-sm' : 'text-slate-500 hover:bg-white'}`}
              >
                {preset.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => applyTypes(presentTypes)}
              className={`h-6 px-2 text-[10px] ${activePreset === 'all' ? 'bg-white font-medium text-emerald-700 shadow-sm' : 'text-slate-500 hover:bg-white'}`}
            >
              全部
            </button>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setShowDetails((value) => !value)}
          className="flex h-6 shrink-0 items-center gap-1 px-1 text-[10px] text-slate-500 hover:text-slate-800"
          aria-expanded={showDetails}
        >
          {visibleCount}/{presentTypes.length}
          <FontAwesomeIcon icon={showDetails ? faChevronDown : faChevronRight} style={{ width: 8, height: 8 }} />
        </button>
      </div>

      {planningMetadata && <div className="mt-1 flex min-w-0 items-center gap-1.5 overflow-hidden text-[9px] text-slate-500">
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${dataQuality?.status === 'ready' ? 'bg-emerald-500' : dataQuality?.status === 'degraded' ? 'bg-amber-500' : 'bg-slate-400'}`}
          aria-hidden="true"
        />
        {planningBasis && <span className="shrink-0" title={`${planningBasis.content_characters ?? 0} 字完整文本`}>
          依据{planningBasis.source_layers?.length ? ` L${planningBasis.source_layers.join('/L')}` : ''}
          {typeof planningBasis.report_count === 'number' ? ` · ${planningBasis.report_count} 项成果` : ''}
        </span>}
        {intentSummary?.spatial_structure && <span className="min-w-0 truncate" title={intentSummary.spatial_structure}>
          结构：{intentSummary.spatial_structure}
        </span>}
        {qualityLabel && <span className="shrink-0">{qualityLabel}</span>}
        <span className={`ml-auto shrink-0 ${validation?.status === 'pass' ? 'text-emerald-600' : validation?.status === 'fail' || validation?.status === 'error' ? 'text-rose-600' : 'text-slate-400'}`}>
          {validationLabel}
        </span>
      </div>}

      {roadSteps.length > 0 && (
        <div className="mt-1.5 rounded-lg border border-emerald-100 bg-emerald-50/60 px-2 py-1.5">
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[9px] leading-4">
            <span className="mr-1 font-semibold text-emerald-800">道路规划</span>
            {roadSteps.map((step, index) => {
              const passed = ['completed', 'passed'].includes(String(step.status));
              return (
                <React.Fragment key={step.id || `${step.label}-${index}`}>
                  {index > 0 && <span className="text-emerald-300">→</span>}
                  <span
                    className={`rounded px-1.5 py-0.5 ${passed ? 'bg-white text-emerald-800' : step.status === 'blocked' ? 'bg-rose-100 text-rose-700' : 'bg-slate-100 text-slate-500'}`}
                    title={step.status ? `状态：${step.status}` : undefined}
                  >
                    {step.label || step.id || `步骤 ${index + 1}`}
                  </span>
                </React.Fragment>
              );
            })}
          </div>
          <div className="mt-1 text-[9px] text-slate-500">
            {typeof roadMetadata?.totalLengthM === 'number' && <>推荐长度 {(roadMetadata.totalLengthM / 1000).toFixed(2)} km</>}
            {typeof roadMetadata?.processTrace?.planningNodeCount === 'number' && <> · 规划节点 {roadMetadata.processTrace.planningNodeCount}</>}
            {typeof roadMetadata?.processTrace?.humanReviewCount === 'number' && roadMetadata.processTrace.humanReviewCount > 0 && <> · 待人工复核 {roadMetadata.processTrace.humanReviewCount}</>}
          </div>
        </div>
      )}

      {showDetails && <div className="mt-1.5 space-y-1 border-t border-slate-100 pt-1.5">
        {LAYER_GROUPS.map(group => {
          const groupTypes = group.types.filter(type => presentTypes.includes(type));
          if (groupTypes.length === 0) return null;
          return (
            <div key={group.label} className="grid grid-cols-[52px_1fr] items-start gap-1.5">
              <span className="pt-0.5 text-[9px] text-slate-400">{group.label}</span>
              <div className="grid grid-cols-2 gap-x-2 gap-y-0.5">
              {groupTypes.map((type) => {
          const label = LAYER_TYPE_LABELS[type] || type;
          const standardCode = layers.find(layer => layer.layerType === type)?.standardCode;
          const visible = visibleTypes.has(type);
          return (
            <label
              key={type}
              className={`flex min-w-0 cursor-pointer items-center gap-1 text-[10px] ${visible ? 'text-slate-700' : 'text-slate-400'}`}
            >
              <input
                type="checkbox"
                checked={visible}
                onChange={() => onToggle(type)}
                className="h-3 w-3 shrink-0 accent-emerald-600"
              />
              <span className="min-w-0 truncate" title={standardCode ? `${label} (${standardCode})` : label}>
                {label}
              </span>
            </label>
          );
              })}
              </div>
            </div>
          );
        })}
      </div>}
    </div>
  );
}
