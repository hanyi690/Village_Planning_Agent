'use client';

/**
 * StreamingText Component
 * 流式文本组件 - 实现 Gemini 风格的逐字打印效果
 */

import React, { useEffect, useRef } from 'react';
import { useStreamingText } from '@/hooks/useStreamingText';

export interface StreamingTextProps {
  content: string;
  speed?: number;
  batchSize?: number;
  enabled?: boolean;
  className?: string;
  onComplete?: () => void;
  children?: (renderProps: {
    text: string;
    isStreaming: boolean;
    isPaused: boolean;
    progress: number;
    pause: () => void;
    resume: () => void;
    skipToEnd: () => void;
  }) => React.ReactNode;
}

/**
 * 流式文本组件
 *
 * @example
 * // 基础用法
 * <StreamingText content="Hello, world!" />
 *
 * @example
 * // 自定义速度
 * <StreamingText content="Slow text..." speed={30} />
 *
 * @example
 * // 自定义渲染
 * <StreamingText content="Custom rendering">
 *   {({ text, isStreaming, progress }) => (
 *     <div>
 *       <p>{text}</p>
 *       {isStreaming && <progress value={progress} max={100} />}
 *     </div>
 *   )}
 * </StreamingText>
 */
export default function StreamingText({
  content,
  speed,
  batchSize,
  enabled = true,
  className = '',
  onComplete,
  children,
}: StreamingTextProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const { displayedContent, isStreaming, isPaused, progress, pause, resume, skipToEnd } =
    useStreamingText(content, {
      speed,
      batchSize,
      enabled,
      onComplete,
    });

  // 自动滚动到底部
  useEffect(() => {
    if (containerRef.current && isStreaming && !isPaused) {
      containerRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'end',
      });
    }
  }, [displayedContent, isStreaming, isPaused]);

  // 如果提供了自定义渲染函数，使用它
  if (children) {
    return (
      <>
        {children({
          text: displayedContent,
          isStreaming,
          isPaused,
          progress,
          pause,
          resume,
          skipToEnd,
        })}
      </>
    );
  }

  // 默认渲染
  return (
    <div
      ref={containerRef}
      className={`streaming-text ${className}`}
      style={{
        position: 'relative',
      }}
    >
      {/* 文本内容 */}
      <span className="streaming-text-content">{displayedContent}</span>

      {/* 打字光标效果 */}
      {isStreaming && !isPaused && (
        <span
          className="streaming-cursor"
          style={{
            display: 'inline-block',
            width: '2px',
            height: '1em',
            backgroundColor: 'currentColor',
            marginLeft: '2px',
            animation: 'blink 1s step-end infinite',
            verticalAlign: 'text-bottom',
          }}
        />
      )}

      {/* 进度条（可选） */}
      {isStreaming && (
        <div
          className="streaming-progress"
          style={{
            position: 'absolute',
            bottom: -4,
            left: 0,
            height: '2px',
            backgroundColor: 'rgba(46, 125, 50, 0.3)',
            borderRadius: '1px',
            overflow: 'hidden',
            transition: 'width 0.1s linear',
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${progress}%`,
              backgroundColor: 'rgba(46, 125, 50, 0.6)',
              transition: 'width 0.1s linear',
            }}
          />
        </div>
      )}

      {/* 内联样式 */}
      <style jsx>{`
        @keyframes blink {
          0%,
          100% {
            opacity: 1;
          }
          50% {
            opacity: 0;
          }
        }

        .streaming-text-content {
          white-space: pre-wrap;
          word-wrap: break-word;
        }
      `}</style>
    </div>
  );
}

/**
 * 快捷组件：带控制按钮的流式文本
 */
export function StreamingTextWithControls(props: StreamingTextProps) {
  const { displayedContent, isStreaming, isPaused, progress, pause, resume, skipToEnd } =
    useStreamingText(props.content, {
      speed: props.speed,
      batchSize: props.batchSize,
      enabled: props.enabled,
      onComplete: props.onComplete,
    });

  return (
    <div className="streaming-text-with-controls">
      {/* 流式文本 */}
      <div className="streaming-text-content mb-2">{displayedContent}</div>

      {/* 控制按钮 */}
      {isStreaming && (
        <div className="streaming-controls flex gap-2 mt-2">
          {/* 暂停/继续按钮 */}
          <button
            onClick={isPaused ? resume : pause}
            className="px-3 py-1 text-xs rounded bg-gray-100 hover:bg-gray-200 transition-colors"
            title={isPaused ? '继续' : '暂停'}
          >
            <i className={`fas ${isPaused ? 'fa-play' : 'fa-pause'} mr-1`} />
            {isPaused ? '继续' : '暂停'}
          </button>

          {/* 跳到结尾按钮 */}
          <button
            onClick={skipToEnd}
            className="px-3 py-1 text-xs rounded bg-gray-100 hover:bg-gray-200 transition-colors"
            title="立即显示全部"
          >
            <i className="fas fa-fast-forward icon-xs mr-1" />
            跳过
          </button>

          {/* 进度指示 */}
          <div className="flex items-center gap-2 ml-auto text-xs text-gray-600">
            <span>{Math.round(progress)}%</span>
            <div className="w-16 h-1 bg-gray-200 rounded overflow-hidden">
              <div
                className="h-full bg-green-500 transition-all duration-100"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        </div>
      )}

      {/* 完成 */}
      {!isStreaming && displayedContent === props.content && (
        <div className="text-xs text-gray-600 mt-1 flex items-center gap-1">
          <i className="fas fa-check-circle icon-xs" />
          <span>完成</span>
        </div>
      )}
    </div>
  );
}
