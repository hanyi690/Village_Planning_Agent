/**
 * 批处理渲染 Hook (useStreamingRender)
 *
 * 功能：
 * - 使用 requestAnimationFrame 批量更新
 * - 防抖内容刷新
 * - 增量DOM更新（只更新变化部分）
 *
 * 目标：
 * - Token → 前端显示延迟 < 100ms
 * - 减少 > 80% 的DOM更新
 * - 平滑的流式显示效果
 *
 * Example:
 * ```tsx
 * const { addToken, completeDimension } = useStreamingRender(
 *   (dimensionKey, content) => {
 *     setDimensionContents(prev => {
 *       const next = new Map(prev);
 *       next.set(dimensionKey, content);
 *       return next;
 *     });
 *   },
 *   { batchSize: 10, batchWindow: 50, debounceMs: 100 }
 * );
 *
 * // Add streaming tokens
 * addToken("economic", "token1", "accumulated1");
 * addToken("economic", "token2", "accumulated1token2");
 *
 * // Mark dimension complete
 * completeDimension("economic");
 * ```
 */

import { useRef, useCallback, useEffect } from 'react';

interface StreamingRenderOptions {
  batchSize?: number; // 批处理大小（token数量）
  batchWindow?: number; // 时间窗口（ms）
  debounceMs?: number; // 防抖延迟
}

interface DimensionBuffer {
  dimensionKey: string;
  chunks: string[];
  lastUpdate: number;
  accumulated: string;
  layer?: number; // 🔧 FIX: 添加 layer 字段，解决闭包陷阱
}

interface UseStreamingRenderReturn {
  addToken: (dimensionKey: string, chunk: string, accumulated: string, layer?: number) => void;
  completeDimension: (dimensionKey: string, layer?: number) => void;
  flushBatch: () => void;
  getStats: () => { bufferSize: number; activeDimensions: string[] };
}

/**
 * 批处理渲染 Hook
 *
 * @param onContentUpdate - 内容更新回调 (dimensionKey, content, layer?) => void
 * @param options - 配置选项
 * @returns 渲染控制函数
 */
export function useStreamingRender(
  onContentUpdate: (dimensionKey: string, content: string, layer?: number) => void,
  options: StreamingRenderOptions = {}
): UseStreamingRenderReturn {
  const { batchSize = 10, batchWindow = 50, debounceMs = 100 } = options;

  const buffers = useRef<Map<string, DimensionBuffer>>(new Map());
  const rafId = useRef<number>();
  const timeoutId = useRef<NodeJS.Timeout>();
  const isFlushScheduled = useRef(false);

  /**
   * 添加token到缓冲区
   */
  const addToken = useCallback(
    (
      dimensionKey: string,
      chunk: string,
      accumulated: string,
      layer?: number // 🔧 FIX: 添加 layer 参数，解决闭包陷阱
    ) => {
      const buffer = buffers.current.get(dimensionKey) || {
        dimensionKey,
        chunks: [],
        lastUpdate: Date.now(),
        accumulated: '',
        layer: layer, // 🔧 FIX: 存储传入的 layer 值
      };

      buffer.chunks.push(chunk);
      buffer.accumulated = accumulated;
      buffer.lastUpdate = Date.now();
      // 🔧 FIX: 如果传入了新的 layer 值，更新它（避免使用旧值）
      if (layer !== undefined) {
        buffer.layer = layer;
      }
      buffers.current.set(dimensionKey, buffer);

      // 触发批处理
      scheduleBatch();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    []
  );

  /**
   * 调度批处理（使用RAF）
   */
  const scheduleBatch = useCallback(() => {
    if (isFlushScheduled.current) {
      return; // 已经调度了，避免重复
    }

    isFlushScheduled.current = true;

    rafId.current = requestAnimationFrame(() => {
      flushBatchInternal();
      isFlushScheduled.current = false;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchSize, batchWindow, debounceMs]);

  /**
   * 内部批处理刷新函数
   */
  const flushBatchInternal = useCallback(() => {
    const now = Date.now();
    const updates: Array<{ dimensionKey: string; content: string; layer?: number }> = [];

    // 收集需要更新的维度
    for (const [key, buffer] of buffers.current) {
      if (buffer.chunks.length >= batchSize || now - buffer.lastUpdate >= batchWindow) {
        updates.push({ dimensionKey: key, content: buffer.accumulated, layer: buffer.layer });
        buffer.chunks = [];
        buffer.lastUpdate = now;
      }
    }

    if (updates.length > 0) {
      // 防抖：延迟执行回调
      if (timeoutId.current) {
        clearTimeout(timeoutId.current);
      }

      timeoutId.current = setTimeout(() => {
        updates.forEach(({ dimensionKey, content, layer }) => {
          // 🔧 FIX: 传递 layer 参数到回调
          onContentUpdate(dimensionKey, content, layer);
        });
      }, debounceMs);
    }
  }, [batchSize, batchWindow, debounceMs, onContentUpdate]);

  /**
   * 手动刷新所有批次
   */
  const flushBatch = useCallback(() => {
    // 取消待处理的RAF
    if (rafId.current) {
      cancelAnimationFrame(rafId.current);
      isFlushScheduled.current = false;
    }

    // 立即刷新所有buffer
    const updates: Array<{ dimensionKey: string; content: string; layer?: number }> = [];

    for (const [key, buffer] of buffers.current) {
      if (buffer.chunks.length > 0) {
        updates.push({ dimensionKey: key, content: buffer.accumulated, layer: buffer.layer });
        buffer.chunks = [];
        buffer.lastUpdate = Date.now();
      }
    }

    if (updates.length > 0) {
      // 立即执行回调（不防抖）
      updates.forEach(({ dimensionKey, content, layer }) => {
        // 🔧 FIX: 传递 layer 参数到回调
        onContentUpdate(dimensionKey, content, layer);
      });
    }
  }, [onContentUpdate]);

  /**
   * 标记维度完成
   */
  const completeDimension = useCallback(
    (dimensionKey: string, layer?: number) => {
      const buffer = buffers.current.get(dimensionKey);
      if (buffer && buffer.chunks.length > 0) {
        // 🔧 FIX: 优先使用传入的 layer 参数，否则使用 buffer 中存储的值
        const layerToUse = layer !== undefined ? layer : buffer.layer;
        // 立即刷新该维度
        onContentUpdate(dimensionKey, buffer.accumulated, layerToUse);
        buffers.current.delete(dimensionKey);
      } else if (buffer) {
        // 即使没有chunk，也要删除
        buffers.current.delete(dimensionKey);
      }
    },
    [onContentUpdate]
  );

  /**
   * 获取统计信息（用于调试）
   */
  const getStats = useCallback(() => {
    const activeDimensions = Array.from(buffers.current.keys());
    const bufferSize = Array.from(buffers.current.values()).reduce(
      (sum, buf) => sum + buf.chunks.length,
      0
    );

    return {
      bufferSize,
      activeDimensions,
    };
  }, []);

  /**
   * 清理
   */
  useEffect(() => {
    return () => {
      if (rafId.current) {
        cancelAnimationFrame(rafId.current);
      }
      if (timeoutId.current) {
        clearTimeout(timeoutId.current);
      }
    };
  }, []);

  return {
    addToken,
    completeDimension,
    flushBatch,
    getStats,
  };
}

/**
 * 默认导出
 */
export default useStreamingRender;
