'use client';

/**
 * ValidationPanel - GIS 布局验证反馈组件
 *
 * 展示布局验证结果：概览统计 + 冲突详情。
 * 概览 tab 显示 4 个统计卡片，详情 tab 显示按检查分组的违规列表。
 */

import { useState } from 'react';
import type {
  LayoutValidationResult,
  LayoutValidationCheck,
  LayoutValidationViolation,
  LayoutValidationDetail,
} from '@/features/gis-test/api/gis-test-api';

// ============================================
// Types
// ============================================

interface ValidationPanelProps {
  /** Validation result from layout-validate API */
  result: LayoutValidationResult | null;
  /** Whether validation is in progress */
  loading?: boolean;
  /** Callback when user clicks a violation to locate on map */
  onViolationClick?: (violation: LayoutValidationViolation) => void;
}

type TabKey = 'overview' | 'details';

// ============================================
// Sub-components
// ============================================

function StatusBadge({ status }: { status: 'pass' | 'fail' | 'warning' }) {
  const config = {
    pass: { bg: 'bg-emerald-100', text: 'text-emerald-700', label: '通过' },
    fail: { bg: 'bg-red-100', text: 'text-red-700', label: '未通过' },
    warning: { bg: 'bg-amber-100', text: 'text-amber-700', label: '警告' },
  }[status];

  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${config.bg} ${config.text}`}>
      {config.label}
    </span>
  );
}

function StatCard({ value, label, color }: { value: number | string; label: string; color: string }) {
  return (
    <div className="bg-white rounded p-2 text-center">
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  );
}

function OverviewTab({
  validation,
  checks,
  zoneAreas,
}: {
  validation: LayoutValidationDetail;
  checks?: LayoutValidationCheck[];
  zoneAreas?: Record<string, number>;
}) {
  const passedChecks = checks?.filter(c => c.passed).length ?? 0;
  const totalChecks = checks?.length ?? 0;
  const warningCount = validation.warnings?.length ?? 0;
  const totalArea = zoneAreas ? Object.values(zoneAreas).reduce((s, v) => s + v, 0) : 0;

  return (
    <div className="space-y-3">
      {/* Overall status */}
      <div className="flex items-center justify-between px-1">
        <span className="text-sm font-medium text-gray-700">验证状态</span>
        <StatusBadge status={validation.status} />
      </div>

      {/* 4 stat cards */}
      <div className="grid grid-cols-4 gap-2 text-sm">
        <StatCard
          value={totalChecks > 0 ? `${passedChecks}/${totalChecks}` : '-'}
          label="检查通过"
          color="text-emerald-600"
        />
        <StatCard
          value={warningCount}
          label="警告"
          color="text-amber-600"
        />
        <StatCard
          value={validation.total_violations}
          label="违规"
          color="text-red-600"
        />
        <StatCard
          value={totalArea > 0 ? totalArea.toFixed(1) : '-'}
          label="总面积(ha)"
          color="text-blue-600"
        />
      </div>

      {/* Zone areas breakdown */}
      {zoneAreas && Object.keys(zoneAreas).length > 0 && (
        <div className="bg-slate-50 rounded-lg p-2">
          <div className="text-xs font-medium text-gray-500 mb-1">分区面积</div>
          <div className="space-y-1">
            {Object.entries(zoneAreas).map(([zone, area]) => (
              <div key={zone} className="flex justify-between text-xs">
                <span className="text-gray-600">{zone}</span>
                <span className="text-gray-800 font-medium">{area.toFixed(2)} ha</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Warnings list */}
      {validation.warnings && validation.warnings.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-2">
          <div className="text-xs font-medium text-amber-700 mb-1">警告</div>
          <ul className="text-xs text-amber-600 list-disc pl-4 space-y-0.5">
            {validation.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function SeverityIcon({ severity }: { severity: 'error' | 'warning' }) {
  if (severity === 'error') {
    return <span className="text-red-500 text-xs">&#10007;</span>;
  }
  return <span className="text-amber-500 text-xs">&#9888;</span>;
}

function DetailsTab({
  checks,
  violations,
  onViolationClick,
}: {
  checks?: LayoutValidationCheck[];
  violations?: LayoutValidationViolation[];
  onViolationClick?: (v: LayoutValidationViolation) => void;
}) {
  // Prefer structured checks; fall back to flat violations
  if (checks && checks.length > 0) {
    return (
      <div className="space-y-2">
        {checks.map((check, idx) => (
          <div
            key={idx}
            className={`rounded-lg border p-2 ${
              check.passed
                ? 'bg-emerald-50 border-emerald-200'
                : 'bg-red-50 border-red-200'
            }`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-gray-700">{check.name}</span>
              <div className="flex items-center gap-1.5">
                {check.violation_count > 0 && (
                  <span className="text-xs text-red-600 font-medium">
                    {check.violation_count} 违规
                  </span>
                )}
                <StatusBadge status={check.passed ? 'pass' : 'fail'} />
              </div>
            </div>
            {check.violations.length > 0 && (
              <div className="space-y-1 mt-1">
                {check.violations.map((v, vi) => (
                  <ViolationRow
                    key={vi}
                    violation={v}
                    onClick={onViolationClick}
                  />
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  }

  // Flat violations list
  if (violations && violations.length > 0) {
    return (
      <div className="space-y-1">
        {violations.map((v, i) => (
          <ViolationRow key={i} violation={v} onClick={onViolationClick} />
        ))}
      </div>
    );
  }

  return (
    <div className="text-center text-sm text-gray-400 py-4">
      无违规详情
    </div>
  );
}

function ViolationRow({
  violation,
  onClick,
}: {
  violation: LayoutValidationViolation;
  onClick?: (v: LayoutValidationViolation) => void;
}) {
  return (
    <div
      className={`flex items-start gap-1.5 text-xs px-2 py-1 rounded ${
        violation.severity === 'error'
          ? 'bg-red-100 text-red-700'
          : 'bg-amber-100 text-amber-700'
      } ${onClick ? 'cursor-pointer hover:opacity-80' : ''}`}
      onClick={() => onClick?.(violation)}
    >
      <SeverityIcon severity={violation.severity as 'error' | 'warning'} />
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{violation.check}</div>
        <div className="opacity-80 truncate">{violation.message}</div>
      </div>
    </div>
  );
}

// ============================================
// Main Component
// ============================================

export default function ValidationPanel({
  result,
  loading = false,
  onViolationClick,
}: ValidationPanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('overview');

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="w-5 h-5 border-2 border-[#0ea5e9] border-t-transparent rounded-full animate-spin" />
        <span className="ml-2 text-sm text-gray-500">验证中...</span>
      </div>
    );
  }

  if (!result || !result.validation) {
    return (
      <div className="bg-gray-50 rounded-lg p-3 text-center text-gray-400 text-sm">
        暂无验证结果
      </div>
    );
  }

  const validation = result.validation as LayoutValidationDetail;
  const { checks, zone_areas } = result;

  return (
    <div className="space-y-2">
      {/* Tab bar */}
      <div className="flex border-b border-slate-200">
        {(['overview', 'details'] as TabKey[]).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
              activeTab === tab
                ? 'text-[#0ea5e9] border-b-2 border-[#0ea5e9]'
                : 'text-gray-400 hover:text-gray-600'
            }`}
          >
            {tab === 'overview' ? '概览' : '冲突详情'}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'overview' ? (
        <OverviewTab
          validation={validation}
          checks={checks}
          zoneAreas={zone_areas}
        />
      ) : (
        <DetailsTab
          checks={checks}
          violations={validation.violations}
          onViolationClick={onViolationClick}
        />
      )}
    </div>
  );
}
