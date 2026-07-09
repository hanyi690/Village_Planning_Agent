'use client';

import { useState } from 'react';
import type {
  PipelineTrace,
  ParseTrace,
  KGTrace,
  ConflictTrace,
  MIPTrace,
  ValidationLoopTrace,
} from '../../store/planningStore';

// ============================================
// Collapsible Section
// ============================================

function Section({
  title,
  timing,
  badge,
  children,
  defaultOpen = false,
}: {
  title: string;
  timing?: string;
  badge?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details open={defaultOpen} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer select-none py-2 px-3 hover:bg-gray-50 flex items-center gap-2 text-sm font-medium">
        <span className={`transition-transform ${open ? 'rotate-90' : ''}`}>&#9654;</span>
        <span>{title}</span>
        {timing && <span className="text-gray-400 text-xs">{timing}</span>}
        {badge && (
          <span className="bg-blue-100 text-blue-700 text-xs px-1.5 py-0.5 rounded">{badge}</span>
        )}
      </summary>
      <div className="pl-6 pr-3 pb-3 text-xs text-gray-700 space-y-1.5">{children}</div>
    </details>
  );
}

function KV({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <span className="text-gray-400 shrink-0 min-w-[100px]">{label}:</span>
      <span className="break-all">{value ?? '—'}</span>
    </div>
  );
}

function CodeBlock({ content, maxHeight = 200 }: { content: string; maxHeight?: number }) {
  const [expanded, setExpanded] = useState(false);
  if (!content) return <span className="text-gray-400">—</span>;
  const truncated = content.length > 500 && !expanded;
  return (
    <div>
      <pre
        className="bg-gray-50 border rounded p-2 overflow-x-auto text-xs whitespace-pre-wrap"
        style={{ maxHeight: expanded ? undefined : maxHeight }}
      >
        {truncated ? content.slice(0, 500) + '...' : content}
      </pre>
      {content.length > 500 && (
        <button
          className="text-blue-500 hover:underline mt-1"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? '收起' : '展开全部'}
        </button>
      )}
    </div>
  );
}

// ============================================
// Parse Section
// ============================================

function ParseSection({ trace }: { trace?: ParseTrace }) {
  if (!trace) return null;
  const timing = trace.timing_ms ? `${(trace.timing_ms / 1000).toFixed(1)}s` : '';
  const badge = trace.llm_model || '';
  return (
    <Section title="文本解析 (parse)" timing={timing} badge={badge}>
      <KV label="Source" value={trace.source} />
      <KV label="Retry count" value={trace.llm_retry_count} />
      <KV label="Anchor confidence" value={trace.anchor_confidence} />
      <KV
        label="Semantic validation"
        value={trace.semantic_validation_passed ? '✓ passed' : '✗ failed'}
      />
      {trace.semantic_violations.length > 0 && (
        <KV label="Violations" value={trace.semantic_violations.join('; ')} />
      )}
      {trace.correction_round && (
        <>
          <KV label="Correction round" value="Yes" />
          {trace.correction_prompt && (
            <div>
              <span className="text-gray-400">Correction prompt:</span>
              <CodeBlock content={trace.correction_prompt} />
            </div>
          )}
        </>
      )}
      {trace.llm_prompt && (
        <div>
          <span className="text-gray-400">Prompt:</span>
          <CodeBlock content={trace.llm_prompt} />
        </div>
      )}
      {trace.llm_response && (
        <div>
          <span className="text-gray-400">Response:</span>
          <CodeBlock content={trace.llm_response} />
        </div>
      )}
    </Section>
  );
}

// ============================================
// KG Section
// ============================================

