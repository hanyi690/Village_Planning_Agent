/**
 * useStreamingText Hook
 * 流式文本输出 Hook - 实现 Gemini 风格的逐字打印效果
 */

import { useState, useEffect, useRef, useCallback } from 'react';

export interface UseStreamingTextOptions {
  speed?: number; // 字符/秒 (默认: 50)
  batchSize?: number; // 每批更新的字符数 (默认: 3)
  enabled?: boolean; // 是否启用流式效果 (默认: true)
  onComplete?: () => void; // 完成回调
}

export interface UseStreamingTextReturn {
  displayedContent: string;
  isStreaming: boolean;
  isPaused: boolean;
  progress: number; // 0-100
  pause: () => void;
  resume: () => void;
  reset: () => void;
  skipToEnd: () => void;
}

/**
 * 流式文本输出 Hook
 * 使用 requestAnimationFrame 实现平滑的逐字打印效果
 */
export function useStreamingText(
  content: string,
  options: UseStreamingTextOptions = {}
): UseStreamingTextReturn {
  const {
    speed = 50, // 字符/秒
    batchSize = 3, // 每次更新显示的字符数
    enabled = true,
    onComplete,
  } = options;

  const [displayedContent, setDisplayedContent] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [progress, setProgress] = useState(0);

  const currentIndexRef = useRef(0);
  const lastUpdateTimeRef = useRef(0);
  const animationFrameRef = useRef<number | null>(null);
  const completeRef = useRef(false);

  // 计算更新间隔（毫秒）
  const updateInterval = (1000 / speed) * batchSize;

  /**
   * 动画循环 - 使用 requestAnimationFrame 确保流畅度
   */
  const animate = useCallback((timestamp: number) => {
    if (completeRef.current) {
      return;
    }

    // 如果暂停，继续循环但不更新
    if (isPaused) {
      animationFrameRef.current = requestAnimationFrame(animate);
      return;
    }

    // 检查是否应该更新
    if (timestamp - lastUpdateTimeRef.current >= updateInterval) {
      const nextIndex = Math.min(
        currentIndexRef.current + batchSize,
        content.length
      );

      if (nextIndex > currentIndexRef.current) {
        currentIndexRef.current = nextIndex;
        setDisplayedContent(content.slice(0, nextIndex));
        setProgress((nextIndex / content.length) * 100);
        lastUpdateTimeRef.current = timestamp;
      }

      // 检查是否完成
      if (nextIndex >= content.length) {
        completeRef.current = true;
        setIsStreaming(false);
        onComplete?.();
        return;
      }
    }

    // 继续动画循环
    animationFrameRef.current = requestAnimationFrame(animate);
  }, [content, batchSize, updateInterval, isPaused, onComplete]);

  /**
   * 开始流式输出
   */
  useEffect(() => {
    // 如果禁用或内容为空，直接显示完整内容
    if (!enabled || !content) {
      setDisplayedContent(content);
      setProgress(content ? 100 : 0);
      completeRef.current = true;
      setIsStreaming(false);
      return;
    }

    // 重置状态
    currentIndexRef.current = 0;
    lastUpdateTimeRef.current = 0;
    completeRef.current = false;
    setDisplayedContent('');
    setProgress(0);
    setIsStreaming(true);
    setIsPaused(false);

    // 开始动画
    animationFrameRef.current = requestAnimationFrame(animate);

    // 清理函数
    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, [content, enabled]); // 仅在 content 或 enabled 变化时重新开始

  /**
   * 暂停流式输出
   */
  const pause = useCallback(() => {
    setIsPaused(true);
  }, []);

  /**
   * 恢复流式输出
   */
  const resume = useCallback(() => {
    setIsPaused(false);
  }, []);

  /**
   * 重置到初始状态
   */
  const reset = useCallback(() => {
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
    }

    currentIndexRef.current = 0;
    lastUpdateTimeRef.current = 0;
    completeRef.current = false;
    setDisplayedContent('');
    setProgress(0);
    setIsStreaming(true);
    setIsPaused(false);

    animationFrameRef.current = requestAnimationFrame(animate);
  }, [animate]);

  /**
   * 跳到结尾
   */
  const skipToEnd = useCallback(() => {
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
    }

    completeRef.current = true;
    currentIndexRef.current = content.length;
    setDisplayedContent(content);
    setProgress(100);
    setIsStreaming(false);
    setIsPaused(false);
  }, [content]);

  return {
    displayedContent,
    isStreaming,
    isPaused,
    progress,
    pause,
    resume,
    reset,
    skipToEnd,
  };
}

/**
 * 流式文本累积器 Hook
 * 用于处理持续到来的文本块（如 SSE 流式输出）
 */
export function useStreamingAccumulator() {
  const [fullContent, setFullContent] = useState('');
  const [displayedContent, setDisplayedContent] = useState('');
  const streamingState = useStreamingText(fullContent);

  /**
   * 添加新的文本块
   */
  const appendChunk = useCallback((chunk: string) => {
    setFullContent(prev => prev + chunk);
  }, []);

  /**
   * 重置累积器
   */
  const reset = useCallback(() => {
    setFullContent('');
    setDisplayedContent('');
    streamingState.reset();
  }, [streamingState]);

  /**
   * 完成输入
   */
  const complete = useCallback(() => {
    streamingState.skipToEnd();
  }, [streamingState]);

  return {
    ...streamingState,
    fullContent,
    appendChunk,
    reset,
    complete,
  };
}
