/**
 * v1 API capability matrix — single place to gate UI that depends on backend routes.
 *
 * When backend v1 adds a route, flip the flag here and wire the panel/API.
 */
export const V1_CAPABILITIES = {
  /** L1/L2/L3 analysis + SSE + human-review + delivery (core path). */
  planningCore: true,
  /** Client-assembled planning text from dimension reports (no /planning-text API). */
  planningTextClient: true,
  /** Client-side layer report export (JSON/MD). */
  layerReportClientExport: true,
  /** Delivery manifest downloads (HTML/PNG/GeoJSON from DELIVER stage). */
  deliveryDownloads: true,
  /** Delivery-based compliance/deferral view (replaces /api/compliance). */
  deliveryComplianceView: true,
  /** Legacy /api/evaluation — backend removed. */
  qualityEvaluation: false,
  /** Legacy /api/suitability — backend removed. */
  suitabilityPanel: false,
  /** Legacy /api/compliance run — backend removed. */
  complianceRunApi: false,
  /** Step mode is submitted at session creation; runtime changes stay local. */
  stepModeMidSessionSync: false,
} as const;

export type V1Capability = keyof typeof V1_CAPABILITIES;

export function isCapabilityEnabled(key: V1Capability): boolean {
  return V1_CAPABILITIES[key];
}

/** Sidebar nav ids hidden when capability is off. */
export const NAV_CAPABILITY_MAP: Partial<Record<string, V1Capability>> = {
  'overview-evaluation': 'qualityEvaluation',
  'data-suitability': 'suitabilityPanel',
};

export function isNavItemEnabled(navId: string): boolean {
  const cap = NAV_CAPABILITY_MAP[navId];
  return cap ? isCapabilityEnabled(cap) : true;
}
