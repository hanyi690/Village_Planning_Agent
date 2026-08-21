'use client';

import { usePlanningStore } from '@/features/planning/store';
import { planningApi } from '@/features/planning/api';
import { useCallback, useEffect, useState } from 'react';

/**
 * v1 合规视图：从 DeliveryProjection 读取交付状态、延期台账与可下载产物，
 * 替代已下线的 /api/compliance/* 独立分析接口。
 */
export default function DeliveryCompliancePanel({
  sessionId,
  projectName,
}: {
  sessionId: string;
  projectName?: string;
}) {
  const storeDelivery = usePlanningStore((s) => s.delivery);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const delivery = await planningApi.getDelivery(sessionId);
      usePlanningStore.getState().setDelivery({
        available: delivery.available,
        delivery_status: delivery.delivery_status ?? null,
        statutory_complete: delivery.statutory_complete,
        snapshot_checksum: delivery.snapshot_checksum ?? '',
        deferral_summary: delivery.deferral_summary ?? {},
        diagnostic_summary: delivery.diagnostic_summary ?? {},
        deliverables: delivery.deliverables ?? [],
        downloads: delivery.downloads ?? [],
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载交付投影失败');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    if (!storeDelivery?.available) {
      void refresh();
    }
  }, [refresh, sessionId, storeDelivery?.available]);

  const delivery = storeDelivery;
  const deferrals = delivery?.deferral_summary ?? {};
  const diagnostics = delivery?.diagnostic_summary ?? {};
  const deferralCount = typeof deferrals.count === 'number'
    ? deferrals.count
    : Object.keys(deferrals).length;

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-sm">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[#e5efe9] px-4 py-3">
        <div>
          <h3 className="text-[14px] font-semibold text-[#264f43]">交付合规 · 闸门状态</h3>
          <p className="text-[11px] text-[#8aa59a]">
            {projectName || '当前项目'} · 数据来自 v1 /delivery 投影（DELIVER 阶段产物）
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="rounded-xl bg-[#3fb288] px-4 py-2 text-[12px] font-medium text-white hover:bg-[#319a75] disabled:opacity-60"
        >
          {loading ? '刷新中…' : '刷新交付状态'}
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {error && (
          <div className="rounded-xl border border-[#fecdd3] bg-[#fff1f2] px-4 py-3 text-[12px] text-[#be123c]">
            {error}
          </div>
        )}

        {!delivery?.available ? (
          <div className="rounded-xl border border-dashed border-[#d5e8df] bg-[#f8fcfa] px-4 py-8 text-center text-[12px] text-[#7ea294]">
            尚未生成交付投影。请完成 L1→L3 分析并进入空间链（GROUND→DELIVER）后刷新。
          </div>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <StatCard
                label="交付状态"
                value={delivery.delivery_status || '未知'}
                hint={delivery.delivery_status === 'partial' ? '含延期或未决项' : '可查看下方清单'}
              />
              <StatCard
                label="法定完整"
                value={delivery.statutory_complete ? '是' : '否'}
                hint="statutory_complete"
              />
              <StatCard
                label="延期条目"
                value={String(deferralCount)}
                hint="deferral_summary"
              />
            </div>

            {Object.keys(diagnostics).length > 0 && (
              <Panel title="诊断摘要">
                <pre className="overflow-x-auto whitespace-pre-wrap text-[11px] text-[#4b635a]">
                  {JSON.stringify(diagnostics, null, 2)}
                </pre>
              </Panel>
            )}

            {Object.keys(deferrals).length > 0 && (
              <Panel title="延期台账（节选）">
                <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-[11px] text-[#4b635a]">
                  {JSON.stringify(deferrals, null, 2)}
                </pre>
              </Panel>
            )}

            {(delivery.downloads?.length ?? 0) > 0 && (
              <Panel title="可下载产物">
                <ul className="space-y-2 text-[12px] text-[#2d5a4a]">
                  {delivery.downloads!.map((path) => (
                    <li key={path} className="rounded-lg bg-[#f4faf7] px-3 py-2 font-mono text-[11px]">
                      {path}
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-[10px] text-[#8aa59a]">
                  完整文件路径由后端 DELIVER 写出；可通过「导出」对话框或空间成果图查看 HTML/PNG/GeoJSON。
                </p>
              </Panel>
            )}
          </>
        )}
      </div>
    </section>
  );
}

function StatCard({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-xl border border-[#e5efe9] bg-[#f8fcfa] px-4 py-3">
      <div className="text-[11px] text-[#8aa59a]">{label}</div>
      <div className="mt-1 text-[18px] font-semibold text-[#264f43]">{value}</div>
      <div className="mt-1 text-[10px] text-[#a8c2b8]">{hint}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-[#e5efe9] p-4">
      <h4 className="mb-2 text-[13px] font-semibold text-[#264f43]">{title}</h4>
      {children}
    </div>
  );
}
