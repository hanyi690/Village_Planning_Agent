'use client';

export interface LayerStatusItem {
  layer_key: string;
  label: string;
  tier: string;
  present: boolean;
  feature_count: number;
  source: string;
}

export interface LayerCompleteness {
  score_pct: number;
  critical_missing: string[];
  recommended_missing: string[];
  layers: LayerStatusItem[];
  summary: string;
}

const TIER_LABEL: Record<string, string> = {
  critical: '关键',
  recommended: '推荐',
  optional: '可选',
};

export default function LayerCompletenessCard({
  completeness,
}: {
  completeness: LayerCompleteness;
}) {
  const scoreColor =
    completeness.score_pct >= 85
      ? 'text-[#168a65]'
      : completeness.score_pct >= 70
        ? 'text-[#b45309]'
        : 'text-[#be123c]';

  return (
    <div className="rounded-xl border border-[#e1eee8] bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h4 className="text-[13px] font-semibold text-[#264f43]">图层完整度</h4>
        <span className={`text-lg font-semibold tabular-nums ${scoreColor}`}>
          {completeness.score_pct.toFixed(0)}%
        </span>
      </div>
      <p className="mt-1 text-[11px] text-[#8aa59a]">{completeness.summary}</p>
      <div className="mt-3 space-y-1">
        {completeness.layers.map((layer) => (
          <div
            key={layer.layer_key}
            className="flex items-center justify-between gap-2 rounded-lg bg-[#f6fbf8] px-2.5 py-1.5 text-[11px]"
          >
            <span className="min-w-0 truncate text-[#264f43]">
              <span className="mr-1.5 text-[#9ab2a8]">{TIER_LABEL[layer.tier] ?? layer.tier}</span>
              {layer.label}
            </span>
            <span className="shrink-0 tabular-nums text-[#6d8f82]">
              {layer.present ? `✓ ${layer.feature_count}` : '缺失'}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
