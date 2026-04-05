'use client';

import { useState } from 'react';
import { faHistory, faLeaf, faPlus, faDatabase } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
// 核心补丁：防止图标在初始加载时巨大化
import '@fortawesome/fontawesome-svg-core/styles.css';

interface HeaderProps {
  taskId: string;
  onToggleHistory?: () => void;
  onNewTask?: () => void;
  onOpenKnowledge?: () => void;
}

export default function Header({
  taskId,
  onToggleHistory,
  onNewTask,
  onOpenKnowledge,
}: HeaderProps) {
  const [isHistoryHovered, setIsHistoryHovered] = useState(false);

  return (
    <header className="fixed top-0 left-0 right-0 z-50 w-full h-14 flex items-center justify-between px-4 lg:px-6 bg-white/80 backdrop-blur-md border-b border-gray-200">
      {/* 左侧：Logo 与 品牌名 */}
      <div className="flex items-center gap-2.5">
        <div className="flex items-center justify-center w-8 h-8 bg-gradient-to-br from-cyan-500 to-teal-600 rounded-lg shadow-sm">
          <FontAwesomeIcon
            icon={faLeaf}
            className="text-white"
            style={{ width: '14px', height: '14px' }}
          />
        </div>
        <span className="text-base font-semibold text-cyan-900 tracking-tight">村庄规划智能体</span>
        {taskId && taskId !== 'new' && (
          <span className="hidden sm:inline-block ml-2 px-2 py-0.5 bg-cyan-50 text-cyan-700 text-xs rounded-md font-medium border border-cyan-100">
            #{taskId.slice(0, 6)}
          </span>
        )}
      </div>

      {/* 右侧：操作按钮 */}
      <div className="flex items-center gap-2.5">
        {/* 知识库按钮 */}
        {onOpenKnowledge && (
          <button
            onClick={onOpenKnowledge}
            className="flex items-center gap-2 px-3.5 py-2 bg-blue-50 border border-blue-200 hover:bg-blue-100 hover:border-blue-300 text-blue-700 rounded-lg transition-all duration-200 group shadow-sm hover:shadow"
          >
            <FontAwesomeIcon
              icon={faDatabase}
              className="text-blue-600 group-hover:text-blue-700"
              style={{ width: '12px', height: '12px' }}
            />
            <span className="text-sm font-medium">知识库</span>
          </button>
        )}

        {/* 新建按钮：改用浅绿背景+深绿文字 */}
        {onNewTask && (
          <button
            onClick={onNewTask}
            className="flex items-center gap-2 px-3.5 py-2 bg-cyan-50 border border-cyan-200 hover:bg-cyan-100 hover:border-cyan-300 text-cyan-700 rounded-lg transition-all duration-200 group shadow-sm hover:shadow"
          >
            <FontAwesomeIcon
              icon={faPlus}
              className="text-cyan-600 group-hover:text-cyan-700"
              style={{ width: '12px', height: '12px' }}
            />
            <span className="text-sm font-medium">新建规划</span>
          </button>
        )}

        {/* 历史按钮：改用透明背景+灰色/绿色文字 */}
        {onToggleHistory && (
          <button
            onClick={onToggleHistory}
            onMouseEnter={() => setIsHistoryHovered(true)}
            onMouseLeave={() => setIsHistoryHovered(false)}
            className="flex items-center gap-2 px-3.5 py-2 bg-white border border-gray-200 hover:border-cyan-300 hover:bg-cyan-50 text-gray-600 hover:text-cyan-700 rounded-lg transition-all duration-200 group shadow-sm hover:shadow"
          >
            <FontAwesomeIcon
              icon={faHistory}
              className={`transition-transform duration-500 ${isHistoryHovered ? '-rotate-180' : ''}`}
              style={{ width: '12px', height: '12px' }}
            />
            <span className="text-sm font-medium">历史记录</span>

            {/* 状态小点 */}
            <span className="w-2 h-2 bg-cyan-500 rounded-full opacity-60 group-hover:opacity-100 transition-opacity" />
          </button>
        )}
      </div>
    </header>
  );
}
