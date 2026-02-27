'use client';

import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';

// ============================================
// Types
// ============================================

export type ReviewStatus = 'idle' | 'reviewing' | 'revising' | 'completed';

export interface RevisionProgress {
  task_id: string;
  current_dimension: string | null;
  total_dimensions: number;
  completed_dimensions: string[];
  status: string;
  message: string | null;
}

export interface PlanningContextType {
  // State
  reviewStatus: ReviewStatus;
  currentLayer: number;
  showReviewButton: boolean;
  revisionProgress: RevisionProgress | null;
  isReviewDrawerOpen: boolean;

  // Actions
  setReviewStatus: (status: ReviewStatus) => void;
  setCurrentLayer: (layer: number) => void;
  setShowReviewButton: (show: boolean) => void;
  setRevisionProgress: (progress: RevisionProgress | null) => void;
  openReviewDrawer: () => void;
  closeReviewDrawer: () => void;
  startReview: () => void;
  submitApproval: () => Promise<void>;
  submitRejection: (feedback: string, dimensions?: string[]) => Promise<void>;
  submitRollback: (checkpointId: string) => Promise<void>;
  reset: () => void;
}

// ============================================
// Context
// ============================================

const PlanningContext = createContext<PlanningContextType | undefined>(undefined);

// ============================================
// Provider
// ============================================

interface PlanningProviderProps {
  children: ReactNode;
  taskId: string;
}

export function PlanningProvider({ children, taskId }: PlanningProviderProps) {
  const [reviewStatus, setReviewStatus] = useState<ReviewStatus>('idle');
  const [currentLayer, setCurrentLayer] = useState(1);
  const [showReviewButton, setShowReviewButton] = useState(false);
  const [revisionProgress, setRevisionProgress] = useState<RevisionProgress | null>(null);
  const [isReviewDrawerOpen, setIsReviewDrawerOpen] = useState(false);

  const openReviewDrawer = useCallback(() => {
    setIsReviewDrawerOpen(true);
    setReviewStatus('reviewing');
  }, []);

  const closeReviewDrawer = useCallback(() => {
    setIsReviewDrawerOpen(false);
    if (reviewStatus === 'reviewing') {
      setReviewStatus('idle');
    }
  }, [reviewStatus]);

  const startReview = useCallback(() => {
    openReviewDrawer();
  }, [openReviewDrawer]);

  const submitApproval = useCallback(async () => {
    try {
      setReviewStatus('idle');
      closeReviewDrawer();

      // Call API to approve review
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/planning/${taskId}/review/approve`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error('Failed to approve review');
      }

      setShowReviewButton(false);
    } catch (error) {
      console.error('Error approving review:', error);
      throw error;
    }
  }, [taskId, closeReviewDrawer]);

  const submitRejection = useCallback(async (feedback: string, dimensions?: string[]) => {
    try {
      setReviewStatus('revising');

      // Call API to reject review and trigger revision
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/planning/${taskId}/review/reject`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          feedback,
          target_dimensions: dimensions,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to reject review');
      }

      const result = await response.json();

      // Update revision progress
      if (result.revision_progress) {
        setRevisionProgress(result.revision_progress);
      }

      closeReviewDrawer();
    } catch (error) {
      console.error('Error rejecting review:', error);
      setReviewStatus('idle');
      throw error;
    }
  }, [taskId, closeReviewDrawer]);

  const submitRollback = useCallback(async (checkpointId: string) => {
    try {
      // Call API to rollback to checkpoint
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/planning/${taskId}/rollback`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          checkpoint_id: checkpointId,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to rollback');
      }

      // Reset state after rollback
      setReviewStatus('idle');
      setRevisionProgress(null);
      closeReviewDrawer();
    } catch (error) {
      console.error('Error rolling back:', error);
      throw error;
    }
  }, [taskId, closeReviewDrawer]);

  const reset = useCallback(() => {
    setReviewStatus('idle');
    setCurrentLayer(1);
    setShowReviewButton(false);
    setRevisionProgress(null);
    setIsReviewDrawerOpen(false);
  }, []);

  const value: PlanningContextType = {
    // State
    reviewStatus,
    currentLayer,
    showReviewButton,
    revisionProgress,
    isReviewDrawerOpen,
    // Actions
    setReviewStatus,
    setCurrentLayer,
    setShowReviewButton,
    setRevisionProgress,
    openReviewDrawer,
    closeReviewDrawer,
    startReview,
    submitApproval,
    submitRejection,
    submitRollback,
    reset,
  };

  return (
    <PlanningContext.Provider value={value}>
      {children}
    </PlanningContext.Provider>
  );
}

// ============================================
// Hook
// ============================================

export function usePlanningContext(): PlanningContextType {
  const context = useContext(PlanningContext);
  if (!context) {
    throw new Error('usePlanningContext must be used within a PlanningProvider');
  }
  return context;
}
