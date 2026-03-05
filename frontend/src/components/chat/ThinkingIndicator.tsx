'use client';

/**
 * ThinkingIndicator Component - Gemini Dark Style
 * 思考状态指示器 - 多状态动画反馈
 */

import React from 'react';

export type ThinkingState =
  | 'analyzing'
  | 'generating'
  | 'reviewing'
  | 'processing'
  | 'waiting';

export interface ThinkingIndicatorProps {
  state: ThinkingState;
  message?: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
  showProgress?: boolean;
  progress?: number;
}

/**
 * 状态配置 - Gemini 深色主题
 */
const STATE_CONFIG: Record<
  ThinkingState,
  {
    icon: React.ReactNode;
    label: string;
    gradient: string;
    glowColor: string;
  }
> = {
  analyzing: {
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
    ),
    label: '分析中',
    gradient: 'from-blue-500 to-cyan-500',
    glowColor: 'rgba(59, 130, 246, 0.4)',
  },
  generating: {
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
      </svg>
    ),
    label: '生成中',
    gradient: 'from-purple-500 to-pink-500',
    glowColor: 'rgba(168, 85, 247, 0.4)',
  },
  reviewing: {
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
      </svg>
    ),
    label: '审查中',
    gradient: 'from-orange-500 to-amber-500',
    glowColor: 'rgba(249, 115, 22, 0.4)',
  },
  processing: {
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
    label: '处理中',
    gradient: 'from-green-500 to-emerald-500',
    glowColor: 'rgba(34, 197, 94, 0.4)',
  },
  waiting: {
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    label: '等待中',
    gradient: 'from-zinc-400 to-zinc-500',
    glowColor: 'rgba(161, 161, 170, 0.3)',
  },
};

/**
 * 尺寸配置
 */
const SIZE_CONFIG: Record<
  'sm' | 'md' | 'lg',
  {
    padding: string;
    iconSize: string;
    textSize: string;
  }
> = {
  sm: {
    padding: 'px-3 py-2',
    iconSize: 'w-4 h-4',
    textSize: 'text-xs',
  },
  md: {
    padding: 'px-4 py-3',
    iconSize: 'w-5 h-5',
    textSize: 'text-sm',
  },
  lg: {
    padding: 'px-5 py-4',
    iconSize: 'w-6 h-6',
    textSize: 'text-base',
  },
};

/**
 * 思考指示器组件 - Gemini 风格
 */
export default function ThinkingIndicator({
  state,
  message,
  size = 'md',
  className = '',
  showProgress = false,
  progress = 0,
}: ThinkingIndicatorProps) {
  const config = STATE_CONFIG[state];
  const sizeConfig = SIZE_CONFIG[size];

  return (
    <div className={`flex items-center gap-3 ${sizeConfig.padding} rounded-xl bg-[#1e1e1e] border border-[#2d2d2d] ${className}`}>
      {/* 动画图标容器 */}
      <div className="relative">
        {/* 背景光晕 */}
        <div 
          className={`absolute inset-0 bg-gradient-to-r ${config.gradient} rounded-full blur-md opacity-30 animate-pulse`}
          style={{ transform: 'scale(1.5)' }}
        />
        
        {/* 图标 */}
        <div className={`relative p-2 rounded-full bg-gradient-to-r ${config.gradient} text-white`}>
          <div className="animate-spin">
            {React.cloneElement(config.icon as React.ReactElement, {
              className: sizeConfig.iconSize
            })}
          </div>
        </div>
      </div>

      {/* 状态文本 */}
      <div className="flex-1 min-w-0">
        <div className={`font-medium text-white ${sizeConfig.textSize}`}>
          {config.label}
        </div>
        {message && (
          <div className={`text-zinc-400 ${sizeConfig.textSize} mt-0.5 truncate`}>
            {message}
          </div>
        )}

        {/* 进度条 */}
        {showProgress && (
          <div className="mt-2 h-1 bg-[#2d2d2d] rounded-full overflow-hidden">
            <div
              className={`h-full bg-gradient-to-r ${config.gradient} rounded-full transition-all duration-300`}
              style={{ width: `${progress}%` }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * 紧凑型思考指示器
 */
export function CompactThinkingIndicator({
  state,
  className = '',
}: {
  state: ThinkingState;
  className?: string;
}) {
  const config = STATE_CONFIG[state];

  return (
    <div className={`inline-flex items-center gap-2 px-2.5 py-1.5 rounded-full bg-[#1e1e1e] border border-[#2d2d2d] ${className}`}>
      <div className={`animate-spin ${config.gradient.replace('from-', 'text-').split(' ')[0]}`}>
        {config.icon}
      </div>
      <span className="text-xs text-zinc-300">{config.label}</span>
    </div>
  );
}

/**
 * 波动型思考指示器 - Gemini 风格
 */
export function WaveThinkingIndicator({
  message = '思考中...',
  className = '',
}: {
  message?: string;
  className?: string;
}) {
  return (
    <div className={`inline-flex items-center gap-3 px-4 py-2.5 rounded-full bg-[#1e1e1e] border border-[#2d2d2d] ${className}`}>
      {/* 波动点动画 */}
      <div className="flex items-center gap-1">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="w-2 h-2 bg-green-400 rounded-full animate-bounce"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>

      {message && (
        <span className="text-sm text-zinc-300">
          {message}
        </span>
      )}
    </div>
  );
}