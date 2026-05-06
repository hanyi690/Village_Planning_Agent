'use client';

import type { SpatialLayoutStatistics, FallbackHistoryEntry } from '../types/planning';

// ============================================
// Types
// ============================================

interface TestResultPanelProps {
  statistics?: SpatialLayoutStatistics | null;
  strategyUsed?: string | null;
  fallbackHistory?: FallbackHistoryEntry[];
  warnings?: string[];
  boundaryStats?: {
    area_km2?: number;
    buffer_km?: number;
  } | null;
}

// ============================================
// Sub-components
// ============================================

function StatisticsCard({ statistics }: { statistics: SpatialLayoutStatistics }) {
  return (
    <div className="bg-green-50 border border-green-200 rounded-lg p-3 mb-3">
      <h4 className="font-semibold text-green-800 mb-2">空间布局统计</h4>
      <div className="grid grid-cols-4 gap-2 text-sm text-green-700">
        <div className="bg-white rounded p-2 text-center">
          <div className="text-2xl font-bold">{statistics.zone_count || 0}</div>
          <div className="text-xs text-gray-500">分区</div>
        </div>
        <div className="bg-white rounded p-2 text-center">
          <div className="text-2xl font-bold">{statistics.facility_count || 0}</div>
          <div className="text-xs text-gray-500">设施</div>
        </div>
        <div className="bg-white rounded p-2 text-center">
          <div className="text-2xl font-bold">{statistics.axis_count || 0}</div>
          <div className="text-xs text-gray-500">轴线</div>
        </div>
        <div className="bg-white rounded p-2 text-center">
          <div className="text-2xl font-bold">{statistics.total_area_km2?.toFixed(1) || 0}</div>
          <div className="text-xs text-gray-500">km²</div>
        </div>
      </div>
    </div>
  );
}

function FallbackHistoryCard({
  strategyUsed,
  fallbackHistory,
  boundaryStats,
}: {
  strategyUsed?: string | null;
  fallbackHistory?: FallbackHistoryEntry[];
  boundaryStats?: { area_km2?: number; buffer_km?: number } | null;
}) {
  if (!strategyUsed && (!fallbackHistory || fallbackHistory.length === 0)) {
    return null;
  }

  return (
    <div className="bg-purple-50 border border-purple-200 rounded-lg p-3 mb-3">
      <h4 className="font-semibold text-purple-800 mb-2">边界兜底策略</h4>

      {strategyUsed && (
        <div className="mb-2 flex items-center gap-2">
          <span className="text-sm text-purple-700">最终策略:</span>
          <span className="bg-purple-200 text-purple-800 px-2 py-0.5 rounded text-sm font-medium">
            {strategyUsed}
          </span>
          {boundaryStats && (
            <span className="text-xs text-purple-600">
              (面积: {boundaryStats.area_km2?.toFixed(2) || boundaryStats.buffer_km?.toFixed(1)} km²)
            </span>
          )}
        </div>
      )}

      {fallbackHistory && fallbackHistory.length > 0 && (
        <div className="mt-2">
          <span className="text-sm text-purple-700">降级路径:</span>
          <div className="mt-1 flex flex-wrap gap-1">
            {fallbackHistory.map((entry, idx) => (
              <div
                key={idx}
                className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${
                  entry.success
                    ? 'bg-green-100 text-green-700 border border-green-200'
                    : 'bg-red-100 text-red-700 border border-red-200'
                }`}
              >
                <span className="font-medium">{entry.strategy}</span>
                <span>{entry.success ? '✓' : '✗'}</span>
                {!entry.success && (
                  <span className="text-xs opacity-70">{entry.reason}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function WarningsCard({ warnings }: { warnings?: string[] }) {
  if (!warnings || warnings.length === 0) {
    return null;
  }

  return (
    <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 mb-3">
      <h4 className="font-semibold text-yellow-800 mb-2">警告信息</h4>
      <ul className="text-sm text-yellow-700 list-disc pl-4">
        {warnings.map((warning, idx) => (
          <li key={idx}>{warning}</li>
        ))}
      </ul>
    </div>
  );
}

// ============================================
// Main Component
// ============================================

export default function TestResultPanel({
  statistics,
  strategyUsed,
  fallbackHistory,
  warnings,
  boundaryStats,
}: TestResultPanelProps) {
  const hasResults = statistics || strategyUsed || (fallbackHistory && fallbackHistory.length > 0);

  if (!hasResults) {
    return (
      <div className="bg-gray-100 rounded-lg p-3 text-center text-gray-500 text-sm">
        点击上方测试按钮查看结果
      </div>
    );
  }

  return (
    <div className="space-y-0">
      {statistics && <StatisticsCard statistics={statistics} />}
      <FallbackHistoryCard
        strategyUsed={strategyUsed}
        fallbackHistory={fallbackHistory}
        boundaryStats={boundaryStats}
      />
      <WarningsCard warnings={warnings} />
    </div>
  );
}