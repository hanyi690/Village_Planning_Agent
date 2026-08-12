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
 */
export default function DeliveryStatusBanner() {
  const sessionId = useSessionId();
  const delivery = usePlanningStore((state) => state.delivery);
  const status = usePlanningStore((state) => state.status);

  if (!sessionId || !delivery || !delivery.available) return null;

  const ds = delivery.delivery_status;

  // Only inspecting mode or terminal states show the conclusion banner.
  if (!ds && status !== "completed" && status !== "failed") return null;

  // No authoritative snapshot yet.
  if (!ds) {
    return (
      <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
        交付快照尚未就绪（DELIVER 尚未产出权威空间成果）。
      </div>
    );
  }

  const isStatutoryComplete = Boolean(delivery.statutory_complete);

  if (ds === "complete" && isStatutoryComplete) {
    return (
      <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
        规划交付已完成，已通过法定完整性校验。
      </div>
    );
  }

  if (ds === "complete") {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        规划成果已生成，但尚未满足法定完整性门槛（statutory_complete=false）。请在交付审核中核对地类变更与延期项。
      </div>
    );
  }

  if (ds === "partial") {
    return (
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

  if (ds === "diagnostic_only") {
    return (
      <div className="rounded-md border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-orange-800">
        当前交付仅为{" "}
        <span className="font-semibold">诊断/人工处理（diagnostic_only）</span>，不构成正式规划成果。
        {delivery.diagnostic_summary && Object.keys(delivery.diagnostic_summary).length > 0 && (
          <span className="mt-1 block text-xs text-orange-700">
            诊断摘要：{JSON.stringify(delivery.diagnostic_summary)}
          </span>
        )}
      </div>
    );
  }

  return null;
}