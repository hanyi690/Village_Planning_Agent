'use client';

import React, { useCallback } from 'react';

import { usePlanningStore, usePlanningActions } from '../../store';
import { useStatus, useCascadeChain } from '../../hooks';
import CascadePanel from '../CascadePanel';
import ReportViewer from './ReportViewer';

export default function FocusArea() {
  const status = useStatus();
  const cascadeChain = useCascadeChain();
  const setRightPanelExpanded = usePlanningStore((state) => state.setRightPanelExpanded);
  const setProcessPanelTab = usePlanningStore((state) => state.setProcessPanelTab);
  const { startPlanning, loadHistoricalSession } = usePlanningActions();

  const handleStartPlanning = useCallback(
    (data: {
      projectName: string;
      villageData?: string;
      villageName?: string;
      taskDescription?: string;
      constraints?: string;
      villageDataFiles?: File[];
      taskFiles?: File[];
      constraintFiles?: File[];
    }) => {
      startPlanning({
        projectName: data.projectName,
        villageData: data.villageData || '',
        villageName: data.projectName,
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

  const handleLoadSession = useCallback(
    (villageName: string, sessionId: string) => {
      loadHistoricalSession(villageName, sessionId);
    },
    [loadHistoricalSession]
  );

  return (
    <div className="flex-1 h-full relative">
      <ReportViewer
        onStartPlanning={handleStartPlanning}
        onViewProcess={handleViewProcess}
        onLoadSession={handleLoadSession}
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
}
