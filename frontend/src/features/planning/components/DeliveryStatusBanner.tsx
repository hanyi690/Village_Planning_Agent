"use client";

import React from "react";
import { usePlanningStore } from "../store";
import { useSessionId } from "../hooks";

/**
 * Delivery status banner (v1 /delivery + /map-layers).
 *
 * Shows the authoritative delivery conclusion. `partial` and `diagnostic_only`
 * are legal terminal states but must NOT be presented as a statutory-complete
 * planning output. When statutory_complete is false, or the snapshot has no
 * land-use changes, we surface that explicitly instead of treating the
 * current-state copy as a finished plan.
 *
 * v1 adapter: also lists the real `delivery.deliverables` (成果文件) so the
 * user can see which files the backend actually produced. The download
 * endpoint (/delivery.downloads) is still pending on the backend, so the list
 * is informational only.
 */
export default function DeliveryStatusBanner() {
  const sessionId = useSessionId();
  const delivery = usePlanningStore((state) => state.delivery);
  const status = usePlanningStore((state) => state.status);

  if (!sessionId || !delivery || !delivery.available) return null;

  const ds = delivery.delivery_status;

  if (ds === "diagnostic_only") return null;

  // Only inspecting mode or terminal states show the conclusion banner.
  if (!ds && status !== "completed" && status !== "failed") return null;

  const deliverables = Array.isArray(delivery.deliverables) ? delivery.deliverables : [];
  const filesBlock =
    deliverables.length > 0 ? (
      <div className="mt-3 border-t border-current/20 pt-2">
        <div className="text-xs font-semibold">交付成果文件（deliverables）</div>
        <ul className="mt-1 space-y-1">
          {deliverables.map((raw, i) => {
            const d = raw as {
              description?: string;
              type?: string;
              format?: string;
              deliverable_id?: string;
            };
            return (
              <li key={i} className="flex items-center gap-2 text-xs">
                <span className="font-mono">{d.description || d.type || '成果'}</span>
                <span className="rounded bg-white/50 px-1 text-[10px]">{d.format || ''}</span>
                <span className="ml-auto font-mono text-[10px] opacity-60">{d.deliverable_id || ''}</span>
              </li>
            );
          })}
        </ul>
        <div className="mt-1 text-[10px] opacity-70">
          下载端点（/delivery.downloads）待后端提供后启用。
        </div>
      </div>
    ) : null;

  let body: React.ReactNode = null;

  // No authoritative snapshot yet.
  if (!ds) {
    body = (
      <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
        交付快照尚未就绪（DELIVER 尚未产出权威空间成果）。
      </div>
    );
  } else {
    const isStatutoryComplete = Boolean(delivery.statutory_complete);

    if (ds === "complete" && isStatutoryComplete) {
      body = (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          规划交付已完成，已通过法定完整性校验。
        </div>
      );
    } else if (ds === "complete") {
      body = (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          规划成果已生成，但尚未满足法定完整性门槛（statutory_complete=false）。请在交付审核中核对地类变更与延期项。
        </div>
      );
    } else if (ds === "partial") {
      body = (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          当前交付为{" "}
          <span className="font-semibold">部分成果（partial）</span>：存在明确延期，不可作为法定完整规划。
          {delivery.deferral_summary && Object.keys(delivery.deferral_summary).length > 0 && (
            <span className="mt-1 block text-xs text-amber-700">
              延期摘要：{JSON.stringify(delivery.deferral_summary)}
            </span>
          )}
        </div>
      );
    }
    // diagnostic_only: workflow terminal failure — do not surface raw JSON in the UI.
  }

  return (
    <>
      {body}
      {filesBlock}
    </>
  );
}