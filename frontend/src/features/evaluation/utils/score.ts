export function pct(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export type ScoreTier = 'excellent' | 'good' | 'fair' | 'poor';

export function scoreTier(score: number): ScoreTier {
  if (score >= 0.85) return 'excellent';
  if (score >= 0.7) return 'good';
  if (score >= 0.55) return 'fair';
  return 'poor';
}

export const TIER_STYLES: Record<
  ScoreTier,
  { text: string; bg: string; ring: string; bar: string }
> = {
  excellent: {
    text: 'text-[#1a7a5c]',
    bg: 'bg-[#e8f7f0]',
    ring: 'stroke-[#3fb288]',
    bar: 'bg-[#3fb288]',
  },
  good: {
    text: 'text-[#2d8c6d]',
    bg: 'bg-[#edf8f3]',
    ring: 'stroke-[#45b88b]',
    bar: 'bg-[#45b88b]',
  },
  fair: {
    text: 'text-[#b45309]',
    bg: 'bg-[#fff7ed]',
    ring: 'stroke-[#f59e0b]',
    bar: 'bg-[#f59e0b]',
  },
  poor: {
    text: 'text-[#be123c]',
    bg: 'bg-[#fff1f2]',
    ring: 'stroke-[#f43f5e]',
    bar: 'bg-[#f43f5e]',
  },
};

export function tierLabel(tier: ScoreTier): string {
  switch (tier) {
    case 'excellent':
      return '优秀';
    case 'good':
      return '良好';
    case 'fair':
      return '一般';
    case 'poor':
      return '待改进';
  }
}
