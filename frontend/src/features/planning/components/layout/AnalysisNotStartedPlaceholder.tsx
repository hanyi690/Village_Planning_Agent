'use client';

import OverviewGuidePanel from './OverviewGuidePanel';

interface AnalysisNotStartedPlaceholderProps {
  onGoToTaskSettings?: () => void;
}

export default function AnalysisNotStartedPlaceholder({
  onGoToTaskSettings,
}: AnalysisNotStartedPlaceholderProps) {
  return (
    <OverviewGuidePanel
      variant="analysis-pending"
      onGoToTask={onGoToTaskSettings}
    />
  );
}
