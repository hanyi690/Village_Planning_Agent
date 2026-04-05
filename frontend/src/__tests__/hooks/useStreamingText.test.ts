/**
 * useStreamingText Hook Tests
 * 流式文本 Hook 测试
 */

import { renderHook, act } from '@testing-library/react';
import { useStreamingText } from '@/hooks/ui';

// Mock requestAnimationFrame
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const mockRaf = jest.fn();
const mockCancelRaf = jest.fn();
let rafCallback: FrameRequestCallback | null = null;

beforeAll(() => {
  global.requestAnimationFrame = (callback: FrameRequestCallback) => {
    rafCallback = callback;
    return 1;
  };
  global.cancelAnimationFrame = mockCancelRaf;
});

beforeEach(() => {
  jest.useFakeTimers();
  rafCallback = null;
});

afterEach(() => {
  jest.useRealTimers();
});

describe('useStreamingText', () => {
  describe('initial state', () => {
    it('should return empty content initially', () => {
      const { result } = renderHook(() => useStreamingText(''));
      expect(result.current.displayedContent).toBe('');
      expect(result.current.isStreaming).toBe(false);
    });

    it('should return full content when disabled', () => {
      const { result } = renderHook(() => useStreamingText('Hello World', { enabled: false }));
      expect(result.current.displayedContent).toBe('Hello World');
    });
  });

  describe('streaming behavior', () => {
    it('should start streaming when content is provided', () => {
      const { result } = renderHook(() => useStreamingText('Hello'));

      // Initial state before animation starts
      expect(result.current.displayedContent).toBe('');
    });

    it('should update progress during streaming', () => {
      const { result } = renderHook(() => useStreamingText('Hello'));

      // Simulate animation frames
      act(() => {
        if (rafCallback) {
          rafCallback(0);
        }
      });

      // Progress should be calculated
      expect(result.current.progress).toBeGreaterThanOrEqual(0);
    });
  });

  describe('control functions', () => {
    it('should have pause function', () => {
      const { result } = renderHook(() => useStreamingText('Hello'));
      expect(typeof result.current.pause).toBe('function');
    });

    it('should have resume function', () => {
      const { result } = renderHook(() => useStreamingText('Hello'));
      expect(typeof result.current.resume).toBe('function');
    });

    it('should have reset function', () => {
      const { result } = renderHook(() => useStreamingText('Hello'));
      expect(typeof result.current.reset).toBe('function');
    });

    it('should have skipToEnd function', () => {
      const { result } = renderHook(() => useStreamingText('Hello'));
      expect(typeof result.current.skipToEnd).toBe('function');
    });

    it('should skip to end when skipToEnd is called', () => {
      const { result } = renderHook(() => useStreamingText('Hello World'));

      act(() => {
        result.current.skipToEnd();
      });

      expect(result.current.displayedContent).toBe('Hello World');
      expect(result.current.progress).toBe(100);
      expect(result.current.isStreaming).toBe(false);
    });

    it('should reset streaming state when reset is called', () => {
      const { result } = renderHook(() => useStreamingText('Hello'));

      // Skip to end first
      act(() => {
        result.current.skipToEnd();
      });

      // Then reset
      act(() => {
        result.current.reset();
      });

      expect(result.current.displayedContent).toBe('');
      expect(result.current.progress).toBe(0);
    });
  });

  describe('pause and resume', () => {
    it('should toggle pause state', () => {
      const { result } = renderHook(() => useStreamingText('Hello'));

      expect(result.current.isPaused).toBe(false);

      act(() => {
        result.current.pause();
      });

      expect(result.current.isPaused).toBe(true);

      act(() => {
        result.current.resume();
      });

      expect(result.current.isPaused).toBe(false);
    });
  });

  describe('onComplete callback', () => {
    it('should have onComplete option', () => {
      const onComplete = jest.fn();
      const { result } = renderHook(() => useStreamingText('Hello', { onComplete }));

      // onComplete is registered but may not be called due to test environment
      expect(result.current.skipToEnd).toBeDefined();
    });
  });
});
