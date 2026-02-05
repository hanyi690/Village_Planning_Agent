'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { villageApi } from '@/lib/api';
import MarkdownRenderer from './MarkdownRenderer';
import CheckpointSelector from './CheckpointSelector';
import CheckpointViewer from './CheckpointViewer';

interface ViewerSidePanelProps {
  villageName: string;
  session?: string;
  visible: boolean;
  activeTab: string;
  onTabChange: (tab: string) => void;
  referencedSection?: string;
  taskId?: string;
}

const LAYERS = [
  { id: 'layer_1_analysis', label: '现状分析', icon: 'fa-search' },
  { id: 'layer_2_concept', label: '规划思路', icon: 'fa-lightbulb' },
  { id: 'layer_3_detailed', label: '详细规划', icon: 'fa-project-diagram' },
] as const;

export default function ViewerSidePanel({
  villageName,
  session,
  visible,
  activeTab,
  onTabChange,
  referencedSection,
  taskId,
}: ViewerSidePanelProps) {
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCheckpointSelector, setShowCheckpointSelector] = useState(false);
  const [showCheckpointViewer, setShowCheckpointViewer] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);

  // Load content
  const loadContent = useCallback(async () => {
    if (!villageName || !activeTab) return;

    try {
      setLoading(true);
      setError(null);

      const data = await villageApi.getLayerContent(
        villageName,
        activeTab,
        session,
        undefined,
        'markdown'
      );

      setContent(data.content || '暂无内容');
    } catch (err: any) {
      console.error('[ViewerSidePanel] Failed to load content:', err);
      setError(err.message || '加载内容失败');
    } finally {
      setLoading(false);
    }
  }, [villageName, session, activeTab]);

  // Scroll to section
  const scrollToSection = useCallback((sectionName: string) => {
    if (!contentRef.current) return;

    const headings = contentRef.current.querySelectorAll('h1, h2, h3, h4, h5, h6');
    for (const heading of headings) {
      if (heading.textContent?.includes(sectionName)) {
        heading.scrollIntoView({ behavior: 'smooth', block: 'start' });

        // Add highlight effect
        const parent = heading.parentElement;
        if (parent) {
          parent.classList.add('highlight-section');
          setTimeout(() => {
            parent.classList.remove('highlight-section');
          }, 2000);
        }
        break;
      }
    }
  }, []);

  // Handle referenced section highlighting
  useEffect(() => {
    if (referencedSection) {
      scrollToSection(referencedSection);
    }
  }, [referencedSection, scrollToSection]);

  // Load content when dependencies change
  useEffect(() => {
    loadContent();
  }, [loadContent]);

  const handleTabChange = useCallback((tab: string) => {
    onTabChange(tab);
  }, [onTabChange]);

  const handleDownload = useCallback(() => {
    if (!content) return;

    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${villageName}_${activeTab}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [content, villageName, activeTab]);

  if (!visible) return null;

  return (
    <div className="viewer-side-panel" style={{ display: 'flex', flexDirection: 'column', height: '100%', backgroundColor: 'white' }}>
      {/* Header */}
      <div
        className="viewer-header"
        style={{
          padding: '1rem',
          borderBottom: '1px solid #dee2e6',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: '#f8f9fa',
        }}
      >
        <div className="d-flex align-items-center">
          <i className="fas fa-file-alt me-2" style={{ color: 'var(--primary-green)' }}></i>
          <div>
            <h6 className="mb-0">{villageName}</h6>
            <small className="text-muted">{LAYERS.find(l => l.id === activeTab)?.label || '文档'}</small>
          </div>
        </div>

        {/* Toolbar */}
        <div className="d-flex gap-2">
          <div className="dropdown">
            <button
              className="btn btn-sm btn-outline-secondary dropdown-toggle"
              type="button"
              onClick={() => setShowCheckpointSelector(!showCheckpointSelector)}
            >
              <i className="fas fa-history me-1"></i>
              版本
            </button>
            {showCheckpointSelector && (
              <div
                className="dropdown-menu show"
                style={{ position: 'absolute', right: 0, top: '100%', zIndex: 1000, minWidth: '300px' }}
              >
                <div className="p-2">
                  <button
                    className="dropdown-item"
                    type="button"
                    onClick={() => {
                      setShowCheckpointSelector(false);
                      setShowCheckpointViewer(true);
                    }}
                  >
                    <i className="fas fa-list me-2"></i>
                    查看所有检查点
                  </button>
                  <CheckpointSelector
                    villageName={villageName}
                    session={session}
                    onRollback={async (checkpointId) => {
                      console.log('Rollback to:', checkpointId);
                      setShowCheckpointSelector(false);
                    }}
                  />
                </div>
              </div>
            )}
          </div>

          <button
            className="btn btn-sm btn-outline-primary"
            onClick={handleDownload}
            title="下载当前内容"
          >
            <i className="fas fa-download"></i>
          </button>
        </div>
      </div>

      {/* Layer Tabs */}
      <div
        className="layer-tabs"
        style={{
          padding: '0.5rem 1rem',
          borderBottom: '1px solid #dee2e6',
          display: 'flex',
          gap: '0.5rem',
          overflowX: 'auto',
        }}
      >
        {LAYERS.map((layer) => (
          <button
            key={layer.id}
            className={`btn btn-sm ${activeTab === layer.id ? 'btn-primary' : 'btn-outline-secondary'}`}
            onClick={() => handleTabChange(layer.id)}
            style={{ whiteSpace: 'nowrap' }}
          >
            <i className={`fas ${layer.icon} me-1`}></i>
            {layer.label}
          </button>
        ))}
      </div>

      {/* Referenced Section Indicator */}
      {referencedSection && (
        <div
          className="reference-indicator"
          style={{
            padding: '0.5rem 1rem',
            backgroundColor: '#fff3cd',
            borderBottom: '1px solid #ffc107',
            fontSize: '0.875rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span>
            <i className="fas fa-highlighter me-2"></i>
            正在查看: {referencedSection}
          </span>
        </div>
      )}

      {/* Content */}
      <div
        ref={contentRef}
        className="viewer-content"
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '1.5rem',
          backgroundColor: 'white',
        }}
      >
        {loading && (
          <div className="text-center py-5">
            <div className="spinner-border text-primary" role="status">
              <span className="visually-hidden">Loading...</span>
            </div>
            <p className="text-muted mt-3">加载中...</p>
          </div>
        )}

        {error && (
          <div className="alert alert-danger" role="alert">
            <i className="fas fa-exclamation-circle me-2"></i>
            {error}
          </div>
        )}

        {!loading && !error && content && (
          <div className="markdown-content">
            <MarkdownRenderer content={content} />
          </div>
        )}

        {!loading && !error && !content && (
          <div className="text-center py-5 text-muted">
            <i className="fas fa-file-alt fa-3x mb-3" style={{ opacity: 0.3 }}></i>
            <p>暂无内容</p>
          </div>
        )}
      </div>

      {/* Footer */}
      <div
        className="chat-reference-footer"
        style={{
          padding: '0.5rem 1rem',
          borderTop: '1px solid #dee2e6',
          backgroundColor: '#f8f9fa',
          fontSize: '0.75rem',
          color: '#6c757d',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <i className="fas fa-comments me-2"></i>
        与对话同步 - 当前显示 {LAYERS.find(l => l.id === activeTab)?.label}
      </div>

      {/* Checkpoint Viewer Modal */}
      {showCheckpointViewer && (
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
            className="checkpoint-viewer-content"
            style={{
              backgroundColor: 'white',
              borderRadius: '0.5rem',
              width: '100%',
              maxWidth: '1200px',
              height: 'calc(100vh - 2rem)',
              maxHeight: '800px',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <CheckpointViewer
              villageName={villageName}
              onClose={() => setShowCheckpointViewer(false)}
              className="flex-fill"
            />
          </div>
        </div>
      )}

      {/* Styles */}
      <style jsx global>{`
        .highlight-section {
          animation: highlight-pulse 2s ease-in-out;
        }

        @keyframes highlight-pulse {
          0% {
            background-color: rgba(255, 193, 7, 0.3);
          }
          50% {
            background-color: rgba(255, 193, 7, 0.6);
          }
          100% {
            background-color: rgba(255, 193, 7, 0.3);
          }
        }

        .markdown-content h1,
        .markdown-content h2,
        .markdown-content h3,
        .markdown-content h4,
        .markdown-content h5,
        .markdown-content h6 {
          margin-top: 1.5rem;
          margin-bottom: 1rem;
          color: #2c3e50;
        }

        .markdown-content h1:first-child,
        .markdown-content h2:first-child {
          margin-top: 0;
        }
      `}</style>
    </div>
  );
}
