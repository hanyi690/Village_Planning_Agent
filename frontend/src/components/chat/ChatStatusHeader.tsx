'use client';

// ============================================
// ChatStatusHeader - 顶部状态显示组件
// ============================================

import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faLayerGroup } from '@fortawesome/free-solid-svg-icons';

interface ChatStatusHeaderProps {
  status: string;
  currentLayer: number | null;
}

// 状态配置映射
const STATUS_CONFIG: Record<string, { badgeClass: string; icon: string; text: string }> = {
  collecting: { badgeClass: 'status-badge-info', icon: '🔄', text: '执行中' },
  planning: { badgeClass: 'status-badge-info', icon: '🔄', text: '执行中' },
  paused: { badgeClass: 'status-badge-warning', icon: '⏸️', text: '等待审查' },
  revising: { badgeClass: 'status-badge-warning', icon: '🔧', text: '修复中' },
  completed: { badgeClass: 'status-badge-success', icon: '✅', text: '已完成' },
  failed: { badgeClass: 'status-badge-error', icon: '❌', text: '失败' },
};

const VISIBLE_STATUSES = ['collecting', 'planning', 'paused', 'revising'];

/**
 * ChatStatusHeader - 顶部状态指示器
 * 显示当前执行状态和层级信息
 */
export default function ChatStatusHeader({ status, currentLayer }: ChatStatusHeaderProps) {
  // 只在特定状态下显示
  if (!VISIBLE_STATUSES.includes(status)) {
    return null;
  }

  const config = STATUS_CONFIG[status] || {
    badgeClass: 'bg-gray-100 text-gray-700',
    icon: '💬',
    text: '就绪',
  };

  return (
    <div className="flex-shrink-0 border-b border-gray-200 bg-white p-3 shadow-sm">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center gap-2">
          <span className={`status-badge ${config.badgeClass}`}>
            <span className="text-base">{config.icon}</span>
            {config.text}
          </span>

          {currentLayer && (
            <span className="status-badge status-badge-success">
              <FontAwesomeIcon icon={faLayerGroup} className="icon-xs" />
              Layer {currentLayer}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
