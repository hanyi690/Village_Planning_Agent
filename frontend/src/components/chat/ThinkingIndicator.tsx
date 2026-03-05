'use client';

/**
 * ThinkingIndicator Component - Gemini Style
 * 思考状态指示器 - 使用 Framer Motion 实现流畅动画
 */

import React from 'react';
import { motion } from 'framer-motion';

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
 * 状态配置 - 使用 Gemini 风格的幻彩渐变
 */
const STATE_CONFIG: Record<
  ThinkingState,
  {
    icon: string;
    label: string;
    gradient: string;
    bgColor: string;
  }
> = {
  analyzing: {
    icon: 'fa-microscope',
    label: '分析中',
    gradient: 'from-blue-500 to-cyan-500',
    bgColor: 'bg-blue-50',
  },
  generating: {
    icon: 'fa-wand-magic-sparkles',
    label: '生成中',
    gradient: 'from-violet-500 to-purple-500',
    bgColor: 'bg-violet-50',
  },
  reviewing: {
    icon: 'fa-magnifying-glass-chart',
    label: '审查中',
    gradient: 'from-amber-500 to-orange-500',
    bgColor: 'bg-amber-50',
  },
  processing: {
    icon: 'fa-gears',
    label: '处理中',
    gradient: 'from-emerald-500 to-teal-500',
    bgColor: 'bg-emerald-50',
  },
  waiting: {
    icon: 'fa-hourglass-half',
    label: '等待中',
    gradient: 'from-gray-400 to-gray-500',
    bgColor: 'bg-gray-50',
  },
};

/**
 * 尺寸配置
 */
const SIZE_CONFIG: Record<
  'sm' | 'md' | 'lg',
  {
    containerPadding: string;
    iconSize: string;
    textSize: string;
    dotSize: string;
  }
> = {
  sm: {
    containerPadding: 'px-3 py-2',
    iconSize: 'text-sm',
    textSize: 'text-xs',
    dotSize: 'w-1.5 h-1.5',
  },
  md: {
    containerPadding: 'px-4 py-3',
    iconSize: 'text-base',
    textSize: 'text-sm',
    dotSize: 'w-2 h-2',
  },
  lg: {
    containerPadding: 'px-5 py-4',
    iconSize: 'text-xl',
    textSize: 'text-base',
    dotSize: 'w-2.5 h-2.5',
  },
};

/**
 * 波动点动画组件
 */
function WaveDots({ size }: { size: 'sm' | 'md' | 'lg' }) {
  const dotSize = SIZE_CONFIG[size].dotSize;

  return (
    <div className="flex items-center gap-1">
      {[0, 1, 2].map((i) => (
        <motion.div
          key={i}
          className={`${dotSize} rounded-full`}
          style={{
            background: 'linear-gradient(135deg, #8b5cf6 0%, #3b82f6 50%, #ec4899 100%)',
          }}
          animate={{
            y: [0, -6, 0],
            opacity: [0.4, 1, 0.4],
          }}
          transition={{
            duration: 0.8,
            repeat: Infinity,
            delay: i * 0.15,
            ease: 'easeInOut',
          }}
        />
      ))}
    </div>
  );
}

/**
 * 渐变图标组件
 */
function GradientIcon({
  icon,
  gradient,
  size,
}: {
  icon: string;
  gradient: string;
  size: string;
}) {
  return (
    <motion.div
      className={`relative ${size}`}
      animate={{
        scale: [1, 1.1, 1],
      }}
      transition={{
        duration: 2,
        repeat: Infinity,
        ease: 'easeInOut',
      }}
    >
      <i
        className={`fas ${icon} bg-gradient-to-r ${gradient} bg-clip-text text-transparent`}
        style={{
          WebkitTextFillColor: 'transparent',
          backgroundClip: 'text',
        }}
      />
      {/* 脉冲光圈 */}
      <motion.div
        className="absolute inset-0 rounded-full"
        style={{
          background: `linear-gradient(135deg, rgba(139, 92, 246, 0.3), rgba(59, 130, 246, 0.3), rgba(236, 72, 153, 0.3))`,
        }}
        animate={{
          scale: [0.8, 1.5],
          opacity: [0.5, 0],
        }}
        transition={{
          duration: 1.5,
          repeat: Infinity,
          ease: 'easeOut',
        }}
      />
    </motion.div>
  );
}

/**
 * 主思考指示器组件
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
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className={`inline-flex items-center gap-3 rounded-2xl ${config.bgColor} ${sizeConfig.containerPadding} ${className}`}
    >
      {/* 渐变图标 */}
      <GradientIcon
        icon={config.icon}
        gradient={config.gradient}
        size={sizeConfig.iconSize}
      />

      {/* 状态文本 */}
      <div className="flex flex-col">
        <div className={`font-medium text-gray-700 ${sizeConfig.textSize}`}>
          {config.label}
        </div>
        {message && (
          <div className={`text-gray-500 mt-0.5 ${sizeConfig.textSize}`}>
            {message}
          </div>
        )}

        {/* 进度条 */}
        {showProgress && (
          <div className="mt-2 w-36 h-1.5 bg-gray-200 rounded-full overflow-hidden">
            <motion.div
              className="h-full rounded-full"
              style={{
                background: 'linear-gradient(135deg, #8b5cf6 0%, #3b82f6 50%, #ec4899 100%)',
              }}
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.3, ease: 'easeOut' }}
            />
          </div>
        )}
      </div>

      {/* 波动点 */}
      <WaveDots size={size} />
    </motion.div>
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
    <div className={`inline-flex items-center gap-2 ${className}`}>
      <motion.i
        className={`fas ${config.icon} text-sm`}
        animate={{ rotate: 360 }}
        transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
        style={{
          background: `linear-gradient(135deg, #8b5cf6, #3b82f6, #ec4899)`,
          WebkitTextFillColor: 'transparent',
          backgroundClip: 'text',
        }}
      />
      <span className="text-xs text-gray-600">{config.label}</span>
    </div>
  );
}

/**
 * 波动型思考指示器 (纯点动画)
 */
export function WaveThinkingIndicator({
  message = '思考中...',
  className = '',
}: {
  message?: string;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className={`inline-flex items-center gap-3 ${className}`}
    >
      <WaveDots size="md" />
      {message && (
        <span className="text-sm text-gray-500">{message}</span>
      )}
    </motion.div>
  );
}