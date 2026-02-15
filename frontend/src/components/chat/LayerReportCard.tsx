'use client';

/**
 * LayerReportCard - Complete layer report card with collapsible dimensions
 * 在侧边面板中渲染完整的 layer 报告
 */

import { useState, useMemo } from 'react';
import { ParsedDimension, parseLayerReport } from '@/lib/layerReportParser';
import DimensionSection from './DimensionSection';

interface LayerReportCardProps {
  layerNumber: number;
  content: string; // Full markdown report
  dimensions?: ParsedDimension[];
  mode?: 'chat' | 'sidebar';  // NEW: 区分显示模式
  defaultExpanded?: boolean;
  maxHeight?: string;        // NEW: 聊天模式下限制高度
  showExpandAll?: boolean;   // NEW: 是否显示全局展开按钮
  onOpenInSidebar?: () => void;  // NEW: 跳转到侧边栏
  onToggleAll?: (expand: boolean) => void;  // NEW: 展开/折叠全部
  isActive?: boolean;  // NEW: 是否为当前活跃层
  hasStreamingDimensions?: boolean;  // NEW: 是否有流式维度内容
}

export default function LayerReportCard({
  layerNumber,
  content,
  dimensions: propDimensions,
  mode = 'sidebar',
  defaultExpanded,
  maxHeight,
  showExpandAll,
  onOpenInSidebar,
  onToggleAll,
  isActive = false,  // NEW: 默认为非活跃层
  hasStreamingDimensions = false,  // NEW: 是否有流式维度内容
}: LayerReportCardProps) {
  // ✅ 修复：活跃层默认展开，非活跃层默认折叠
  // ✅ 新增：有流式维度内容时默认展开
  const actualDefaultExpanded = defaultExpanded ?? (mode === 'sidebar' || isActive || hasStreamingDimensions);
  const actualMaxHeight = maxHeight ?? (mode === 'chat' ? 'none' : 'none');
  const actualShowExpandAll = showExpandAll ?? (mode === 'sidebar');

  const [allExpanded, setAllExpanded] = useState(false);
  const [localExpanded, setLocalExpanded] = useState(actualDefaultExpanded);

  // ✅ 使用传入的 dimensions prop，或解析 content
  const dimensions = useMemo(() => {
    // 如果有 propDimensions，使用它
    if (propDimensions && propDimensions.length > 0) {
      return propDimensions;
    }
    
    // 回退到解析 content
    return parseLayerReport(content);
  }, [content, propDimensions]);

  const handleCopyDimension = (dimensionName: string, dimensionContent: string) => {
    const textToCopy = `## ${dimensionName}\n\n${dimensionContent}`;
    navigator.clipboard.writeText(textToCopy);
    // TODO: Show toast notification
  };

  const handleExportDimension = (dimensionName: string, dimensionContent: string) => {
    const blob = new Blob([`## ${dimensionName}\n\n${dimensionContent}`], {
      type: 'text/markdown',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `layer${layerNumber}_${dimensionName}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleExpandAll = () => {
    setAllExpanded(true);
    onToggleAll?.(true);
  };

  const handleCollapseAll = () => {
    setAllExpanded(false);
    onToggleAll?.(false);
  };

  const handleToggleExpanded = () => {
    setLocalExpanded(prev => !prev);
  };

  if (dimensions.length === 0) {
    return (
      <div
        style={{
          background: 'linear-gradient(135deg, #f5f9f5, #e8f5e9)',
          borderRadius: '10px',
          padding: '20px',
          margin: '1.5rem 0',
          textAlign: 'center',
          color: '#666',
        }}
      >
        <i className="fas fa-file-alt" style={{ fontSize: '2rem', marginBottom: '10px' }} />
        <p>暂无维度数据</p>
      </div>
    );
  }

  return (
    <div
      className={`layer-report-container layer-report-card-${mode}`}
      style={{
        background: 'linear-gradient(135deg, #f5f9f5, #e8f5e9)',
        borderRadius: '10px',
        padding: '20px',
        margin: '1.5rem 0',
        maxHeight: mode === 'chat' && !localExpanded ? actualMaxHeight : 'none',
        // ✅ 修复：当展开时，允许滚动
        overflow: localExpanded ? 'visible' : 'hidden',
        position: 'relative',
        // ✅ 新增：非活跃层降低不透明度
        ...(isActive ? {} : { opacity: 0.7 }),
      }}
    >
      {/* ✅ 新增：非活跃层添加标识 */}
      {!isActive && mode === 'chat' && (
        <div style={{
          position: 'absolute',
          top: '10px',
          right: '10px',
          background: 'rgba(0,0,0,0.05)',
          padding: '2px 8px',
          borderRadius: '4px',
          fontSize: '0.75rem',
          color: '#666',
          zIndex: 1,
        }}>
          已完成
        </div>
      )}

      {/* Header - 聊天流简化，侧边栏完整 */}
      {mode === 'chat' ? (
        <div
          style={{
            marginBottom: '16px',
            paddingBottom: '12px',
            borderBottom: '1px solid #c8e6c9',
          }}
        >
          <h3
            style={{
              margin: 0,
              color: '#1b5e20',
              fontSize: '1.1rem',
              fontWeight: 600,
            }}
          >
            <i className="fas fa-layer-group" style={{ marginRight: '8px' }} />
            Layer {layerNumber} 报告
          </h3>
          <p
            style={{
              margin: '4px 0 0 0',
              color: '#666',
              fontSize: '0.85rem',
            }}
          >
            {dimensions.length} 个维度 · {content.length} 字
          </p>
        </div>
      ) : (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '20px',
            paddingBottom: '15px',
            borderBottom: '1px solid #c8e6c9',
          }}
        >
          <div>
            <h3
              style={{
                margin: 0,
                color: '#1b5e20',
                fontSize: '1.3rem',
                fontWeight: 600,
              }}
            >
              <i className="fas fa-layer-group" style={{ marginRight: '10px' }} />
              Layer {layerNumber} 完整报告
            </h3>
            <p
              style={{
                margin: '5px 0 0 0',
                color: '#666',
                fontSize: '0.9rem',
              }}
            >
              共 {dimensions.length} 个维度 · {content.length} 字
            </p>
          </div>

          {/* Action buttons - 只在侧边栏模式显示 */}
          {actualShowExpandAll && (
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={handleExpandAll}
                style={{
                  background: 'linear-gradient(135deg, #2e7d32, #1b5e20)',
                  color: 'white',
                  border: 'none',
                  padding: '8px 16px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.9rem',
                  fontWeight: 500,
                  transition: 'all 0.3s ease',
                  boxShadow: '0 2px 6px rgba(46, 125, 50, 0.3)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = 'translateY(-2px)';
                  e.currentTarget.style.boxShadow = '0 4px 10px rgba(46, 125, 50, 0.4)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = 'translateY(0)';
                  e.currentTarget.style.boxShadow = '0 2px 6px rgba(46, 125, 50, 0.3)';
                }}
              >
                <i className="fas fa-expand-alt" style={{ marginRight: '6px' }} />
                展开全部
              </button>
              <button
                onClick={handleCollapseAll}
                style={{
                  background: 'white',
                  color: '#2e7d32',
                  border: '1px solid #2e7d32',
                  padding: '8px 16px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.9rem',
                  fontWeight: 500,
                  transition: 'all 0.3s ease',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = '#e8f5e9';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'white';
                }}
              >
                <i className="fas fa-compress-alt" style={{ marginRight: '6px' }} />
                折叠全部
              </button>
            </div>
          )}
        </div>
      )}

      {/* Dimension sections */}
      <div
        style={{
          // ✅ 修复：只在折叠时限制高度，展开时不限制但设置最大高度防止无限展开
          maxHeight: localExpanded ? '80vh' : (mode === 'chat' && !localExpanded ? actualMaxHeight : 'none'),
          // ✅ 修复：始终保持 auto 滚动
          overflow: 'auto',
        }}
      >
        {dimensions.map((dimension, index) => (
          <DimensionSection
            key={index}
            name={dimension.name}
            content={dimension.content}
            icon={dimension.icon}
            subsections={dimension.subsections}
            defaultExpanded={allExpanded || actualDefaultExpanded}
            onCopy={() => handleCopyDimension(dimension.name, dimension.content)}
            onExport={() => handleExportDimension(dimension.name, dimension.content)}
          />
        ))}
      </div>

      {/* 聊天流模式：展开全文按钮 */}
      {mode === 'chat' && !localExpanded && (
        <div
          style={{
            position: 'absolute',
            bottom: 0,
            left: 0,
            right: 0,
            padding: '20px',
            background: 'linear-gradient(to bottom, transparent, rgba(245, 249, 245, 0.95), #f5f9f5)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '10px',
          }}
        >
          <button
            onClick={handleToggleExpanded}
            style={{
              background: 'white',
              color: '#2e7d32',
              border: '1px solid #2e7d32',
              padding: '8px 20px',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '0.9rem',
              fontWeight: 500,
              transition: 'all 0.3s ease',
              boxShadow: '0 2px 8px rgba(46, 125, 50, 0.2)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = '#e8f5e9';
              e.currentTarget.style.transform = 'translateY(-2px)';
              e.currentTarget.style.boxShadow = '0 4px 12px rgba(46, 125, 50, 0.3)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'white';
              e.currentTarget.style.transform = 'translateY(0)';
              e.currentTarget.style.boxShadow = '0 2px 8px rgba(46, 125, 50, 0.2)';
            }}
          >
            <i className="fas fa-chevron-down" style={{ marginRight: '6px' }} />
            展开全文
          </button>

          {onOpenInSidebar && (
            <button
              onClick={onOpenInSidebar}
              className="btn-open-in-sidebar"
              style={{
                background: 'white',
                color: '#2e7d32',
                border: '1px solid #2e7d32',
                padding: '8px 16px',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '0.85rem',
                transition: 'all 0.3s ease',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = '#e8f5e9';
                e.currentTarget.style.transform = 'translateY(-2px)';
                e.currentTarget.style.boxShadow = '0 4px 10px rgba(46, 125, 50, 0.3)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'white';
                e.currentTarget.style.transform = 'translateY(0)';
                e.currentTarget.style.boxShadow = 'none';
              }}
            >
              <i className="fas fa-external-link-alt" />
              在侧边栏查看
            </button>
          )}
        </div>
      )}
    </div>
  );
}
