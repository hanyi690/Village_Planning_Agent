'use client';

import { useState } from 'react';
import { faHistory, faLeaf, faPlus } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
// 核心补丁：防止图标在初始加载时巨大化
import '@fortawesome/fontawesome-svg-core/styles.css';

interface HeaderProps {
  taskId: string;
  onToggleHistory?: () => void;
  onNewTask?: () => void;
}

export default function Header({ taskId, onToggleHistory, onNewTask }: HeaderProps) {
  const [isHistoryHovered, setIsHistoryHovered] = useState(false);

  return (
    <header className="relative w-full h-12 flex items-center justify-between px-4 lg:px-6 bg-white/95 backdrop-blur-sm border-b border-gray-100 z-50">
      
      {/* 左侧：Logo 与 品牌名 */}
      <div className="flex items-center gap-2">
        <div className="flex items-center justify-center w-6 h-6 bg-green-100 rounded-md">
          <FontAwesomeIcon 
            icon={faLeaf} 
            className="text-green-600" 
            style={{ width: '12px', height: '12px' }} 
          />
        </div>
        <span className="text-sm font-semibold text-green-800 tracking-wide">
          村庄规划智能体
        </span>
        {taskId && taskId !== 'new' && (
          <span className="hidden sm:inline-block ml-2 px-2 py-0.5 bg-gray-100 text-[10px] text-gray-500 rounded font-mono">
            #{taskId.slice(0, 6)}
          </span>
        )}
      </div>

      {/* 右侧：操作按钮 (移除所有白色文字) */}
      <div className="flex items-center gap-3">
        
        {/* 新建按钮：改用浅绿背景+深绿文字 */}
        {onNewTask && (
          <button
            onClick={onNewTask}
            className="flex items-center gap-1.5 px-3 py-1 bg-green-50 border border-green-200 hover:bg-green-100 text-green-700 rounded-full transition-all group"
          >
            <FontAwesomeIcon 
              icon={faPlus} 
              className="text-green-600"
              style={{ width: '10px', height: '10px' }} 
            />
            <span className="text-xs font-medium">新建规划</span>
          </button>
        )}

        {/* 历史按钮：改用透明背景+灰色/绿色文字 */}
        {onToggleHistory && (
          <button
            onClick={onToggleHistory}
            onMouseEnter={() => setIsHistoryHovered(true)}
            onMouseLeave={() => setIsHistoryHovered(false)}
            className="flex items-center gap-1.5 px-3 py-1 bg-white border border-gray-200 hover:border-green-300 hover:bg-green-50 text-gray-600 hover:text-green-700 rounded-full transition-all group"
          >
            <FontAwesomeIcon 
              icon={faHistory} 
              className={`transition-transform duration-500 ${isHistoryHovered ? '-rotate-180' : ''}`}
              style={{ width: '12px', height: '12px' }}
            />
            <span className="text-xs font-medium">历史记录</span>
            
            {/* 状态小点 */}
            <span className="w-1.5 h-1.5 bg-green-500 rounded-full opacity-60 group-hover:opacity-100" />
          </button>
        )}

      </div>
    </header>
  );
}