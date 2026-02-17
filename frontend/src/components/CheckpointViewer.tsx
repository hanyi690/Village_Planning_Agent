'use client';

import React, { useState, useEffect } from 'react';
import { villageApi } from '@/lib/api';
import MarkdownRenderer from './MarkdownRenderer';
import { ChevronLeft, ChevronRight, X, Loader } from 'lucide-react';

interface Checkpoint {
  checkpoint_id: string;
  description: string;
  timestamp: string;
  layer: number;
}

interface CheckpointViewerProps {
  villageName: string;
  initialCheckpointId?: string;
  onClose?: () => void;
  className?: string;
}

export default function CheckpointViewer({
  villageName,
  initialCheckpointId,
  onClose,
  className = '',
}: CheckpointViewerProps) {
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedLayer, setSelectedLayer] = useState<number | 'all'>('all');

  // Load checkpoints list
  useEffect(() => {
    loadCheckpoints();
  }, [villageName]);

  // Load content when checkpoint or layer changes
  useEffect(() => {
    if (checkpoints.length > 0) {
      const checkpoint = checkpoints[currentIndex];
      if (checkpoint) {
        loadCheckpointContent(checkpoint.checkpoint_id);
      }
    }
  }, [currentIndex, checkpoints, selectedLayer]);

  const loadCheckpoints = async () => {
    try {
      const data = await villageApi.getCheckpoints(villageName);
      setCheckpoints(data.checkpoints || []);

      // Set initial index if provided
      if (initialCheckpointId) {
        const idx = data.checkpoints?.findIndex(cp => cp.checkpoint_id === initialCheckpointId);
        if (idx !== undefined && idx >= 0) {
          setCurrentIndex(idx);
        }
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load checkpoints');
    }
  };

  const loadCheckpointContent = async (checkpointId: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await villageApi.getCheckpoint(villageName, checkpointId);

      // Format content based on layer
      const layer = checkpoints[currentIndex]?.layer || 1;
      const formattedContent = formatCheckpointContent(data, layer);
      setContent(formattedContent);
    } catch (err: any) {
      setError(err.message || 'Failed to load checkpoint content');
    } finally {
      setLoading(false);
    }
  };

  const formatCheckpointContent = (checkpointData: any, layer: number): string => {
    // Extract relevant content based on layer
    const state = checkpointData.state || checkpointData;

    let layerContent = '';
    let layerTitle = '';

    switch (layer) {
      case 1:
        layerTitle = '现状分析';
        layerContent = state.analysis_report || state.layer_1_analysis || '';
        break;
      case 2:
        layerTitle = '规划思路';
        layerContent = state.planning_concept || state.layer_2_concept || '';
        break;
      case 3:
        layerTitle = '详细规划';
        layerContent = state.detailed_plan || state.layer_3_detailed || state.final_detailed_plan || '';
        break;
      default:
        layerContent = JSON.stringify(state, null, 2);
    }

    return `# ${villageName} - ${layerTitle} (检查点: ${checkpoints[currentIndex]?.description})

**时间**: ${checkpoints[currentIndex]?.timestamp}
**层级**: Layer ${layer}

---

${layerContent}
`;
  };

  const filteredCheckpoints = selectedLayer === 'all'
    ? checkpoints
    : checkpoints.filter(cp => cp.layer === selectedLayer);

  const currentCheckpoint = filteredCheckpoints[currentIndex];
  const canGoPrev = currentIndex > 0;
  const canGoNext = currentIndex < filteredCheckpoints.length - 1;

  const goPrev = () => {
    if (canGoPrev) setCurrentIndex(currentIndex - 1);
  };

  const goNext = () => {
    if (canGoNext) setCurrentIndex(currentIndex + 1);
  };

  if (checkpoints.length === 0 && !error) {
    return (
      <div className={`checkpoint-viewer ${className}`}>
        <div className="text-center py-5">
          <Loader className="spinner mx-auto mb-3" size={32} />
          <p>加载检查点...</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`checkpoint-viewer ${className}`} style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div className="checkpoint-header bg-light border-bottom p-3" style={{ flexShrink: 0 }}>
        <div className="d-flex justify-content-between align-items-center mb-2">
          <h6 className="mb-0">
            <i className="fas fa-history me-2" style={{ color: 'var(--primary-green)' }}></i>
            检查点查看器
          </h6>
          {onClose && (
            <button
              className="btn btn-sm btn-outline-secondary"
              onClick={onClose}
              type="button"
            >
              <X size={16} />
            </button>
          )}
        </div>

        {/* Layer Filter */}
        <div className="d-flex gap-2 align-items-center flex-wrap">
          <small className="text-muted">筛选:</small>
          <select
            className="form-select form-select-sm"
            style={{ width: 'auto' }}
            value={selectedLayer}
            onChange={(e) => {
              setSelectedLayer(e.target.value === 'all' ? 'all' : parseInt(e.target.value));
              setCurrentIndex(0);
            }}
          >
            <option value="all">全部层级</option>
            <option value="1">Layer 1 - 现状分析</option>
            <option value="2">Layer 2 - 规划思路</option>
            <option value="3">Layer 3 - 详细规划</option>
          </select>
          <small className="text-muted">
            {filteredCheckpoints.length} 个检查点
          </small>
        </div>
      </div>

      {/* Navigation */}
      <div className="checkpoint-nav border-bottom p-2" style={{ flexShrink: 0 }}>
        <div className="d-flex justify-content-between align-items-center">
          <button
            className="btn btn-sm btn-outline-primary"
            onClick={goPrev}
            disabled={!canGoPrev || loading}
          >
            <ChevronLeft size={16} className="me-1" />
            上一个
          </button>

          <div className="text-center" style={{ flex: 1 }}>
            <div className="fw-bold">
              {currentCheckpoint?.description || '检查点'}
            </div>
            <small className="text-muted">
              {currentIndex + 1} / {filteredCheckpoints.length}
            </small>
          </div>

          <button
            className="btn btn-sm btn-outline-primary"
            onClick={goNext}
            disabled={!canGoNext || loading}
          >
            下一个
            <ChevronRight size={16} className="ms-1" />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="checkpoint-content flex-fill p-3" style={{ overflowY: 'auto', flex: 1 }}>
        {error && (
          <div className="alert alert-danger" role="alert">
            <i className="fas fa-exclamation-circle me-2"></i>
            {error}
          </div>
        )}

        {loading && (
          <div className="text-center py-5">
            <div className="spinner-border text-primary" role="status">
              <span className="visually-hidden">Loading...</span>
            </div>
            <p className="mt-2">加载检查点内容...</p>
          </div>
        )}

        {!loading && !error && content && (
          <MarkdownRenderer content={content} />
        )}

        {!loading && !error && !content && (
          <div className="alert alert-info" role="alert">
            <i className="fas fa-info-circle me-2"></i>
            此检查点没有可用内容
          </div>
        )}
      </div>

      {/* Footer - Checkpoint List */}
      <div className="checkpoint-footer border-top p-3" style={{ flexShrink: 0, maxHeight: '200px', overflowY: 'auto' }}>
        <small className="text-muted mb-2 d-block">检查点列表:</small>
        <div className="list-group list-group-flush">
          {filteredCheckpoints.map((cp, idx) => (
            <button
              key={cp.checkpoint_id}
              className={`list-group-item list-group-item-action d-flex justify-content-between align-items-center ${idx === currentIndex ? 'active' : ''}`}
              onClick={() => setCurrentIndex(idx)}
              type="button"
            >
              <div>
                <div className="fw-bold">{cp.description}</div>
                <small className="text-muted">{cp.timestamp}</small>
              </div>
              <span className="badge bg-secondary">Layer {cp.layer}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