function KGSection({ trace }: { trace?: KGTrace }) {
  if (!trace || !trace.built) return null;
  const timing = trace.timing_ms ? `${(trace.timing_ms / 1000).toFixed(1)}s` : '';
  const badge = `${trace.parcel_count} parcels, ${trace.triple_count} triples`;
  return (
    <Section title="知识图谱 (kg)" timing={timing} badge={badge}>
      <KV label="Constraint count" value={trace.constraint_count} />
      <KV label="Indicator count" value={trace.indicator_count} />
      <KV label="Adjacency edges" value={trace.adjacency_edge_count} />
      {trace.constraints_detail &&
        Object.keys(trace.constraints_detail).length > 0 && (
          <div>
            <span className="text-gray-400">Constraints:</span>
            <CodeBlock content={JSON.stringify(trace.constraints_detail, null, 2)} />
          </div>
        )}
      {trace.triples_sample && trace.triples_sample.length > 0 && (
        <div>
          <span className="text-gray-400">Triples ({trace.triples_sample.length}):</span>
          <CodeBlock content={JSON.stringify(trace.triples_sample.slice(0, 20), null, 2)} />
        </div>
      )}
    </Section>
  );
}

// ============================================
// Conflict Section
// ============================================

function ConflictSection({ trace }: { trace?: ConflictTrace }) {
  if (!trace) return null;
  const timing = trace.timing_ms ? `${(trace.timing_ms / 1000).toFixed(1)}s` : '';
  const mc = trace.metric_conflicts?.length ?? 0;
  const cv = trace.constraint_violations?.length ?? 0;
  const badge = `${mc} metric, ${cv} constraint`;
  return (
    <Section title="冲突检测 (conflicts)" timing={timing} badge={badge}>
      {trace.metric_conflicts?.map((c, i) => (
        <div key={i} className="bg-yellow-50 border-l-2 border-yellow-400 pl-2 py-1">
          <span className="font-medium">Metric:</span>{' '}
          {String((c as Record<string, unknown>).field ?? '?')} —{' '}
          {String((c as Record<string, unknown>).dim_a ?? '?')} vs{' '}
          {String((c as Record<string, unknown>).dim_b ?? '?')}
        </div>
      ))}
      {trace.constraint_violations?.map((v, i) => (
        <div key={i} className="bg-red-50 border-l-2 border-red-400 pl-2 py-1">
          <span className="font-medium">Constraint:</span>{' '}
          {String((v as Record<string, unknown>).description ?? (v as Record<string, unknown>).constraint_id ?? '?')}
        </div>
      ))}
      {trace.resolution_applied?.map((r, i) => (
        <div key={i} className="bg-green-50 border-l-2 border-green-400 pl-2 py-1">
          <span className="font-medium">Resolution:</span>{' '}
          {String((r as Record<string, unknown>).description ?? '?')}
        </div>
      ))}
    </Section>
  );
}

// ============================================
// MIP Section
// ============================================

