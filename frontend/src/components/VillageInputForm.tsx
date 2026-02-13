'use client';

import { useState, FormEvent } from 'react';

export interface VillageInputData {
  projectName: string;
  taskDescription: string;
  constraints: string;
}

interface VillageInputFormProps {
  onSubmit: (data: VillageInputData) => void;
}

export default function VillageInputForm({ onSubmit }: VillageInputFormProps) {
  const [projectName, setProjectName] = useState('');
  const [taskDescription, setTaskDescription] = useState('');
  const [constraints, setConstraints] = useState('');

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();

    // Manual input validation
    if (!projectName.trim()) {
      alert('请输入村庄名称');
      return;
    }

    onSubmit({
      projectName: projectName.trim(),
      taskDescription: taskDescription.trim(),
      constraints: constraints.trim(),
    });
  };

  return (
    <form onSubmit={handleSubmit} className="w-100 p-3 p-md-4">
      {/* Header */}
      <div className="mb-4 pb-3 border-bottom text-center">
        <h3 className="h5 fw-bold d-flex align-items-center justify-content-center gap-2 mb-2">
          <span className="d-none d-sm-inline bg-success rounded-circle"
                style={{ width: '4px', height: '32px' }}></span>
          创建规划任务
        </h3>
        <p className="text-muted small">
          请填写以下基础信息，以便 AI 助手为您生成定制化方案。
        </p>
      </div>

      {/* Form Fields */}
      <div className="mb-4">
        {/* Manual Input Section */}
        <div className="mb-4">
          <h6 className="mb-3 fw-bold d-flex align-items-center gap-2">
            <span>✏️</span>
            填写村庄规划信息
          </h6>
        </div>


        {/* 1. Village Name */}
        <div className="mb-4 w-100">
          <label htmlFor="projectName"
                 className="form-label fw-bold d-flex align-items-center gap-2">
            <span>📍</span>
            村庄名称 <span className="text-danger">*</span>
          </label>
          <input
            id="projectName"
            type="text"
            className="form-control form-control-lg"
            style={{
              borderRadius: '12px',
              backgroundColor: '#f9fafb',
              border: '1px solid #e5e7eb'
            }}
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            placeholder="例如：杭州市余杭区李家村"
            required
          />
        </div>

        {/* 2. Task Description */}
        <div className="mb-4 w-100">
          <label htmlFor="taskDescription"
                 className="form-label fw-bold d-flex align-items-center gap-2">
            <span>📝</span>
            任务描述
          </label>
          <textarea
            id="taskDescription"
            className="form-control"
            rows={4}
            style={{
              borderRadius: '12px',
              backgroundColor: '#f9fafb',
              border: '1px solid #e5e7eb',
              resize: 'none'
            }}
            value={taskDescription}
            onChange={(e) => setTaskDescription(e.target.value)}
            placeholder="请描述本次规划的主要目标、重点改造区域以及发展愿景..."
          />
        </div>

        {/* 3. Constraints */}
        <div className="mb-4 w-100">
          <label htmlFor="constraints"
                 className="form-label fw-bold d-flex align-items-center gap-2">
            <span>⚙️</span>
            约束条件
          </label>
          <textarea
            id="constraints"
            className="form-control"
            rows={3}
            style={{
              borderRadius: '12px',
              backgroundColor: '#f9fafb',
              border: '1px solid #e5e7eb',
              resize: 'none'
            }}
            value={constraints}
            onChange={(e) => setConstraints(e.target.value)}
            placeholder="例如：预算需控制在 500 万以内；保留村口百年古树；用地指标限制..."
          />
        </div>
      </div>

      {/* Submit Button - Centered */}
      <div className="pt-4 d-flex justify-content-center">
        <button
          type="submit"
          className="btn btn-success btn-lg px-5 py-3 rounded-pill shadow-sm d-flex align-items-center gap-2"
        >
          <span className="fw-bold">提交</span>
          <span>🚀</span>
        </button>
      </div>
    </form>
  );
}
