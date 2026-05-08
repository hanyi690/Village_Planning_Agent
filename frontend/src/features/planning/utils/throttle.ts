/**
 * Throttle Hook
 *
 * 创建一个 throttled 版本的回调函数
 * 用于减少高频状态更新的渲染压力
 *
 * @param callback - 原始回调函数
 * @param delay - throttle 延迟时间 (ms)
 * @returns throttled 回调函数
 */

import { useRef, useCallback, useEffect } from 'react';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function useThrottleCallback<T extends (...args: any[]) => any>(
  callback: T,
  delay: number
): T {
  const lastCallTimeRef = useRef(0);
  const timeoutIdRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pendingArgsRef = useRef<any[] | null>(null);

  // 清理 timeout
  useEffect(() => {
    return () => {
      if (timeoutIdRef.current) {
        clearTimeout(timeoutIdRef.current);
      }
      pendingArgsRef.current = null;
    };
  }, []);

  const throttledCallback = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (...args: any[]) => {
      const now = Date.now();
      const timeSinceLastCall = now - lastCallTimeRef.current;

      // 如果距离上次调用时间超过 delay，立即执行
      if (timeSinceLastCall >= delay) {
        lastCallTimeRef.current = now;
        callback(...args);
      } else {
        // 否则，保存参数并在 delay 后执行
        pendingArgsRef.current = args;

        if (!timeoutIdRef.current) {
          timeoutIdRef.current = setTimeout(() => {
            if (pendingArgsRef.current) {
              lastCallTimeRef.current = Date.now();
              callback(...pendingArgsRef.current);
              pendingArgsRef.current = null;
            }
            timeoutIdRef.current = null;
          }, delay - timeSinceLastCall);
        }
      }
    },
    [callback, delay]
  ) as T;

  return throttledCallback;
}

export default useThrottleCallback;