'use client';

import React from 'react';

import { usePlanningStore, usePlanningActions } from '../../store';
import {
  useStatus,
  useIsPaused,
  useMessages,
  useCurrentLayer,
  useCascadeChain,
  useReports,
  useDimensionProgressAll,
  useApprovalActions,
} from '../../hooks';
import MessagePanel from '../MessagePanel';
import ChatInput from '../ChatInput';
import ReviewPanel from '../chat/ReviewPanel';
import CascadePanel from '../CascadePanel';
import VillageInputForm from '../VillageInputForm';
import { LAYER_VALUE_MAP, LAYER_IDS, NAV_KEYS } from '@/features/planning/constants';
import MarkdownRenderer from '../ui/MarkdownRenderer';

export default function FocusArea() {
  const selectedNavigationKey = usePlanningStore((state) => state.selectedNavigationKey);
  const setSelectedNavigationKey = usePlanningStore((state) => state.setSelectedNavigationKey);
  const status = useStatus();
  const isPaused = useIsPaused();
  const messages = useMessages();
  const currentLayer = useCurrentLayer();
  const cascadeChain = useCascadeChain();
  const reports = useReports();
  const dimensionProgress = useDimensionProgressAll();
  const { sendChatMessage, startPlanning } = usePlanningActions();
  const { approve, isSubmitting } = useApprovalActions();

  const handleChatClose = () => setSelectedNavigationKey(NAV_KEYS.OVERVIEW);

  if ((status as string) === 'idle') {
    return (
      <div className="flex-1 h-full bg-slate-50">
        <VillageInputForm
          onSubmit={(data) =>
            startPlanning({
              projectName: data.projectName,
              villageData: data.villageData || '',
              villageName: data.projectName,
              taskDescription: data.taskDescription,
              constraints: data.constraints,
              villageDataFiles: data.villageDataFiles,
              taskFiles: data.taskFiles,
              constraintFiles: data.constraintFiles,
            })
          }
        />
      </div>
    );
  }

  if (cascadeChain && !selectedNavigationKey) {
    return (
      <div className="flex-1 h-full flex flex-col bg-white">
        <div className="flex-1 overflow-y-auto p-6">
          <CascadePanel trigger={cascadeChain.trigger} impacted={cascadeChain.impacted} />
        </div>
        <div className="h-[56px] border-t border-slate-200">
          <ChatInput disabled={false} onSend={(msg) => sendChatMessage(msg)} />
        </div>
      </div>
    );
  }

  if (selectedNavigationKey === NAV_KEYS.CHAT) {
    return (
      <div className="flex-1 h-full flex flex-col bg-white">
        <div className="flex-1 overflow-y-auto">
          <MessagePanel messages={messages} onClose={handleChatClose} />
        </div>
        <div className="h-[56px] border-t border-slate-200">
          <ChatInput
            disabled={(status as string) === 'idle'}
            onSend={(msg) => sendChatMessage(msg)}
          />
        </div>
      </div>
    );
  }

  if (selectedNavigationKey === NAV_KEYS.APPROVAL && isPaused && currentLayer) {
    return (
      <div className="flex-1 h-full flex flex-col items-center justify-center bg-white p-4 lg:p-6">
        <ReviewPanel layer={currentLayer} onApprove={approve} isSubmitting={isSubmitting} />
      </div>
    );
  }

  if (selectedNavigationKey?.startsWith('dim:')) {
    const dimKey = selectedNavigationKey.slice(4);
    const layer = parseInt(dimKey.split('_')[0], 10);
    const layerReports = reports[`layer${layer}` as 'layer1' | 'layer2' | 'layer3'] || {};
    const dimKeyPart = dimKey.split('_').slice(1).join('_');
    const reportContent = layerReports[dimKeyPart] || '';

    return (
      <div className="flex-1 h-full overflow-y-auto bg-white p-4 lg:p-6">
        <div className="max-w-3xl lg:max-w-4xl mx-auto">
          <h2 className="text-xl font-semibold text-slate-800 mb-4">{dimKeyPart} 分析报告</h2>
          {reportContent ? (
            <MarkdownRenderer content={reportContent} />
          ) : (
            <div className="text-slate-400 text-sm">该维度尚未生成报告。</div>
          )}
        </div>
      </div>
    );
  }

  // Default: overview dashboard
  const allDimensionCount = Object.keys(dimensionProgress).length;

  return (
    <div className="flex-1 h-full overflow-y-auto bg-slate-50 p-4 lg:p-6">
      <div className="max-w-3xl lg:max-w-4xl mx-auto">
        <h2 className="text-xl font-semibold text-slate-800 mb-2">规划总览</h2>
        <p className="text-base text-slate-500 mb-4">
          当前阶段: {currentLayer ? `Layer ${currentLayer}` : '初始化中'} | 维度数: {allDimensionCount}
        </p>

        <div className="space-y-3">
          {LAYER_IDS.map((layer) => {
            const layerReports = reports[`layer${layer}`] || {};
            const reportKeys = Object.keys(layerReports);
            if (reportKeys.length === 0) return null;
            return (
              <div key={layer} className="bg-white rounded-xl border border-slate-200 p-4">
                <h3 className="text-base font-medium text-slate-700 mb-2">
                  Layer {layer}: {LAYER_VALUE_MAP[layer]}
                </h3>
                <div className="text-sm text-slate-500">{reportKeys.length} 份报告完成</div>
              </div>
            );
          })}
        </div>

        <div className="mt-4 flex gap-2">
          <button
            onClick={() => setSelectedNavigationKey(NAV_KEYS.CHAT)}
            className="px-5 py-2.5 rounded-lg bg-emerald-50 text-emerald-700 text-base hover:bg-emerald-100 transition-colors"
          >
            查看对话
          </button>
          {isPaused && (
            <button
              onClick={() => setSelectedNavigationKey(NAV_KEYS.APPROVAL)}
              className="px-5 py-2.5 rounded-lg bg-amber-50 text-amber-700 text-base hover:bg-amber-100 transition-colors"
            >
              去审批
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
