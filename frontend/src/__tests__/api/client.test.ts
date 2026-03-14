/**
 * API Client Tests
 * API 客户端测试
 */

import { apiRequest, createApiError, API_BASE_URL } from '@/lib/api/client';

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('API Client', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  describe('API_BASE_URL', () => {
    it('should have a default value', () => {
      expect(API_BASE_URL).toBeDefined();
    });
  });

  describe('apiRequest', () => {
    it('should make successful GET request', async () => {
      const mockData = { id: '123', name: 'Test' };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockData),
      });

      const result = await apiRequest('/api/test');
      expect(result).toEqual(mockData);
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/test'),
        expect.objectContaining({ method: 'GET' })
      );
    });

    it('should make POST request with body', async () => {
      const mockData = { success: true, data: { id: '123' } };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockData),
      });

      await apiRequest('/api/test', {
        method: 'POST',
        body: JSON.stringify({ name: 'Test' }),
      });

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/test'),
        expect.objectContaining({ method: 'POST' })
      );
    });

    it('should handle API error response', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: () => Promise.resolve({ message: 'Bad Request' }),
      });

      await expect(apiRequest('/api/test')).rejects.toThrow('Bad Request');
    });

    it('should handle API response with success: false', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ success: false, error: 'Operation failed' }),
      });

      await expect(apiRequest('/api/test')).rejects.toThrow('Operation failed');
    });

    it('should return data from successful API response', async () => {
      const responseData = { success: true, data: { id: '123', name: 'Test' } };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(responseData),
      });

      const result = await apiRequest<{ id: string; name: string }>('/api/test');
      expect(result).toEqual({ id: '123', name: 'Test' });
    });

    it('should include request_id in error when available', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: () => Promise.resolve({ message: 'Server Error', request_id: 'req-123' }),
      });

      try {
        await apiRequest('/api/test');
        fail('Should have thrown');
      } catch (error) {
        expect(error).toBeInstanceOf(Error);
        expect((error as Error & { requestId?: string }).requestId).toBe('req-123');
      }
    });

    it('should retry on network errors', async () => {
      // First two attempts fail
      mockFetch
        .mockRejectedValueOnce(new TypeError('Network error'))
        .mockRejectedValueOnce(new TypeError('Network error'))
        // Third attempt succeeds
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ id: '123' }),
        });

      const result = await apiRequest('/api/test');
      expect(result).toEqual({ id: '123' });
      expect(mockFetch).toHaveBeenCalledTimes(3);
    });

    it('should throw after max retries', async () => {
      mockFetch.mockRejectedValue(new TypeError('Network error'));

      // Set a shorter timeout for this test
      await expect(apiRequest('/api/test')).rejects.toThrow('Network error');
      // Verify it tried MAX_RETRIES + 1 times (initial + 3 retries)
      expect(mockFetch).toHaveBeenCalledTimes(4);
    }, 30000);
  });

  describe('createApiError', () => {
    it('should create error with message', () => {
      const error = createApiError('Test error');
      expect(error.message).toBe('Test error');
    });

    it('should create error with requestId and status', () => {
      const error = createApiError('Test error', 'req-123', 404);
      expect(error.message).toBe('Test error');
      expect((error as Error & { requestId?: string }).requestId).toBe('req-123');
      expect((error as Error & { status?: number }).status).toBe(404);
    });
  });
});