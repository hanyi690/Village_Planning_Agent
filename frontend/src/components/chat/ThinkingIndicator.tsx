'use client';

/**
 * ThinkingIndicator Component
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
 * 状态配置
 */
const STATE_CONFIG: Record<
  ThinkingState,
  {
    icon: string;
    label: string;
    color: string;
    bgColor: string;
  }
> = {
  analyzing: {
    icon: 'fa-microscope',
    label: '分析中',
    color: 'text-blue-500',
    bgColor: 'bg-blue-50',
  },
  generating: {
    icon: 'fa-wand-magic-sparkles',
    label: '生成中',
    color: 'text-purple-500',
    bgColor: 'bg-purple-50',
  },
  reviewing: {
    icon: 'fa-magnifying-glass-chart',
    label: '审查中',
    color: 'text-orange-500',
    bgColor: 'bg-orange-50',
  },
  processing: {
    icon: 'fa-gears',
    label: '处理中',
    color: 'text-green-500',
    bgColor: 'bg-green-50',
  },
  waiting: {
    icon: 'fa-hourglass-half',
    label: '等待中',
    color: 'text-gray-600',
    bgColor: 'bg-gray-50',
  },
};

/**
 * 尺寸配置
 */
const SIZE_CONFIG: Record<
  'sm' | 'md' | 'lg',
  {
    containerSize: string;
    iconSize: string;
    textSize: string;
  }
> = {
  sm: {
    containerSize: 'p-2',
    iconSize: 'text-sm',
    textSize: 'text-xs',
  },
  md: {
    containerSize: 'p-3',
    iconSize: 'text-base',
    textSize: 'text-sm',
  },
  lg: {
    containerSize: 'p-4',
    iconSize: 'text-xl',
    textSize: 'text-base',
  },
};

/**
 * 思考指示器组件
 *
 * @example
 * <ThinkingIndicator state="analyzing" message="正在分析村庄数据..." />
 *
 * @example
 * <ThinkingIndicator
 *   state="generating"
 *   message="生成规划方案中..."
 *   size="lg"
 *   showProgress
 *   progress={65}
 * />
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
    <div
      className={`thinking-indicator ${config.bgColor} ${config.color} ${sizeConfig.containerSize} rounded-lg ${className}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.75rem',
      }}
    >
      {/* 动画图标 */}
      <div className="thinking-icon-wrapper" style={{ position: 'relative' }}>
        <i
          className={`fas ${config.icon} ${sizeConfig.iconSize}`}
          style={{
            display: 'inline-block',
            animation: 'pulse 2s ease-in-out infinite',
          }}
        />

        {/* 脉冲圆圈效果 */}
        <span
          className="pulse-ring"
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            width: '100%',
            height: '100%',
            borderRadius: '50%',
            border: `2px solid currentColor`,
            opacity: '0.3',
            animation: 'pulse-ring 2s ease-out infinite',
          }}
        />
      </div>

      {/* 状态文本 */}
      <div className="thinking-text">
        <div className={`font-semibold ${sizeConfig.textSize}`}>
          {config.label}
        </div>
        {message && (
          <div className={`text-gray-600 ${sizeConfig.textSize} mt-0.5`}>
            {message}
          </div>
        )}

        {/* 进度条 */}
        {showProgress && (
          <div className="progress-bar mt-2" style={{ width: '150px' }}>
            <div
              className="progress-fill"
              style={{
                height: '3px',
                backgroundColor: 'currentColor',
                borderRadius: '2px',
                transition: 'width 0.3s ease',
                width: `${progress}%`,
              }}
            />
          </div>
        )}
      </div>

      {/* 内联动画定义 */}
      <style jsx>{`
        @keyframes pulse {
          0%, 100% {
            transform: scale(1);
            opacity: 1;
          }
          50% {
            transform: scale(1.05);
            opacity: 0.8;
          }
        }

        @keyframes pulse-ring {
          0% {
            transform: translate(-50%, -50%) scale(0.8);
            opacity: 0.5;
          }
          100% {
            transform: translate(-50%, -50%) scale(1.5);
            opacity: 0;
          }
        }
      `}</style>
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
    <div
      className={`compact-thinking ${config.color} ${className}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.5rem',
      }}
    >
      <i
        className={`fas ${config.icon} fa-spin`}
        style={{ fontSize: '0.875rem' }}
      />
      <span style={{ fontSize: '0.75rem' }}>{config.label}</span>
    </div>
  );
}

/**
 * 波动型思考指示器
 */
export function WaveThinkingIndicator({
  message = '思考中...',
  className = '',
}: {
  message?: string;
  className?: string;
}) {
  return (
    <div
      className={`wave-thinking ${className}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.5rem',
      }}
    >
      {/* 波动点动画 */}
      <div className="wave-dots" style={{ display: 'flex', gap: '3px' }}>
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            style={{
              width: '6px',
              height: '6px',
              backgroundColor: 'currentColor',
              borderRadius: '50%',
              animation: `wave 1.2s ease-in-out infinite`,
              animationDelay: `${i * 0.15}s`,
            }}
          />
        ))}
      </div>

      {message && (
        <span style={{ fontSize: '0.875rem', color: 'currentColor' }}>
          {message}
        </span>
      )}

      <style jsx>{`
        @keyframes wave {
          0%, 100% {
            transform: translateY(0);
            opacity: 0.4;
          }
          50% {
            transform: translateY(-6px);
            opacity: 1;
          }
        }
      `}</style>
    </div>
  );
}
