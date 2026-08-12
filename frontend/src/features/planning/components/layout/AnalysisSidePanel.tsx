'use client';

import React, { useEffect, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faCheck,
  faChevronDown,
  faExchangeAlt,
  faLink,
  faMap,
  faPauseCircle,
  faWrench,
  faComments,
  faClipboardCheck,
} from '@fortawesome/free-solid-svg-icons';

import { getDimensionName } from '@/features/planning/config/dimensions';
import { cn } from '@/features/planning/utils/cn';

const REVISION_LAYER_LABELS: Record<number, string> = {
  1: 'L1 现状分析',
  2: 'L2 规划思路',
  3: 'L3 详细规划',
};

type SidePanelTab = 'chat' | 'review' | 'tools';

interface RagDocument {
  title: string;
  snippet?: string;
  score?: number;
}

interface AnalysisSidePanelProps {
  reviewPanelRef: React.RefObject<HTMLDivElement>;
  reviewLayer: number | null;
  showReview: boolean;
  highlightReviewBox: boolean;
  feedback: string;
  onFeedbackChange: (value: string) => void;
  onFeedbackKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onApprove: () => void;
  onSubmitRevision: () => void;
  isSubmitting: boolean;
  primaryBtnClass: string;
  secondaryBtnClass: string;
  allCompletedDimsCount: number;
  allCompletedDimsByLayer: Array<{ layer: number; dims: string[] }>;
  selectedDimensions: string[];
  onToggleDimension: (dimKey: string) => void;
  showCompare?: boolean;
  onCompare?: () => void;
  ragDocuments?: RagDocument[];
  ragQuery?: string;
  onOpenRagDoc?: (index: number) => void;
  showGisTrigger?: boolean;
  gisBusy?: boolean;
  onTriggerGis?: () => void;
  completedDimsCount: number;
  totalDims: number;
  chatPanel: React.ReactNode;
  sessionConnected?: boolean;
  /** Increment to auto-focus the review tab (pause for approval or revision draft). */
  autoFocusReviewKey?: number;
}

