'use client';

import OverviewGuidePanel from './OverviewGuidePanel';

interface OverviewLockedPlaceholderProps {
  variant: 'analysis' | 'document' | 'evaluation';
  onGoToTask?: () => void;
}

export default function OverviewLockedPlaceholder({
  variant,
  onGoToTask,
}: OverviewLockedPlaceholderProps) {
  return (
    <OverviewGuidePanel
      variant={
        variant === 'analysis'
          ? 'analysis-intro'
          : variant === 'evaluation'
            ? 'evaluation-intro'
            : 'document-intro'
      }
      onGoToTask={onGoToTask}
    />
  );
}
