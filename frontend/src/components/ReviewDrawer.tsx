'use client';

import React, { useState, useEffect } from 'react';
import { taskApi, ReviewData } from '@/lib/api';
import DimensionSelector, { DIMENSION_OPTIONS, DimensionOption } from './DimensionSelector';
import MarkdownRenderer from './MarkdownRenderer';
import CheckpointDiffViewer from './CheckpointDiffViewer';

interface ReviewDrawerProps {
  isOpen: boolean;
  taskId: string;
  onClose: () => void;
  onApprove: () => Promise<void>;
  onReject: (feedback: string, dimensions?: string[]) => Promise<void>;
  onRollback: (checkpointId: string) => Promise<void>;
}

export default function ReviewDrawer({
  isOpen,
  taskId,
  onClose,
  onApprove,
  onReject,
  onRollback,
}: ReviewDrawerProps) {
  const [reviewData, setReviewData] = useState<ReviewData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState('');
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>([]);
  const [autoDetectedDimensions, setAutoDetectedDimensions] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<'content' | 'diff'>('content');
  const [selectedCheckpointA, setSelectedCheckpointA] = useState<string>('');
  const [selectedCheckpointB, setSelectedCheckpointB] = useState<string>('');
  const [submitting, setSubmitting] = useState(false);

  // Load review data when drawer opens
  useEffect(() => {
    if (isOpen && taskId) {
      loadReviewData();
    }
  }, [isOpen, taskId]);

  const loadReviewData = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await taskApi.getReviewData(taskId);
      setReviewData(data);

      // Auto-detect dimensions from content (simple keyword matching)
      const detected = detectDimensions(data.content);
      setAutoDetectedDimensions(detected);
      setSelectedDimensions(detected);
    } catch (err: any) {
      setError(err.message || 'Failed to load review data');
    } finally {
      setLoading(false);
    }
  };

  const detectDimensions = (content: string): string[] => {
    const detected: string[] = [];
    const contentLower = content.toLowerCase();

    // Simple keyword matching based on RevisionTool.DIMENSION_KEYWORDS
    const dimensionKeywords: Record<string, string[]> = {
      industry: ['产业', '经济', '农业', '工业', '旅游', '收入', 'gdp'],
      master_plan: ['总体规划', '空间布局', '用地', '村庄布局', '总规'],
      traffic: ['交通', '道路', '运输', '出行', '路网', '停车'],
      public_service: ['公共服务', '教育', '医疗', '卫生', '养老', '文化', '体育'],
      infrastructure: ['基础设施', '水电', '给排水', '电力', '通信', '管网'],
      ecological: ['生态', '环境', '绿地', '绿化', '环保', '污染', '景观'],
      disaster_prevention: ['防灾', '减灾', '安全', '消防', '防洪', '地震'],
      heritage: ['历史', '文化', '文物', '保护', '古迹', '传统'],
      landscape: ['风貌', '建筑', '风格', '外观', '色彩', '高度'],
      project_bank: ['项目', '建设', '工程', '投资', '实施', '计划']
    };

    for (const [dimension, keywords] of Object.entries(dimensionKeywords)) {
      for (const keyword of keywords) {
        if (keyword in contentLower) {
          if (!detected.includes(dimension)) {
            detected.push(dimension);
          }
          break;
        }
      }
    }

    return detected;
  };

  const handleApprove = async () => {
    setSubmitting(true);
    try {
      await onApprove();
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to approve');
    } finally {
      setSubmitting(false);
    }
  };

  const handleReject = async () => {
    if (!feedback.trim()) {
      setError('请提供反馈意见');
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await onReject(feedback, selectedDimensions);
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to reject');
    } finally {
      setSubmitting(false);
    }
  };

  const handleRollback = async (checkpointId: string) => {
    if (!confirm(`确定要回退到 ${checkpointId} 吗？之后的内容将被删除。`)) {
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await onRollback(checkpointId);
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to rollback');
    } finally {
      setSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className={`drawer-backdrop ${isOpen ? 'show' : ''}`}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          backgroundColor: 'rgba(0, 0, 0, 0.5)',
          zIndex: 1040,
          display: isOpen ? 'block' : 'none',
        }}
        onClick={onClose}
      ></div>

      {/* Drawer */}
      <div
        className={`drawer drawer-end ${isOpen ? 'show' : ''}`}
        style={{
          position: 'fixed',
          top: 0,
          right: 0,
          width: '600px',
          maxWidth: '90%',
          height: '100%',
          backgroundColor: 'white',
          boxShadow: '-2px 0 8px rgba(0, 0, 0, 0.15)',
          zIndex: 1050,
          transform: isOpen ? 'translateX(0)' : 'translateX(100%)',
          transition: 'transform 0.3s ease-in-out',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Header */}
        <div className="drawer-header p-3 border-bottom" style={{ flexShrink: 0 }}>
          <div className="d-flex justify-content-between align-items-center">
            <h5 className="mb-0">
              <i className="fas fa-clipboard-check me-2" style={{ color: 'var(--primary-green)' }}></i>
              规划审查
            </h5>
            <button
              className="btn btn-sm btn-outline-secondary"
              type="button"
              onClick={onClose}
              disabled={submitting}
            >
              <i className="fas fa-times"></i>
            </button>
          </div>
          {reviewData && (
            <div className="mt-2">
              <span className="badge bg-primary">Layer {reviewData.current_layer}</span>
              <small className="text-muted ms-2">
                {reviewData.summary.word_count} 字
              </small>
            </div>
          )}
        </div>

        {/* Body */}
        <div className="drawer-body p-3" style={{ flex: 1, overflowY: 'auto' }}>
          {loading && (
            <div className="text-center py-5">
              <div className="spinner-border text-primary" role="status">
                <span className="visually-hidden">Loading...</span>
              </div>
              <p className="mt-2">加载审查数据...</p>
            </div>
          )}

          {error && (
            <div className="alert alert-danger" role="alert">
              <i className="fas fa-exclamation-circle me-2"></i>
              {error}
              <button
                type="button"
                className="btn-close float-end"
                onClick={() => setError(null)}
              ></button>
            </div>
          )}

          {reviewData && (
            <div>
              {/* Tabs */}
              <ul className="nav nav-tabs mb-3">
                <li className="nav-item">
                  <button
                    className={`nav-link ${activeTab === 'content' ? 'active' : ''}`}
                    onClick={() => setActiveTab('content')}
                  >
                    <i className="fas fa-file-alt me-1"></i>
                    内容
                  </button>
                </li>
                <li className="nav-item">
                  <button
                    className={`nav-link ${activeTab === 'diff' ? 'active' : ''}`}
                    onClick={() => setActiveTab('diff')}
                  >
                    <i className="fas fa-exchange-alt me-1"></i>
                    版本对比
                  </button>
                </li>
              </ul>

              {/* Content Tab */}
              {activeTab === 'content' && (
                <div>
                  {/* Report Summary */}
                  <div className="card mb-3">
                    <div className="card-body">
                      <h6 className="card-title mb-2">
                        <i className="fas fa-info-circle me-2"></i>
                        报告摘要
                      </h6>
                      <div className="row text-sm">
                        <div className="col-6">
                          <div className="text-muted">当前层级</div>
                          <div className="fw-bold">Layer {reviewData.current_layer}</div>
                        </div>
                        <div className="col-6">
                          <div className="text-muted">字数</div>
                          <div className="fw-bold">{reviewData.summary.word_count}</div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Report Content */}
                  <div className="card mb-3">
                    <div className="card-body" style={{ maxHeight: '400px', overflowY: 'auto' }}>
                      <MarkdownRenderer content={reviewData.content} />
                    </div>
                  </div>

                  {/* Dimension Selector (only for Layer 3) */}
                  {reviewData.current_layer === 3 && reviewData.available_dimensions.length > 0 && (
                    <div className="card mb-3">
                      <div className="card-body">
                        <DimensionSelector
                          dimensions={DIMENSION_OPTIONS.filter(d => reviewData.available_dimensions.includes(d.id))}
                          selectedDimensions={selectedDimensions}
                          onChange={setSelectedDimensions}
                          disabled={submitting}
                          autoDetected={autoDetectedDimensions}
                        />
                      </div>
                    </div>
                  )}

                  {/* Feedback Input */}
                  <div className="card mb-3">
                    <div className="card-body">
                      <label htmlFor="feedback" className="form-label">
                        <strong>反馈意见 *</strong>
                      </label>
                      <textarea
                        id="feedback"
                        className="form-control"
                        rows={4}
                        placeholder="请描述需要修改的内容..."
                        value={feedback}
                        onChange={(e) => setFeedback(e.target.value)}
                        disabled={submitting}
                      ></textarea>
                      {autoDetectedDimensions.length > 0 && (
                        <small className="text-muted">
                          <i className="fas fa-lightbulb me-1"></i>
                          AI已识别以下维度: {autoDetectedDimensions.join(', ')}
                        </small>
                      )}
                    </div>
                  </div>

                  {/* Checkpoints */}
                  {reviewData.checkpoints.length > 0 && (
                    <div className="card mb-3">
                      <div className="card-body">
                        <h6 className="card-title mb-2">
                          <i className="fas fa-history me-2"></i>
                          可回退的检查点
                        </h6>
                        <div className="list-group list-group-flush">
                          {reviewData.checkpoints.map((cp) => (
                            <div
                              key={cp.checkpoint_id}
                              className="list-group-item d-flex justify-content-between align-items-center"
                            >
                              <div>
                                <div className="fw-bold">{cp.description}</div>
                                <small className="text-muted">{cp.timestamp}</small>
                              </div>
                              <button
                                className="btn btn-sm btn-outline-secondary"
                                type="button"
                                onClick={() => handleRollback(cp.checkpoint_id)}
                                disabled={submitting}
                              >
                                <i className="fas fa-undo me-1"></i>
                                回退
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Diff Tab - 暂时隐藏，等待完整实现 */}
              {activeTab === 'diff' && (
                <div className="alert alert-info">
                  <i className="fas fa-info-circle me-2"></i>
                  版本对比功能开发中，敬请期待
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="drawer-footer p-3 border-top" style={{ flexShrink: 0 }}>
          <div className="d-flex gap-2">
            <button
              className="btn btn-success flex-grow-1"
              type="button"
              onClick={handleApprove}
              disabled={submitting || loading}
            >
              <i className={`fas ${submitting ? 'fa-spinner fa-spin' : 'fa-check'} me-2`}></i>
              批准
            </button>
            <button
              className="btn btn-warning flex-grow-1"
              type="button"
              onClick={handleReject}
              disabled={submitting || loading || !feedback.trim()}
            >
              <i className={`fas ${submitting ? 'fa-spinner fa-spin' : 'fa-times'} me-2`}></i>
              驳回
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

/* Responsive Styles for Vertical Screens */
// Inline styles are already handled in the component above
// The drawer uses maxWidth: '90%' which provides mobile adaptation
// On smaller screens, the drawer will adjust width automatically

