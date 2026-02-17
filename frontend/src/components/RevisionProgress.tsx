'use client';

import React, { useEffect, useState } from 'react';

export interface RevisionProgressData {
  task_id: string;
  current_dimension: string | null;
  total_dimensions: number;
  completed_dimensions: string[];
  status: 'in_progress' | 'completed' | 'failed';
  message: string | null;
}

interface RevisionProgressProps {
  taskId: string;
  onComplete?: () => void;
  onError?: (error: string) => void;
}

const DIMENSION_NAMES: Record<string, string> = {
  industry: '产业规划',
  master_plan: '村庄总体规划',
  traffic: '道路交通规划',
  public_service: '公服设施规划',
  infrastructure: '基础设施规划',
  ecological: '生态绿地规划',
  disaster_prevention: '防震减灾规划',
  heritage: '历史文保规划',
  landscape: '村庄风貌指引',
  project_bank: '建设项目库'
};

export default function RevisionProgress({ taskId, onComplete, onError }: RevisionProgressProps) {
  const [progress, setProgress] = useState<RevisionProgressData | null>(null);
  const [eventSource, setEventSource] = useState<EventSource | null>(null);

  useEffect(() => {
    // Create SSE connection for revision progress
    const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
    const url = `${API_BASE_URL}/api/planning/${taskId}/stream`;
    const es = new EventSource(url);

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        // Check if this is a revision progress update
        if (data.revision_progress) {
          setProgress(data.revision_progress);

          // Check if revision is complete
          if (data.revision_progress.status === 'completed' && onComplete) {
            setTimeout(() => onComplete(), 500);
            es.close();
          }

          // Check if revision failed
          if (data.revision_progress.status === 'failed' && onError) {
            onError(data.revision_progress.message || '修复失败');
            es.close();
          }
        }

        // Close if task is completed or failed
        if (data.status === 'completed' || data.status === 'failed') {
          es.close();
        }
      } catch (error) {
        console.error('Failed to parse SSE data:', error);
      }
    };

    es.onerror = (error) => {
      console.error('SSE error:', error);
      if (onError) {
        onError('连接错误');
      }
    };

    setEventSource(es);

    return () => {
      es.close();
    };
  }, [taskId, onComplete, onError]);

  if (!progress) {
    return (
      <div className="alert alert-info" role="alert">
        <div className="d-flex align-items-center">
          <div className="spinner-border spinner-border-sm me-2" role="status">
            <span className="visually-hidden">Loading...</span>
          </div>
          <div>准备修复...</div>
        </div>
      </div>
    );
  }

  const completedCount = progress.completed_dimensions.length;
  const progressPercent = progress.total_dimensions > 0
    ? Math.round((completedCount / progress.total_dimensions) * 100)
    : 0;

  return (
    <div className="card">
      <div className="card-body">
        <h6 className="card-title mb-3">
          <i className="fas fa-tools me-2" style={{ color: 'var(--primary-orange)' }}></i>
          修复进度
        </h6>

        {/* Progress Bar */}
        <div className="mb-3">
          <div className="d-flex justify-content-between mb-1">
            <span>
              {completedCount} / {progress.total_dimensions} 个维度
            </span>
            <span>{progressPercent}%</span>
          </div>
          <div className="progress" style={{ height: '8px' }}>
            <div
              className="progress-bar bg-warning"
              role="progressbar"
              style={{ width: `${progressPercent}%` }}
              aria-valuenow={progressPercent}
              aria-valuemin={0}
              aria-valuemax={100}
            ></div>
          </div>
        </div>

        {/* Current Dimension */}
        {progress.current_dimension && (
          <div className="mb-3">
            <div className="text-muted mb-1">当前修复:</div>
            <div className="fw-bold">
              <i className="fas fa-cog fa-spin me-2" style={{ color: 'var(--primary-orange)' }}></i>
              {DIMENSION_NAMES[progress.current_dimension] || progress.current_dimension}
            </div>
          </div>
        )}

        {/* Message */}
        {progress.message && (
          <div className="alert alert-info mb-0" role="alert">
            <small>
              <i className="fas fa-info-circle me-1"></i>
              {progress.message}
            </small>
          </div>
        )}

        {/* Completed State */}
        {progress.status === 'completed' && (
          <div className="alert alert-success mb-0" role="alert">
            <i className="fas fa-check-circle me-2"></i>
            修复完成！
          </div>
        )}

        {/* Failed State */}
        {progress.status === 'failed' && (
          <div className="alert alert-danger mb-0" role="alert">
            <i className="fas fa-exclamation-circle me-2"></i>
            修复失败: {progress.message}
          </div>
        )}

        {/* Completed Dimensions List */}
        {completedCount > 0 && (
          <div className="mt-3">
            <small className="text-muted">已完成:</small>
            <div className="mt-1">
              {progress.completed_dimensions.map((dim) => (
                <span
                  key={dim}
                  className="badge bg-light text-dark me-1 mb-1"
                >
                  <i className="fas fa-check text-success me-1"></i>
                  {DIMENSION_NAMES[dim] || dim}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
