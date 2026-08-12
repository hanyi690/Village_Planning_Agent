'use client';

import { usePlanningStore } from '@/features/planning/store';

const BANNER_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  offline_template: {
    bg: 'bg-amber-50 border-amber-200',
    text: 'text-amber-900',
    label: '离线模板',
  },
  connection_error: {
    bg: 'bg-orange-50 border-orange-200',
    text: 'text-orange-900',
    label: '连接失败',
  },
  arrears: {
    bg: 'bg-red-50 border-red-200',
    text: 'text-red-900',
    label: '账户异常',
  },
  api_error: {
    bg: 'bg-red-50 border-red-200',
    text: 'text-red-900',
    label: 'API 错误',
  },
};

export default function LlmStatusBanner() {
  const status = usePlanningStore((state) => state.llmHealthStatus);
  const message = usePlanningStore((state) => state.llmHealthMessage);
  const dismiss = usePlanningStore((state) => state.dismissLlmHealthBanner);

  if (!status || !message) return null;

  const style = BANNER_STYLES[status] ?? BANNER_STYLES.api_error;

  return (
    <div
      className={`flex shrink-0 items-start justify-between gap-3 rounded-xl border px-4 py-2.5 text-[12px] ${style.bg}`}
      role="status"
    >
      <div className={`min-w-0 ${style.text}`}>
        <span className="font-semibold">大模型 {style.label}：</span>
        <span>{message}</span>
      </div>
      <button
        type="button"
        onClick={dismiss}
        className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-medium hover:bg-black/5 ${style.text}`}
      >
        知道了
      </button>
    </div>
  );
}
