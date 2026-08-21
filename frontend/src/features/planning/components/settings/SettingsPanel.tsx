'use client';

import React from 'react';
import { usePlanningStore } from '../../store';
import { LAYER_VALUE_MAP, LAYER_IDS } from '@/features/planning/constants';
import { planningApi } from '../../api';

function Toggle({
  label,
  description,
  enabled,
  onToggle,
  loading,
}: {
  label: string;
  description?: string;
  enabled: boolean;
  onToggle: () => void;
  loading?: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-2.5 px-3 rounded-lg hover:bg-slate-50 transition-colors">
      <div className="flex flex-col gap-0.5">
        <span className="text-sm text-slate-700">{label}</span>
        {description && (
          <span className="text-xs text-slate-400">{description}</span>
        )}
      </div>
      <button
        onClick={onToggle}
        disabled={loading}
        className={`relative w-11 h-6 rounded-full transition-colors duration-200 ${
          enabled ? 'bg-[#0ea5e9]' : 'bg-slate-300'
        } ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
        aria-label={`切换 ${label}`}
      >
        <span
          className={`absolute top-1 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
            enabled ? 'left-6' : 'left-1'
          }`}
        />
      </button>
    </div>
  );
}

function LayerToggle({
  layer,
  label,
  enabled,
  onToggle,
  loading,
}: {
  layer: number;
  label: string;
  enabled: boolean;
  onToggle: () => void;
  loading?: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-2.5 px-3 rounded-lg hover:bg-slate-50 transition-colors">
      <div className="flex items-center gap-2.5">
        <span className="w-7 h-7 flex items-center justify-center rounded-md bg-slate-100 text-xs font-semibold text-slate-600">
          L{layer}
        </span>
        <span className="text-sm text-slate-700">{label}</span>
      </div>
      <button
        onClick={onToggle}
        disabled={loading}
        className={`relative w-11 h-6 rounded-full transition-colors duration-200 ${
          enabled ? 'bg-[#0ea5e9]' : 'bg-slate-300'
        } ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
        aria-label={`切换 ${label} 知识检索`}
      >
        <span
          className={`absolute top-1 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
            enabled ? 'left-6' : 'left-1'
          }`}
        />
      </button>
    </div>
  );
}

export default function SettingsPanel() {
  const ragLayerConfig = usePlanningStore((state) => state.ragLayerConfig);
  const toggleLayerRag = usePlanningStore((state) => state.toggleLayerRag);
  const stepMode = usePlanningStore((state) => state.step_mode);
  const setStepMode = usePlanningStore((state) => state.setStepMode);
  const sessionId = usePlanningStore((state) => state.sessionId);

  const [stepLoading, setStepLoading] = React.useState(false);

  const handleRagToggle = (layer: number) => {
    toggleLayerRag(layer);
    // v1: RAG layer toggles are local-only; backend runtime config endpoint was removed.
    void layer;
    void sessionId;
  };

  const handleStepModeToggle = async () => {
    const newStepMode = !stepMode;
    setStepMode(newStepMode);

    if (!sessionId) return;

    setStepLoading(true);

    try {
      await planningApi.updateStepMode(sessionId, { step_mode: newStepMode });
    } catch (error) {
      console.error('[Settings] Failed to sync step mode:', error);
      setStepMode(!newStepMode);
    } finally {
      setStepLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* 标题 */}
      <div className="px-4 py-3 border-b border-slate-100">
        <h3 className="text-sm font-semibold text-slate-800">规划设置</h3>
      </div>

      {/* 设置内容 */}
      <div className="flex-1 overflow-y-auto p-4">
        {/* 执行模式 */}
        <div className="mb-6">
          <h4 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">
            执行模式
          </h4>
          <div className="bg-white rounded-xl border border-slate-200">
            <Toggle
              label="步骤模式"
              description="启用后将在每个层级完成后暂停，等待用户确认"
              enabled={stepMode}
              onToggle={handleStepModeToggle}
              loading={stepLoading}
            />
          </div>
        </div>

        {/* 知识检索配置 */}
        <div className="mb-6">
          <h4 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">
            知识检索配置
          </h4>
          <div className="bg-white rounded-xl border border-slate-200 divide-y divide-slate-100">
            {LAYER_IDS.map((layer) => (
              <LayerToggle
                key={layer}
                layer={layer}
                label={LAYER_VALUE_MAP[layer]}
                enabled={ragLayerConfig[layer] ?? true}
                onToggle={() => handleRagToggle(layer)}
                loading={false}
              />
            ))}
          </div>
          <p className="mt-2 text-xs text-slate-400">
            关闭后，该层级将不使用知识库检索，仅依赖模型生成
          </p>
        </div>
      </div>
    </div>
  );
}