'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { taskApi, fileApi } from '@/lib/api';
import ReviewDrawer from '@/components/ReviewDrawer';
import CheckpointViewer from '@/components/CheckpointViewer';
import Link from 'next/link';

interface FormField {
  projectName: string;
  villageData: string;
  taskDescription: string;
  constraints: string;
  stepMode: boolean;
  streamMode: boolean;
}

export default function NewVillagePage() {
  const router = useRouter();
  const [step, setStep] = useState<'form' | 'planning' | 'complete'>('form');
  const [taskId, setTaskId] = useState<string>('');
  const [showReviewDrawer, setShowReviewDrawer] = useState(false);
  const [showCheckpointViewer, setShowCheckpointViewer] = useState(false);

  // Form state
  const [form, setForm] = useState<FormField>({
    projectName: '',
    villageData: '',
    taskDescription: '制定乡村振兴规划',
    constraints: '无特殊约束',
    stepMode: true,
    streamMode: true,
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string>('');

  const handleFileUpload = async (file: File) => {
    try {
      setLoading(true);
      setError(null);
      const result = await fileApi.uploadFile(file);
      setForm(prev => ({ ...prev, villageData: result.content }));
      setFileName(file.name);
    } catch (err: any) {
      setError(err.message || '文件上传失败');
    } finally {
      setLoading(false);
    }
  };

  const handleStartPlanning = async () => {
    if (!form.projectName.trim() || !form.villageData.trim()) {
      setError('请填写项目名称并上传村庄数据');
      return;
    }

    try {
      setLoading(true);
      const response = await taskApi.createTask({
        project_name: form.projectName.trim(),
        village_data: form.villageData,
        task_description: form.taskDescription,
        constraints: form.constraints,
        need_human_review: form.stepMode,
        stream_mode: form.streamMode,
        step_mode: form.stepMode,
        input_mode: 'text',
      });

      setTaskId(response.task_id);
      setStep('planning');
    } catch (err: any) {
      setError(err.message || '创建任务失败');
    } finally {
      setLoading(false);
    }
  };

  // Review handlers
  const handleApproveReview = async () => {
    if (!taskId) return;
    try {
      await taskApi.approveReview(taskId);
      setShowReviewDrawer(false);
    } catch (err: any) {
      setError(err.message || '批准失败');
    }
  };

  const handleRejectReview = async (feedback: string, dimensions?: string[]) => {
    if (!taskId) return;
    try {
      await taskApi.rejectReview(taskId, feedback, dimensions);
      setShowReviewDrawer(false);
    } catch (err: any) {
      setError(err.message || '驳回失败');
    }
  };

  const handleRollbackCheckpoint = async (checkpointId: string) => {
    if (!taskId) return;
    try {
      await taskApi.rollbackCheckpoint(taskId, checkpointId);
      setShowReviewDrawer(false);
    } catch (err: any) {
      setError(err.message || '回退失败');
    }
  };

  return (
    <div className="new-village-page container-fluid py-4" style={{ minHeight: '100vh' }}>
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="d-flex justify-content-between align-items-center mb-4">
          <h2>
            <i className="fas fa-plus-circle me-2" style={{ color: 'var(--primary-green)' }}></i>
            新建村庄规划
          </h2>
          <Link href="/" className="btn btn-outline-secondary">
            <i className="fas fa-home me-2"></i>
            返回首页
          </Link>
        </div>

        {/* Step Indicator */}
        <div className="mb-4">
          <div className="progress" style={{ height: '30px' }}>
            <div
              className="progress-bar bg-success d-flex align-items-center justify-content-center"
              role="progressbar"
              style={{ width: step === 'form' ? '33%' : step === 'planning' ? '66%' : '100%' }}
            >
              {step === 'form' && '1. 填写信息'}
              {step === 'planning' && '2. 规划中'}
              {step === 'complete' && '3. 完成'}
            </div>
          </div>
        </div>

        {/* Step 1: Form */}
        {step === 'form' && (
          <div className="card">
            <div className="card-body">
              <h5 className="card-title mb-4">村庄信息</h5>

              {error && (
                <div className="alert alert-danger mb-3">
                  <i className="fas fa-exclamation-circle me-2"></i>
                  {error}
                  <button
                    className="btn-close float-end"
                    onClick={() => setError(null)}
                  ></button>
                </div>
              )}

              {/* Project Name */}
              <div className="mb-3">
                <label htmlFor="projectName" className="form-label">
                  项目名称 <span className="text-danger">*</span>
                </label>
                <input
                  type="text"
                  className="form-control"
                  id="projectName"
                  value={form.projectName}
                  onChange={(e) => setForm({ ...form, projectName: e.target.value })}
                  placeholder="例如：金田村乡村振兴规划"
                  disabled={loading}
                />
              </div>

              {/* File Upload */}
              <div className="mb-3">
                <label className="form-label">
                  村庄现状数据 <span className="text-danger">*</span>
                </label>
                <input
                  type="file"
                  className="form-control"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) handleFileUpload(file);
                  }}
                  disabled={loading}
                  accept=".txt,.md,.doc,.docx,.pdf"
                />
                {fileName && (
                  <small className="text-success mt-1 d-block">
                    <i className="fas fa-check-circle me-1"></i>
                    已上传: {fileName}
                  </small>
                )}
              </div>

              {/* Task Description */}
              <div className="mb-3">
                <label htmlFor="taskDescription" className="form-label">
                  规划任务描述
                </label>
                <textarea
                  className="form-control"
                  id="taskDescription"
                  rows={2}
                  value={form.taskDescription}
                  onChange={(e) => setForm({ ...form, taskDescription: e.target.value })}
                  placeholder="描述本次规划的主要任务和目标"
                  disabled={loading}
                />
              </div>

              {/* Constraints */}
              <div className="mb-3">
                <label htmlFor="constraints" className="form-label">
                  约束条件
                </label>
                <input
                  type="text"
                  className="form-control"
                  id="constraints"
                  value={form.constraints}
                  onChange={(e) => setForm({ ...form, constraints: e.target.value })}
                  placeholder="例如：生态优先、绿色发展"
                  disabled={loading}
                />
              </div>

              {/* Options */}
              <div className="mb-4">
                <div className="form-check form-switch mb-2">
                  <input
                    className="form-check-input"
                    type="checkbox"
                    id="stepMode"
                    checked={form.stepMode}
                    onChange={(e) => setForm({ ...form, stepMode: e.target.checked })}
                    disabled={loading}
                  />
                  <label className="form-check-label" htmlFor="stepMode">
                    分步执行 (每层完成后暂停审核)
                  </label>
                </div>
                <div className="form-check form-switch">
                  <input
                    className="form-check-input"
                    type="checkbox"
                    id="streamMode"
                    checked={form.streamMode}
                    onChange={(e) => setForm({ ...form, streamMode: e.target.checked })}
                    disabled={loading}
                  />
                  <label className="form-check-label" htmlFor="streamMode">
                    实时流式更新
                  </label>
                </div>
              </div>

              {/* Submit Button */}
              <button
                className="btn btn-success btn-lg w-100"
                onClick={handleStartPlanning}
                disabled={loading || !form.projectName.trim() || !form.villageData.trim()}
              >
                {loading ? (
                  <>
                    <span className="spinner-border spinner-border-sm me-2" role="status"></span>
                    创建中...
                  </>
                ) : (
                  <>
                    <i className="fas fa-play me-2"></i>
                    开始AI规划
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Planning */}
        {step === 'planning' && (
          <div className="card">
            <div className="card-body text-center py-5">
              <div className="spinner-border text-primary mb-3" role="status">
                <span className="visually-hidden">Loading...</span>
              </div>
              <h5>规划进行中...</h5>
              <p className="text-muted">任务ID: {taskId}</p>
              <button
                className="btn btn-outline-secondary mt-3"
                onClick={() => {
                  if (confirm('确定要取消吗？')) {
                    router.push('/');
                  }
                }}
              >
                取消任务
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Complete */}
        {step === 'complete' && (
          <div className="card">
            <div className="card-body text-center py-5">
              <div className="mb-4">
                <i
                  className="fas fa-check-circle"
                  style={{ fontSize: '4rem', color: 'var(--primary-green)' }}
                ></i>
              </div>
              <h5>规划完成！</h5>
              <p className="text-muted mb-4">村庄规划已成功生成</p>

              <div className="d-flex gap-2 justify-content-center">
                <button
                  className="btn btn-primary"
                  onClick={() => setShowCheckpointViewer(true)}
                >
                  <i className="fas fa-history me-2"></i>
                  查看检查点
                </button>
                <Link href="/" className="btn btn-outline-secondary">
                  <i className="fas fa-home me-2"></i>
                  返回首页
                </Link>
              </div>
            </div>
          </div>
        )}

        {/* Review Drawer */}
        {taskId && showReviewDrawer && (
          <ReviewDrawer
            isOpen={showReviewDrawer}
            taskId={taskId}
            onClose={() => setShowReviewDrawer(false)}
            onApprove={handleApproveReview}
            onReject={handleRejectReview}
            onRollback={handleRollbackCheckpoint}
          />
        )}

        {/* Checkpoint Viewer Modal */}
        {step === 'complete' && showCheckpointViewer && form.projectName && (
          <div
            className="checkpoint-viewer-modal"
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              width: '100%',
              height: '100%',
              backgroundColor: 'rgba(0, 0, 0, 0.5)',
              zIndex: 1100,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '1rem',
            }}
            onClick={() => setShowCheckpointViewer(false)}
          >
            <div
              className="checkpoint-viewer-content bg-white rounded shadow"
              style={{
                width: '100%',
                maxWidth: '1200px',
                height: 'calc(100vh - 2rem)',
                maxHeight: '800px',
                borderRadius: '0.5rem',
                display: 'flex',
                flexDirection: 'column',
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <CheckpointViewer
                villageName={form.projectName}
                onClose={() => setShowCheckpointViewer(false)}
                className="flex-fill"
              />
            </div>
          </div>
        )}
      </div>

      {/* Vertical Screen Adaptation Styles */}
      <style jsx global>{`
        @media (max-width: 768px) {
          .new-village-page {
            padding: 1rem !important;
          }

          .new-village-page .max-w-4xl {
            max-width: 100% !important;
          }

          .checkpoint-viewer-content {
            height: calc(100vh - 4rem) !important;
            margin: 0.5rem !important;
          }

          /* Review Drawer - Full screen on mobile */
          .drawer {
            width: 100% !important;
            max-width: 100% !important;
          }

          .drawer-header,
          .drawer-footer {
            padding: 0.75rem !important;
          }

          .drawer-body {
            padding: 0.75rem !important;
          }

          /* Stack buttons vertically on small screens */
          .d-flex.gap-2 {
            flex-direction: column;
          }

          .btn {
            width: 100%;
            margin-bottom: 0.5rem;
          }

          .btn:last-child {
            margin-bottom: 0;
          }
        }

        @media (max-width: 576px) {
          /* Extra small screens */
          .checkpoint-viewer-modal {
            padding: 0.5rem !important;
          }

          .checkpoint-viewer-content {
            height: 100vh !important;
            margin: 0 !important;
            borderRadius: 0 !important;
          }

          .checkpoint-footer {
            display: none;
          }

          .checkpoint-nav {
            padding: 0.5rem !important;
          }
        }
      `}</style>
    </div>
  );
}
