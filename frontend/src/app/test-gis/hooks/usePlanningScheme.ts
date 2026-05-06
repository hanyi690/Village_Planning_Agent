'use client';

import { useState, useCallback } from 'react';
import type {
  VillagePlanningScheme,
  PlanningZone,
  FacilityPoint,
  DevelopmentAxis,
} from '../types/planning';
import {
  JINTIAN_PLANNING_SCHEME,
  SIMPLE_PLANNING_SCHEME,
} from '../constants/jintian-planning';

// ============================================
// Types
// ============================================

type ZoneUpdate = Partial<PlanningZone> & { zone_id: string };
type FacilityUpdate = Partial<FacilityPoint> & { facility_id: string };
type AxisUpdate = Partial<DevelopmentAxis> & { axis_id: string };

// ============================================
// Hook: usePlanningScheme
// ============================================

interface UsePlanningSchemeResult {
  scheme: VillagePlanningScheme;
  setScheme: (scheme: VillagePlanningScheme) => void;

  // Zone methods
  updateZone: (update: ZoneUpdate) => void;
  addZone: (zone: PlanningZone) => void;
  removeZone: (zoneId: string) => void;

  // Facility methods
  updateFacility: (update: FacilityUpdate) => void;
  addFacility: (facility: FacilityPoint) => void;
  removeFacility: (facilityId: string) => void;

  // Axis methods
  updateAxis: (update: AxisUpdate) => void;
  addAxis: (axis: DevelopmentAxis) => void;
  removeAxis: (axisId: string) => void;

  // Import/Export
  exportJSON: () => string;
  importJSON: (json: string) => boolean;
  exportToFile: () => void;

  // Reset
  loadDefault: (type: 'jintian' | 'simple') => void;
  reset: () => void;
}

export function usePlanningScheme(
  initialScheme?: VillagePlanningScheme
): UsePlanningSchemeResult {
  const [scheme, setScheme] = useState<VillagePlanningScheme>(
    initialScheme || JINTIAN_PLANNING_SCHEME
  );

  // ============================================
  // Zone CRUD
  // ============================================

  const updateZone = useCallback((update: ZoneUpdate) => {
    setScheme((prev) => ({
      ...prev,
      zones: prev.zones.map((z) =>
        z.zone_id === update.zone_id ? { ...z, ...update } : z
      ),
    }));
  }, []);

  const addZone = useCallback((zone: PlanningZone) => {
    setScheme((prev) => ({
      ...prev,
      zones: [...prev.zones, zone],
    }));
  }, []);

  const removeZone = useCallback((zoneId: string) => {
    setScheme((prev) => ({
      ...prev,
      zones: prev.zones.filter((z) => z.zone_id !== zoneId),
    }));
  }, []);

  // ============================================
  // Facility CRUD
  // ============================================

  const updateFacility = useCallback((update: FacilityUpdate) => {
    setScheme((prev) => ({
      ...prev,
      facilities: prev.facilities.map((f) =>
        f.facility_id === update.facility_id ? { ...f, ...update } : f
      ),
    }));
  }, []);

  const addFacility = useCallback((facility: FacilityPoint) => {
    setScheme((prev) => ({
      ...prev,
      facilities: [...prev.facilities, facility],
    }));
  }, []);

  const removeFacility = useCallback((facilityId: string) => {
    setScheme((prev) => ({
      ...prev,
      facilities: prev.facilities.filter((f) => f.facility_id !== facilityId),
    }));
  }, []);

  // ============================================
  // Axis CRUD
  // ============================================

  const updateAxis = useCallback((update: AxisUpdate) => {
    setScheme((prev) => ({
      ...prev,
      axes: prev.axes.map((a) =>
        a.axis_id === update.axis_id ? { ...a, ...update } : a
      ),
    }));
  }, []);

  const addAxis = useCallback((axis: DevelopmentAxis) => {
    setScheme((prev) => ({
      ...prev,
      axes: [...prev.axes, axis],
    }));
  }, []);

  const removeAxis = useCallback((axisId: string) => {
    setScheme((prev) => ({
      ...prev,
      axes: prev.axes.filter((a) => a.axis_id !== axisId),
    }));
  }, []);

  // ============================================
  // Import/Export
  // ============================================

  const exportJSON = useCallback(() => {
    return JSON.stringify(scheme, null, 2);
  }, [scheme]);

  const importJSON = useCallback((json: string): boolean => {
    try {
      const parsed = JSON.parse(json) as VillagePlanningScheme;
      // Basic validation
      if (!parsed.zones || parsed.zones.length === 0) {
        return false;
      }
      setScheme(parsed);
      return true;
    } catch {
      return false;
    }
  }, []);

  const exportToFile = useCallback(() => {
    const json = exportJSON();
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `planning-scheme-${Date.now()}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [exportJSON]);

  // ============================================
  // Reset
  // ============================================

  const loadDefault = useCallback((type: 'jintian' | 'simple') => {
    setScheme(type === 'jintian' ? JINTIAN_PLANNING_SCHEME : SIMPLE_PLANNING_SCHEME);
  }, []);

  const reset = useCallback(() => {
    setScheme(JINTIAN_PLANNING_SCHEME);
  }, []);

  return {
    scheme,
    setScheme,
    updateZone,
    addZone,
    removeZone,
    updateFacility,
    addFacility,
    removeFacility,
    updateAxis,
    addAxis,
    removeAxis,
    exportJSON,
    importJSON,
    exportToFile,
    loadDefault,
    reset,
  };
}