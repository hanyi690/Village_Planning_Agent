'use client';

import React, { useState } from 'react';

export interface DimensionOption {
  id: string;
  name: string;
  disabled?: boolean;
  detected?: boolean;
}

interface DimensionSelectorProps {
  dimensions: DimensionOption[];
  selectedDimensions: string[];
  onChange: (selected: string[]) => void;
  disabled?: boolean;
  autoDetected?: string[];
}

export default function DimensionSelector({
  dimensions,
  selectedDimensions,
  onChange,
  disabled = false,
  autoDetected = [],
}: DimensionSelectorProps) {
  const [selectAll, setSelectAll] = useState(false);

  const handleToggle = (dimensionId: string) => {
    if (disabled) return;

    const newSelected = selectedDimensions.includes(dimensionId)
      ? selectedDimensions.filter(id => id !== dimensionId)
      : [...selectedDimensions, dimensionId];

    onChange(newSelected);
    setSelectAll(newSelected.length === dimensions.filter(d => !d.disabled).length);
  };

  const handleToggleAll = () => {
    if (disabled) return;

    const availableDimensions = dimensions.filter(d => !d.disabled).map(d => d.id);
    const newSelected = selectAll ? [] : availableDimensions;

    onChange(newSelected);
    setSelectAll(!selectAll);
  };

  return (
    <div className="dimension-selector">
      <div className="d-flex justify-content-between align-items-center mb-2">
        <label className="form-label mb-0">
          <strong>选择需要修复的维度</strong>
          {autoDetected.length > 0 && (
            <span className="badge bg-info ms-2">
              AI已识别 {autoDetected.length} 个维度
            </span>
          )}
        </label>
        <button
          className="btn btn-sm btn-outline-secondary"
          type="button"
          onClick={handleToggleAll}
          disabled={disabled}
        >
          <i className={`fas ${selectAll ? 'fa-check-square' : 'fa-square'} me-1`}></i>
          {selectAll ? '取消全选' : '全选'}
        </button>
      </div>

      <div className="dimension-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '0.5rem' }}>
        {dimensions.map((dimension) => {
          const isSelected = selectedDimensions.includes(dimension.id);
          const isDetected = autoDetected.includes(dimension.id);

          return (
            <div
              key={dimension.id}
              className={`dimension-card ${isSelected ? 'selected' : ''} ${isDetected ? 'detected' : ''} ${dimension.disabled ? 'disabled' : ''}`}
              style={{
                border: '1px solid #dee2e6',
                borderRadius: '0.375rem',
                padding: '0.75rem',
                cursor: dimension.disabled ? 'not-allowed' : 'pointer',
                backgroundColor: isSelected ? 'var(--primary-green)' : (isDetected ? '#e7f5ff' : 'white'),
                opacity: dimension.disabled ? 0.6 : 1,
                transition: 'all 0.2s',
              }}
              onClick={() => handleToggle(dimension.id)}
            >
              <div className="d-flex align-items-center">
                <i
                  className={`fas ${isSelected ? 'fa-check-circle' : 'fa-circle'} me-2`}
                  style={{ color: isSelected ? 'white' : (isDetected ? 'var(--primary-green)' : '#6c757d') }}
                ></i>
                <div className="flex-grow-1">
                  <div className="dimension-name" style={{ fontWeight: 500, color: isSelected ? 'white' : 'inherit' }}>
                    {dimension.name}
                  </div>
                  {isDetected && !isSelected && (
                    <small className="text-muted" style={{ fontSize: '0.75rem' }}>
                      <i className="fas fa-robot me-1"></i>
                      AI识别
                    </small>
                  )}
                  {dimension.disabled && (
                    <small className="text-muted" style={{ fontSize: '0.75rem' }}>
                      <i className="fas fa-lock me-1"></i>
                      不可修复
                    </small>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {selectedDimensions.length > 0 && (
        <div className="mt-2">
          <small className="text-muted">
            已选择 <strong>{selectedDimensions.length}</strong> 个维度
          </small>
        </div>
      )}

      <style jsx>{`
        .dimension-card:hover:not(.disabled) {
          border-color: var(--primary-green);
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        .dimension-card.selected:hover {
          background-color: var(--primary-green);
          opacity: 0.9;
        }
      `}</style>
    </div>
  );
}

// Predefined dimension options
export const DIMENSION_OPTIONS: DimensionOption[] = [
  { id: 'industry', name: '产业规划' },
  { id: 'master_plan', name: '村庄总体规划' },
  { id: 'traffic', name: '道路交通规划' },
  { id: 'public_service', name: '公服设施规划' },
  { id: 'infrastructure', name: '基础设施规划' },
  { id: 'ecological', name: '生态绿地规划' },
  { id: 'disaster_prevention', name: '防震减灾规划' },
  { id: 'heritage', name: '历史文保规划' },
  { id: 'landscape', name: '村庄风貌指引' },
  { id: 'project_bank', name: '建设项目库' },
];
