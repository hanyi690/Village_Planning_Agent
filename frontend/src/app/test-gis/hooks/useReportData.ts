'use client';

import { useState, useEffect, useCallback } from 'react';

interface FacilityInfo {
  name: string;
  content: string;
  scale: string;
  location: string;
  function: string;
}

interface ZoneInfo {
  zone_id: string;
  name: string;
  type: string;
  description: string;
  location_hint: string;
  area_ratio: number;
}

interface ReportDataState {
  layer1Report: string;
  layer2Report: string;
  layer3Report: string;
  facilities: FacilityInfo[];
  zones: ZoneInfo[];
  loading: boolean;
  error: string | null;
}

const JINTIAN_API_BASE = '/api/jintian';

export function useReportData(): ReportDataState & {
  loadReport: (layer: number) => Promise<void>;
  loadFacilities: () => Promise<void>;
  loadZones: () => Promise<void>;
  getFacilitiesByPriority: (priority: 'high' | 'medium' | 'low') => FacilityInfo[];
} {
  const [state, setState] = useState<ReportDataState>({
    layer1Report: '',
    layer2Report: '',
    layer3Report: '',
    facilities: [],
    zones: [],
    loading: true,
    error: null,
  });

  const loadReport = useCallback(async (layer: number) => {
    try {
      const response = await fetch(`${JINTIAN_API_BASE}/report/${layer}`);
      if (!response.ok) {
        throw new Error(`Failed to load report layer ${layer}`);
      }
      const data = await response.json();

      setState(prev => ({
        ...prev,
        [`layer${layer}Report` as keyof ReportDataState]: data.content,
      }));
    } catch (err) {
      console.warn(`[useReportData] Failed to load layer ${layer}:`, err);
    }
  }, []);

  const loadFacilities = useCallback(async () => {
    try {
      const response = await fetch(`${JINTIAN_API_BASE}/planning/facilities`);
      if (!response.ok) {
        throw new Error('Failed to load facilities');
      }
      const data = await response.json();

      setState(prev => ({
        ...prev,
        facilities: data.facilities || [],
      }));
    } catch (err) {
      console.warn('[useReportData] Failed to load facilities:', err);
    }
  }, []);

  const loadZones = useCallback(async () => {
    try {
      const response = await fetch(`${JINTIAN_API_BASE}/planning/zones`);
      if (!response.ok) {
        throw new Error('Failed to load zones');
      }
      const data = await response.json();

      setState(prev => ({
        ...prev,
        zones: data.zones || [],
      }));
    } catch (err) {
      console.warn('[useReportData] Failed to load zones:', err);
    }
  }, []);

  useEffect(() => {
    async function loadAllData() {
      setState(prev => ({ ...prev, loading: true }));

      try {
        const [r1, r2, r3, facRes, zoneRes] = await Promise.all([
          fetch(`${JINTIAN_API_BASE}/report/1`),
          fetch(`${JINTIAN_API_BASE}/report/2`),
          fetch(`${JINTIAN_API_BASE}/report/3`),
          fetch(`${JINTIAN_API_BASE}/planning/facilities`),
          fetch(`${JINTIAN_API_BASE}/planning/zones`),
        ]);

        const data1 = r1.ok ? await r1.json() : { content: '' };
        const data2 = r2.ok ? await r2.json() : { content: '' };
        const data3 = r3.ok ? await r3.json() : { content: '' };
        const facilitiesData = facRes.ok ? await facRes.json() : { facilities: [] };
        const zonesData = zoneRes.ok ? await zoneRes.json() : { zones: [] };

        setState({
          layer1Report: data1.content || '',
          layer2Report: data2.content || '',
          layer3Report: data3.content || '',
          facilities: facilitiesData.facilities || [],
          zones: zonesData.zones || [],
          loading: false,
          error: null,
        });
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Unknown error';
        setState(prev => ({
          ...prev,
          loading: false,
          error: errorMessage,
        }));
      }
    }

    loadAllData();
  }, []);

  const getFacilitiesByPriority = useCallback((priority: 'high' | 'medium' | 'low') => {
    return state.facilities.filter(f => {
      const name = f.name.toLowerCase();
      if (priority === 'high') {
        return name.includes('灵芝') || name.includes('古檀') || name.includes('村委会') || name.includes('电商');
      }
      if (priority === 'medium') {
        return name.includes('加工') || name.includes('船灯') || name.includes('步道');
      }
      return name.includes('民宿') || name.includes('蜂');
    });
  }, [state.facilities]);

  return {
    ...state,
    loadReport,
    loadFacilities,
    loadZones,
    getFacilitiesByPriority,
  };
}