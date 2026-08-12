'use client';

import React from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCheck, faSpinner } from '@fortawesome/free-solid-svg-icons';

import type { PlanningBootstrapStep } from '@/features/planning/hooks/usePlanningBootstrapStage';

interface PlanningBootstrapPanelProps {
  headline: string;
  steps: PlanningBootstrapStep[];
  compact?: boolean;
}

export default function PlanningBootstrapPanel({
  headline,
  steps,
  compact = false,
}: PlanningBootstrapPanelProps) {
  const activeStep = steps.find((step) => step.active) ?? steps[steps.length - 1];

  if (compact) {
    return (
      <div className="flex min-h-[200px] flex-1 items-center justify-center px-4 py-6">
        <div className="w-full max-w-md rounded-2xl border border-[#dcebe4] bg-white p-4 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#e8f5ef]">
              <FontAwesomeIcon icon={faSpinner} spin className="text-[#2d8c6d]" style={{ width: 16, height: 16 }} />
            </div>
            <div className="min-w-0">
              <p className="text-[14px] font-semibold text-[#244c40]">{headline}</p>
              <p className="mt-0.5 text-[12px] text-[#78968b]">{activeStep?.detail}</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-[320px] flex-1 items-center justify-center px-4 py-8">
      <div className="w-full max-w-xl rounded-2xl border border-[#dcebe4] bg-gradient-to-b from-white to-[#f7fbf9] p-6 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#e8f5ef] text-[#2d8c6d]">
            <FontAwesomeIcon icon={faSpinner} spin style={{ width: 20, height: 20 }} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#7da396]">Planning Bootstrap</p>
            <h3 className="mt-1 text-[20px] font-bold text-[#244c40]">{headline}</h3>
            <p className="mt-2 text-[13px] leading-6 text-[#6d8f82]">
              规划任务已提交，系统正在按步骤完成初始化。完成后将自动进入 L1/L2/L3 分层分析。
            </p>
          </div>
        </div>

        <ol className="mt-6 space-y-3">
          {steps.map((step, index) => (
            <li
              key={step.id}
              className={`flex items-start gap-3 rounded-xl border px-3 py-3 transition-colors ${
                step.active
                  ? 'border-[#b9e3d0] bg-[#f0faf5]'
                  : step.done
                    ? 'border-[#e3f1eb] bg-white'
                    : 'border-[#edf4f0] bg-white/70'
              }`}
            >
              <div
                className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${
                  step.done
                    ? 'bg-[#3fb288] text-white'
                    : step.active
                      ? 'bg-[#dff3ea] text-[#2d8c6d]'
                      : 'bg-[#eef4f0] text-[#9ab2a8]'
                }`}
              >
                {step.done ? (
                  <FontAwesomeIcon icon={faCheck} style={{ width: 12, height: 12 }} />
                ) : step.active ? (
                  <FontAwesomeIcon icon={faSpinner} spin style={{ width: 12, height: 12 }} />
                ) : (
                  index + 1
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className={`text-[13px] font-semibold ${step.active || step.done ? 'text-[#244c40]' : 'text-[#8aa59a]'}`}>
                  {step.label}
                </p>
                <p className={`mt-0.5 text-[12px] leading-5 ${step.active ? 'text-[#5d7f72]' : 'text-[#9ab2a8]'}`}>
                  {step.detail}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
