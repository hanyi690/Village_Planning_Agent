"use client";

import React, { memo, useCallback } from "react";

import { usePlanningStore, usePlanningActions } from "../../store";
import ReportViewer from "./ReportViewer";
import PlanningTextViewer from "../PlanningTextViewer";
import { NAV_KEYS } from "@/features/planning/constants";

const FocusArea = memo(function FocusArea() {
  const sessionId = usePlanningStore((state) => state.sessionId);
  const selectedNavigationKey = usePlanningStore(
    (state) => state.selectedNavigationKey,
  );
  const setRightPanelExpanded = usePlanningStore(
    (state) => state.setRightPanelExpanded,
  );
  const setProcessPanelTab = usePlanningStore(
    (state) => state.setProcessPanelTab,
  );
  const { startPlanning } = usePlanningActions();

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
        villageData: data.villageData || "",
        villageName: data.villageName || data.projectName,
        province: data.province || "",
        city: data.city || "",
        county: data.county || "",
        township: data.township || "",
        planningPeriod: data.planningPeriod || "",
        taskDescription: data.taskDescription,
        constraints: data.constraints,
        villageDataFiles: data.villageDataFiles,
        taskFiles: data.taskFiles,
        constraintFiles: data.constraintFiles,
      });
    },
    [startPlanning],
  );

  const handleViewProcess = useCallback(() => {
    setProcessPanelTab("messages");
    setRightPanelExpanded(true);
  }, [setProcessPanelTab, setRightPanelExpanded]);

  // Planning Text view (after all hooks)
  if (selectedNavigationKey === NAV_KEYS.PLANNING_TEXT && sessionId) {
    return (
      <div className="flex-1 h-full relative">
        <PlanningTextViewer sessionId={sessionId} />
      </div>
    );
  }

  return (
    <div className="flex-1 h-full relative">
      <ReportViewer
        onStartPlanning={handleStartPlanning}
        onViewProcess={handleViewProcess}
      />
    </div>
  );
});

export default FocusArea;