export default function AnalysisSidePanel({
  reviewPanelRef,
  reviewLayer,
  showReview,
  highlightReviewBox,
  feedback,
  onFeedbackChange,
  onFeedbackKeyDown,
  onApprove,
  onSubmitRevision,
  isSubmitting,
  primaryBtnClass,
  secondaryBtnClass,
  allCompletedDimsCount,
  allCompletedDimsByLayer,
  selectedDimensions,
  onToggleDimension,
  showCompare,
  onCompare,
  ragDocuments,
  ragQuery,
  onOpenRagDoc,
  showGisTrigger,
  gisBusy,
  onTriggerGis,
  completedDimsCount,
  totalDims,
  chatPanel,
  sessionConnected,
  autoFocusReviewKey = 0,
}: AnalysisSidePanelProps) {
  const [activeTab, setActiveTab] = useState<SidePanelTab>('chat');
  const [revisionDimsExpanded, setRevisionDimsExpanded] = useState(true);

  useEffect(() => {
    if (autoFocusReviewKey > 0) {
      setActiveTab('review');
    }
  }, [autoFocusReviewKey]);

  const tabs: Array<{
    id: SidePanelTab;
    label: string;
    icon: typeof faComments;
    badge?: string | number;
  }> = [
    { id: 'chat', label: '问答', icon: faComments },
    {
      id: 'review',
      label: '审查',
      icon: faClipboardCheck,
      badge: showReview ? '!' : selectedDimensions.length > 0 ? selectedDimensions.length : undefined,
    },
    { id: 'tools', label: '工具', icon: faWrench },
  ];

  return (
    <aside
      ref={reviewPanelRef}
      className="flex w-[320px] shrink-0 flex-col overflow-hidden border-l border-[#e5efe9] bg-[#fafcfb]"
    >
      <div className="flex shrink-0 border-b border-[#e5efe9] bg-white px-1 pt-1">
        {tabs.map((tab) => {
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'relative flex flex-1 flex-col items-center gap-0.5 rounded-t-lg px-2 py-2 text-[12px] font-medium transition-colors',
                active
                  ? 'bg-[#f3f8f5] text-[#1f7a59]'
                  : 'text-[#5d7f72] hover:bg-[#f6fbf8] hover:text-[#2d8c6d]',
              )}
            >
              <FontAwesomeIcon icon={tab.icon} style={{ width: 12, height: 12 }} />
              <span>{tab.label}</span>
              {tab.badge !== undefined && (
                <span className="absolute right-2 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-[#3fb288] px-1 text-[9px] font-semibold text-white">
                  {tab.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        {activeTab === 'chat' && (
          <div className="flex h-full min-h-0 flex-col">
            <div className="flex shrink-0 items-center justify-between border-b border-[#e5efe9] px-3 py-2">
              <span className="text-[13px] font-semibold text-[#244c40]">智能体问答</span>
              <span className="text-[11px] text-[#9ab2a8]">{sessionConnected ? '已连接' : '待启动'}</span>
            </div>
            <div className="flex min-h-0 flex-1 flex-col">
              {chatPanel}
            </div>
          </div>
        )}

        {activeTab === 'review' && (
          <div className="h-full overflow-y-auto p-3 space-y-3">
            {showReview && reviewLayer ? (
              <>
                <div className="rounded-xl border border-[#f0ddb8] bg-[#fff8eb] px-3 py-3">
                  <div className="flex items-start gap-2">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#ffe8bf] text-[#b7791f]">
                      <FontAwesomeIcon icon={faPauseCircle} style={{ width: 15, height: 15 }} />
                    </div>
                    <div className="min-w-0">
                      <div className="text-[11px] font-semibold text-[#b7791f]">审查状态</div>
                      <div className="mt-0.5 text-[14px] font-semibold text-[#244c40]">Layer {reviewLayer} 已暂停</div>
                      <div className="mt-1 text-[12px] leading-5 text-[#8a7350]">请审批通过，或填写修订意见后提交</div>
                    </div>
                  </div>
                </div>

                <div>
                  <div className="mb-2 text-[12px] font-semibold text-[#5d7f72]">修订意见</div>
                  <div
                    className={cn(
                      'rounded-xl border bg-white p-3 transition-shadow',
                      highlightReviewBox ? 'border-[#3fb288] ring-2 ring-[#b8e5d2]' : 'border-[#dcebe4]',
                    )}
                  >
                    <textarea
                      value={feedback}
                      onChange={(event) => {
                        onFeedbackChange(event.target.value);
                        event.target.style.height = 'auto';
                        event.target.style.height = `${event.target.scrollHeight}px`;
                      }}
                      onKeyDown={onFeedbackKeyDown}
                      placeholder="描述需要修改的内容…"
                      rows={4}
                      className="min-h-[96px] w-full resize-none bg-transparent text-[13px] leading-6 text-[#244c40] placeholder-[#9ab2a8] focus:outline-none"
                    />
                    <div className="mt-1 text-[11px] text-[#9ab2a8]">Enter 提交 · Shift+Enter 换行</div>
                  </div>
                </div>

                {allCompletedDimsCount > 0 && (
                  <div className="rounded-xl border border-[#dcebe4] bg-white overflow-hidden">
                    <button
                      type="button"
                      onClick={() => setRevisionDimsExpanded((open) => !open)}
                      className="flex w-full items-center justify-between px-3 py-2.5 text-left hover:bg-[#f6fbf8]"
                    >
                      <span className="text-[12px] font-semibold text-[#244c40]">修订维度目录</span>
                      <span className="flex items-center gap-2 text-[11px] text-[#78968b]">
                        {selectedDimensions.length > 0 ? `已选 ${selectedDimensions.length}` : '按 L1/L2/L3 勾选'}
                        <FontAwesomeIcon
                          icon={faChevronDown}
                          className={cn('transition-transform', revisionDimsExpanded && 'rotate-180')}
                          style={{ width: 10, height: 10 }}
                        />
                      </span>
                    </button>
                    {revisionDimsExpanded && (
                      <div className="max-h-72 space-y-2 overflow-y-auto border-t border-[#eef4f0] p-2">
                        {allCompletedDimsByLayer.map((group) => (
                          <div key={group.layer} className="rounded-lg border border-[#eef4f0] bg-[#fafcfb] p-2">
                            <div className="mb-1.5 flex items-center justify-between px-0.5">
                              <span className="text-[12px] font-semibold text-[#2d8c6d]">
                                {REVISION_LAYER_LABELS[group.layer] ?? `Layer ${group.layer}`}
                              </span>
                              <span className="text-[11px] text-[#9ab2a8]">{group.dims.length} 项</span>
                            </div>
                            <div className="space-y-1">
                              {group.dims.map((dimKey) => (
                                <label
                                  key={dimKey}
                                  className={cn(
                                    'flex cursor-pointer items-start gap-2 rounded-md border px-2.5 py-2 text-[12px] leading-5',
                                    selectedDimensions.includes(dimKey)
                                      ? 'border-[#3fb288] bg-[#e8f5ef] text-[#1f7a59]'
                                      : 'border-transparent text-[#5d7f72] hover:border-[#e5efe9] hover:bg-white',
                                  )}
                                >
                                  <input
                                    type="checkbox"
                                    className="mt-0.5 accent-[#3fb288]"
                                    checked={selectedDimensions.includes(dimKey)}
                                    onChange={() => onToggleDimension(dimKey)}
                                  />
                                  <span className="min-w-0 flex-1">{getDimensionName(dimKey)}</span>
                                </label>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                    <p className="border-t border-[#eef4f0] px-3 py-2 text-[11px] leading-5 text-[#9ab2a8]">
                      未勾选时按系统级联修订；勾选后仅重跑所选维度及下游依赖。
                    </p>
                  </div>
                )}

                <div className="space-y-2">
                  <button
                    type="button"
                    onClick={onApprove}
                    disabled={isSubmitting}
                    className={cn(
                      'flex w-full items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[13px] font-semibold text-white disabled:opacity-50',
                      primaryBtnClass,
                    )}
                  >
                    <FontAwesomeIcon icon={faCheck} style={{ width: 13, height: 13 }} />
                    批准继续
                  </button>
                  <button
                    type="button"
                    onClick={onSubmitRevision}
                    disabled={isSubmitting}
                    className={cn(
                      'w-full rounded-xl border px-3 py-2.5 text-[13px] font-medium disabled:opacity-50',
                      secondaryBtnClass,
                    )}
                  >
                    提交修订
                  </button>
                </div>
              </>
            ) : (
              <div className="rounded-xl border border-dashed border-[#dcebe4] bg-white px-4 py-8 text-center">
                <div className="text-[13px] font-medium text-[#5d7f72]">当前无需审查</div>
                <p className="mt-2 text-[12px] leading-5 text-[#9ab2a8]">
                  规划暂停并进入审批阶段时，可在此填写修订意见、勾选维度并提交。
                </p>
              </div>
            )}
          </div>
        )}

        {activeTab === 'tools' && (
          <div className="h-full overflow-y-auto p-3 space-y-3">
            <div className="rounded-xl border border-[#dcebe4] bg-white px-3 py-3">
              <div className="text-[12px] font-semibold text-[#9ab2a8]">整体进度</div>
              <div className="mt-1 text-[22px] font-semibold tabular-nums text-[#1f7a59]">
                {completedDimsCount}
                <span className="text-[13px] font-normal text-[#9ab2a8]"> / {totalDims}</span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#e7f2ed]">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-[#6fd0a8] to-[#3fb288]"
                  style={{ width: `${totalDims > 0 ? Math.round((completedDimsCount / totalDims) * 100) : 0}%` }}
                />
              </div>
            </div>

            {showGisTrigger && onTriggerGis && (
              <div className="rounded-xl border border-[#c9e8db] bg-[#f3fbf7] p-3">
                <div className="text-[12px] font-semibold text-[#2d8c6d]">空间布局</div>
                <p className="mt-1 text-[12px] leading-5 text-[#5d7f72]">L3 已完成，可生成 GIS 成果</p>
                <button
                  type="button"
                  onClick={onTriggerGis}
                  disabled={gisBusy}
                  className={cn(
                    'mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg px-3 py-2.5 text-[12px] font-medium text-white disabled:opacity-50',
                    primaryBtnClass,
                  )}
                >
                  <FontAwesomeIcon icon={faMap} style={{ width: 12, height: 12 }} />
                  {gisBusy ? '生成中…' : '确认生成 GIS'}
                </button>
              </div>
            )}

            {showCompare && onCompare && (
              <div className="rounded-xl border border-[#dcebe4] bg-white p-3">
                <div className="text-[12px] font-semibold text-[#5d7f72]">报告对比</div>
                <p className="mt-1 text-[12px] text-[#9ab2a8]">与历史会话或版本进行并排比较</p>
                <button
                  type="button"
                  onClick={onCompare}
                  className={cn(
                    'mt-2 flex w-full items-center justify-center gap-2 rounded-lg border px-3 py-2.5 text-[12px] font-medium',
                    secondaryBtnClass,
                  )}
                >
                  <FontAwesomeIcon icon={faExchangeAlt} style={{ width: 12, height: 12 }} />
                  打开对比
                </button>
              </div>
            )}

            {ragDocuments && ragDocuments.length > 0 && (
              <div className="rounded-xl border border-[#dcebe4] bg-white p-3">
                <div className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold text-[#5d7f72]">
                  <FontAwesomeIcon icon={faLink} className="text-[#3fb288]" style={{ width: 11, height: 11 }} />
                  知识来源
                  <span className="rounded-full bg-[#e8f5ef] px-1.5 text-[11px] text-[#1f7a59]">{ragDocuments.length}</span>
                </div>
                {ragQuery && (
                  <div className="mb-2 rounded-lg border border-[#eef4f0] bg-[#fafcfb] px-2.5 py-2 text-[11px] text-[#78968b]">
                    检索词：<span className="text-[#2d8c6d]">{ragQuery}</span>
                  </div>
                )}
                <div className="space-y-1.5">
                  {ragDocuments.slice(0, 5).map((doc, index) => (
                    <button
                      key={`${doc.title}-${index}`}
                      type="button"
                      onClick={() => onOpenRagDoc?.(index)}
                      className="w-full rounded-lg border border-[#eef4f0] bg-[#fafcfb] px-2.5 py-2 text-left hover:border-[#9fd4bc]"
                    >
                      <div className="text-[12px] font-medium text-[#244c40] line-clamp-2">{doc.title}</div>
                      {doc.snippet && (
                        <div className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-[#78968b]">{doc.snippet}</div>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
