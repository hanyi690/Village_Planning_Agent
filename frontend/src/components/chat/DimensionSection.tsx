'use client';

/**
 * DimensionSection - Single collapsible dimension card component
 * 单个可折叠维度卡片组件
 */

import { useState } from 'react';
import { ParsedSubsection } from '@/lib/layerReportParser';
import MarkdownRenderer from '../MarkdownRenderer';

interface DimensionSectionProps {
  name: string;
  content: string;
  icon: string;
  subsections?: ParsedSubsection[];
  defaultExpanded?: boolean;
  onCopy?: () => void;
  onExport?: () => void;
}

export default function DimensionSection({
  name,
  content,
  icon,
  subsections = [],
  defaultExpanded = false,
  onCopy,
  onExport,
}: DimensionSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div
      className={`section-card ${expanded ? 'expanded' : ''}`}
      style={{
        border: '1px solid #c8e6c9',
        background: 'white',
        marginBottom: '15px',
        borderRadius: '8px',
        transition: 'all 0.3s ease',
        overflow: 'hidden',
        boxShadow: '0 2px 6px rgba(0,0,0,0.03)',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = 'translateY(-2px)';
        e.currentTarget.style.boxShadow = '0 5px 15px rgba(0,0,0,0.08)';
        e.currentTarget.style.borderColor = '#8bc34a';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = 'translateY(0)';
        e.currentTarget.style.boxShadow = '0 2px 6px rgba(0,0,0,0.03)';
        e.currentTarget.style.borderColor = '#c8e6c9';
      }}
    >
      {/* Header */}
      <div
        className="section-header"
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: '12px 20px',
          cursor: 'pointer',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: '#e8f5e9',
          transition: 'background 0.3s ease',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = 'linear-gradient(90deg, #e8f5e9, #d0efd0)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = '#e8f5e9';
        }}
      >
        <h4 className="section-title" style={{ margin: 0, color: '#1b5e20' }}>
          <i
            className={`fas ${icon}`}
            style={{
              color: '#2e7d32',
              fontSize: '1.1rem',
              marginRight: '10px',
            }}
          />
          {name}
        </h4>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {/* Action buttons */}
          <div
            className="dimension-actions"
            style={{
              display: 'flex',
              gap: '8px',
              opacity: 0,
              transition: 'opacity 0.2s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.opacity = '1';
            }}
          >
            {onCopy && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onCopy();
                }}
                className="dimension-action-btn"
                style={{
                  background: '#f5f5f5',
                  border: 'none',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  color: '#666',
                  transition: 'all 0.2s ease',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = '#e8f5e9';
                  e.currentTarget.style.color = '#2e7d32';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = '#f5f5f5';
                  e.currentTarget.style.color = '#666';
                }}
                title="复制内容"
              >
                <i className="fas fa-copy" />
              </button>
            )}
            {onExport && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onExport();
                }}
                className="dimension-action-btn"
                style={{
                  background: '#f5f5f5',
                  border: 'none',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  color: '#666',
                  transition: 'all 0.2s ease',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = '#e8f5e9';
                  e.currentTarget.style.color = '#2e7d32';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = '#f5f5f5';
                  e.currentTarget.style.color = '#666';
                }}
                title="导出"
              >
                <i className="fas fa-download" />
              </button>
            )}
          </div>
          <i
            className={`fas fa-chevron-${expanded ? 'up' : 'down'} chevron-icon`}
            style={{
              transition: 'transform 0.3s ease',
            }}
          />
        </div>
      </div>

      {/* Content */}
      <div
        className="section-content"
        style={{
          padding: expanded ? '15px 20px' : '0 20px',
          maxHeight: expanded ? '5000px' : '0',
          overflow: expanded ? 'auto' : 'hidden',
          transition: 'max-height 0.4s ease, padding 0.4s ease',
          background: 'white',
        }}
      >
        {/* Render subsections if available, otherwise render full content */}
        {subsections.length > 0 ? (
          subsections.map((subsection, index) => (
            <div
              key={index}
              className="subsection"
              style={{
                margin: '12px 0',
                padding: '10px 0 10px 15px',
                borderLeft: '2px solid #c8e6c9',
              }}
            >
              <div
                className="subsection-title"
                style={{
                  fontWeight: 600,
                  color: '#2e7d32',
                  marginBottom: '8px',
                  fontSize: '0.95rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}
              >
                <i className="fas fa-caret-right" style={{ fontSize: '0.8rem' }} />
                {subsection.title}
              </div>
              <div
                className="markdown-content"
                style={{
                  color: '#666',
                  lineHeight: '1.7',
                  fontSize: '0.95rem',
                }}
              >
                <MarkdownRenderer content={subsection.content} />
              </div>
            </div>
          ))
        ) : (
          <div
            className="markdown-content"
            style={{
              color: '#666',
              lineHeight: '1.7',
              fontSize: '0.95rem',
            }}
          >
            <MarkdownRenderer content={content} />
          </div>
        )}
      </div>
    </div>
  );
}
