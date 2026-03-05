'use client';

import { useState } from 'react';
import { faHistory, faLeaf, faPlus, faDatabase } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import '@fortawesome/fontawesome-svg-core/styles.css';

interface HeaderProps {
  taskId: string;
  onToggleHistory?: () => void;
  onNewTask?: () => void;
  onOpenKnowledge?: () => void;
}

export default function Header({ taskId, onToggleHistory, onNewTask, onOpenKnowledge }: HeaderProps) {
  const [isHistoryHovered, setIsHistoryHovered] = useState(false);

  return (
    <header className="relative w-full h-14 flex items-center justify-between px-4 lg:px-6 bg-[#1a1a1a]/95 backdrop-blur-xl border-b border-[#2d2d2d] z-50">
      
      {/* 左侧：Logo 与 品牌名 */}
      <div className="flex items-center gap-3">
        {/* Logo with gradient glow */}
        <div className="relative flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-br from-green-500/20 to-green-600/10 border border-green-500/30">
          <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-green-500 to-green-600 opacity-20 blur-sm" />
          <FontAwesomeIcon 
            icon={faLeaf} 
            className="text-green-400 relative z-10"
            style={{ width: '16px', height: '16px' }} 
          />
        </div>
        
        {/* Brand name with gradient text */}
        <div className="flex flex-col">
          <span className="text-base font-semibold bg-gradient-to-r from-green-400 to-green-500 bg-clip-text text-transparent tracking-wide">
            村庄规划智能体
          </span>
        </div>
        
        {/* Task ID badge */}
        {taskId && taskId !== 'new' && (
          <span className="hidden sm:inline-flex items-center gap-1.5 ml-2 px-2.5 py-1 bg-[#2d2d2d] text-xs text-zinc-400 rounded-full font-mono border border-[#3f3f46]">
            <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" />
            #{taskId.slice(0, 6)}
          </span>
        )}
      </div>

      {/* 右侧：操作按钮 */}
      <div className="flex items-center gap-2">
        
        {/* 知识库按钮 */}
        {onOpenKnowledge && (
          <button
            onClick={onOpenKnowledge}
            className="group relative flex items-center gap-2 px-4 py-2 bg-[#2d2d2d] border border-[#3f3f46] hover:border-blue-500/50 hover:bg-blue-500/10 text-zinc-300 hover:text-blue-400 rounded-full transition-all duration-200"
          >
            <FontAwesomeIcon 
              icon={faDatabase} 
              className="text-blue-400 group-hover:scale-110 transition-transform"
              style={{ width: '14px', height: '14px' }} 
            />
            <span className="text-sm font-medium hidden sm:inline">知识库</span>
          </button>
        )}

        {/* 新建按钮 */}
        {onNewTask && (
          <button
            onClick={onNewTask}
            className="group relative flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-green-600 to-green-500 hover:from-green-500 hover:to-green-400 text-white rounded-full transition-all duration-200 shadow-lg shadow-green-500/20 hover:shadow-green-500/30"
          >
            <FontAwesomeIcon 
              icon={faPlus} 
              className="transition-transform group-hover:rotate-90"
              style={{ width: '12px', height: '12px' }} 
            />
            <span className="text-sm font-medium hidden sm:inline">新建规划</span>
          </button>
        )}

        {/* 历史按钮 */}
        {onToggleHistory && (
          <button
            onClick={onToggleHistory}
            onMouseEnter={() => setIsHistoryHovered(true)}
            onMouseLeave={() => setIsHistoryHovered(false)}
            className="group flex items-center gap-2 px-4 py-2 bg-[#2d2d2d] border border-[#3f3f46] hover:border-zinc-500 hover:bg-[#333] text-zinc-300 hover:text-white rounded-full transition-all duration-200"
          >
            <FontAwesomeIcon 
              icon={faHistory} 
              className={`transition-transform duration-500 ${isHistoryHovered ? '-rotate-180' : ''}`}
              style={{ width: '14px', height: '14px' }}
            />
            <span className="text-sm font-medium hidden sm:inline">历史记录</span>
          </button>
        )}

      </div>
    </header>
  );
}
