'use client';

import React, { memo, useCallback } from 'react';

import { usePlanningStore, usePlanningActions } from '../../store';
import { useStatus, useCascadeChain } from '../../hooks';
import CascadePanel from '../CascadePanel';
import ReportViewer from './ReportViewer';
import PlanningTextViewer from '../PlanningTextViewer';
import { NAV_KEYS } from '@/features/planning/constants';

const FocusArea = memo(function FocusArea() {
  const status = useStatus();
  const cascadeChain = useCascadeChain();
  const sessionId = usePlanningStore((state) => state.sessionId);
  const selectedNavigationKey = usePlanningStore((state) => state.selectedNavigationKey);
  const setRightPanelExpanded = usePlanningStore((state) => state.setRightPanelExpanded);
  const setProcessPanelTab = usePlanningStore((state) => state.setProcessPanelTab);
  const { startPlanning } = usePlanningActions();

  // Planning Text view
  if (selectedNavigationKey === NAV_KEYS.PLANNING_TEXT && sessionId) {
    return (
      <div className="flex-1 h-full relative">
        <PlanningTextViewer sessionId={sessionId} />
      </div>
    );
  }

  const handleStartPlanning = useCallback(
    (data: {
      projectName: string;
      villageData?: string;
      villageName?: string;
      province?: string;
      city?: string;
      county?: string;
      township?: string;
      planningPeriod?: string;
      taskDescription?: string;
      constraints?: string;
      villageDataFiles?: File[];
      taskFiles?: File[];
      constraintFiles?: File[];
    }) => {
      startPlanning({
        projectName: data.projectName,
        villageData: data.villageData || '',
        villageName: data.villageName || data.projectName,
        province: data.province || '',
        city: data.city || '',
        county: data.county || '',
        township: data.township || '',
        planningPeriod: data.planningPeriod || '',
        taskDescription: data.taskDescription,
        constraints: data.constraints,
        villageDataFiles: data.villageDataFiles,
        taskFiles: data.taskFiles,
        constraintFiles: data.constraintFiles,
      });
    },
    [startPlanning]
  );

  const handleViewProcess = useCallback(() => {
    setProcessPanelTab('messages');
    setRightPanelExpanded(true);
  }, [setProcessPanelTab, setRightPanelExpanded]);

  return (
    <div className="flex-1 h-full relative">
      <ReportViewer
        onStartPlanning={handleStartPlanning}
        onViewProcess={handleViewProcess}
      />

      {/* Cascade chain emergency overlay */}
      {cascadeChain && status !== 'idle' && (
        <div className="absolute inset-0 bg-white/95 backdrop-blur-sm flex flex-col z-20">
          <div className="flex-1 overflow-y-auto p-6">
            <CascadePanel trigger={cascadeChain.trigger} impacted={cascadeChain.impacted} />
          </div>
        </div>
      )}
    </div>
  );
});

export default FocusArea;