function MIPSection({ trace }: { trace?: MIPTrace }) {
  if (!trace) return null;
  const timing = trace.timing_ms ? `${(trace.timing_ms / 1000).toFixed(1)}s` : '';
  const badge = `${trace.solver_status || '?'} ${trace.variable_count} vars`;
  return (
    <Section title="MIP 求解 (mip)" timing={timing} badge={badge}>
      <KV label="Mode" value={trace.mode} />
      <KV label="Objective" value={trace.objective_value?.toFixed(2)} />
      <KV label="Binary vars" value={trace.binary_variable_count} />
      <KV label="Adjacency pairs" value={trace.adjacency_pairs} />
      <KV label="Changed parcels" value={`${trace.changed_parcels} (${trace.changed_pct?.toFixed(1)}%)`} />

      {/* Deviation bar chart */}
      {trace.zone_deviations && Object.keys(trace.zone_deviations).length > 0 && (
        <div className="mt-2">
          <span className="text-gray-400">Zone deviations:</span>
          <div className="space-y-1 mt-1">
            {Object.entries(trace.zone_deviations).map(([zone, dev]) => {
              const absDev = Math.abs(dev as number);
              const maxBar = 50;
              const barWidth = Math.min(absDev * 2, maxBar);
              const isPositive = (dev as number) >= 0;
              return (
                <div key={zone} className="flex items-center gap-2">
                  <span className="min-w-[80px] truncate" title={zone}>{zone}</span>
                  <div className="flex-1 h-3 bg-gray-100 rounded relative">
                    <div
                      className={`h-full rounded ${isPositive ? 'bg-orange-300' : 'bg-blue-300'}`}
                      style={{ width: `${barWidth}%` }}
                    />
                  </div>
                  <span className={`text-xs ${isPositive ? 'text-orange-600' : 'text-blue-600'}`}>
                    {(dev as number) >= 0 ? '+' : ''}{(dev as number).toFixed(1)}ha
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {trace.kg_slack_values && Object.keys(trace.kg_slack_values).length > 0 && (
        <div className="mt-2">
          <span className="text-gray-400">KG slack values:</span>
          <CodeBlock content={JSON.stringify(trace.kg_slack_values, null, 2)} />
        </div>
      )}
    </Section>
  );
}

// ============================================
// Validation Section
// ============================================

function ValidationSection({ trace }: { trace?: ValidationLoopTrace }) {
  if (!trace || !trace.rounds?.length) return null;
  const badge = `${trace.rounds.length} rounds, ${trace.final_status}`;
  return (
    <Section title="验证循环 (validation)" badge={badge} defaultOpen>
      {trace.rounds.map((round) => (
        <div key={round.round_number} className="border rounded p-2 space-y-1">
          <div className="flex items-center gap-2 font-medium">
            <span>第 {round.round_number} 轮</span>
            <span className="text-gray-400 text-xs">{round.timing_ms}ms</span>
            <span
              className={`text-xs px-1.5 py-0.5 rounded ${
                round.total_violations === 0
                  ? 'bg-green-100 text-green-700'
                  : 'bg-yellow-100 text-yellow-700'
              }`}
            >
              {round.total_violations} violations
            </span>
            {round.damping > 0 && (
              <span className="text-gray-400 text-xs">damping={round.damping.toFixed(2)}</span>
            )}
          </div>
          {round.violations?.slice(0, 5).map((v, i) => (
            <div key={i} className="text-xs text-gray-600 pl-2">
              {String((v as Record<string, unknown>).check)}: {String((v as Record<string, unknown>).message)}
            </div>
          ))}
          {round.violations?.length > 5 && (
            <div className="text-xs text-gray-400 pl-2">
              +{round.violations.length - 5} more...
            </div>
          )}
          {Object.keys(round.adjustments || {}).length > 0 && (
            <div className="text-xs text-gray-600 pl-2">
              Adjustments: {JSON.stringify(round.adjustments)}
            </div>
          )}
        </div>
      ))}
      <div className="mt-1">
        <span className="font-medium">Final status: </span>
        <span
          className={`px-1.5 py-0.5 rounded text-xs ${
            trace.final_status === 'pass'
              ? 'bg-green-100 text-green-700'
              : trace.final_status === 'warning'
                ? 'bg-yellow-100 text-yellow-700'
                : 'bg-red-100 text-red-700'
          }`}
        >
          {trace.final_status}
        </span>
      </div>
    </Section>
  );
}

// ============================================
// TracePanel (main)
// ============================================

export function TracePanel({ trace }: { trace: PipelineTrace | null }) {
  if (!trace) return null;

  const totalTiming = trace.total_timing_ms
    ? `${(trace.total_timing_ms / 1000).toFixed(1)}s`
    : '';

  return (
    <div className="border rounded-lg overflow-hidden text-sm">
      <div className="bg-gray-50 px-3 py-2 font-semibold flex items-center gap-2">
        <span>规划→GIS 全过程记录</span>
        {totalTiming && <span className="text-gray-400 text-xs font-normal">{totalTiming}</span>}
      </div>
      <div className="divide-y">
        <ParseSection trace={trace.parse} />
        <KGSection trace={trace.kg} />
        <ConflictSection trace={trace.conflicts} />
        <MIPSection trace={trace.mip} />
        <ValidationSection trace={trace.validation} />
      </div>
    </div>
  );
}
