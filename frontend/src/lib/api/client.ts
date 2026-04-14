// ============================================
// API Client - 基础请求函数
// ============================================

import type { APIResponse, ApiError } from './types';

// ============================================
// Configuration
// ============================================

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Retry configuration
const MAX_RETRIES = 3;
const INITIAL_RETRY_DELAY = 1000; // ms
const RETRY_BACKOFF_MULTIPLIER = 2;

// ============================================
// Helper Functions
// ============================================

/**
 * Extract error message from API error response
 * Handles Pydantic validation errors where detail is an array of objects
 */
function extractErrorMessage(errorData: unknown): string {
  if (!errorData) return 'Unknown error';
  if (typeof errorData === 'string') return errorData;

  if (typeof errorData === 'object') {
    const data = errorData as Record<string, unknown>;

    // Pydantic validation errors: detail is array of error objects
    if (data.detail) {
      if (typeof data.detail === 'string') return data.detail;
      if (Array.isArray(data.detail)) {
        return data.detail.map((e) => e.msg || 'Validation error').join(', ');
      }
      if (typeof data.detail === 'object') {
        const detailObj = data.detail as Record<string, unknown>;
        const msg = detailObj.msg;
        if (typeof msg === 'string') return msg;
        return JSON.stringify(data.detail);
      }
    }

    if (typeof data.message === 'string') return data.message;
    if (typeof data.error === 'string') return data.error;
  }

  return 'API request failed';
}

/**
 * 统一的 API 请求函数
 * 支持统一响应格式、重试和错误处理
 */
export async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  let lastError: Error | null = null;
  let retryDelay = INITIAL_RETRY_DELAY;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetch(url, { ...options, method: options.method || 'GET', headers });

      // 解析响应数据
      const data = await response.json();

      // 非2xx响应必须抛出错误，绝不返回数据
      if (!response.ok) {
        // 尝试从错误响应中提取信息
        const errorData = data as ApiError;
        const errorMessage = extractErrorMessage(errorData);
        const requestId = (data as { request_id?: string })?.request_id;

        const error = new Error(errorMessage);
        (error as Error & { requestId?: string; status?: number }).requestId = requestId;
        (error as Error & { requestId?: string; status?: number }).status = response.status;
        throw error;
      }

      // 成功响应 - 检查标准格式并返回数据
      const apiResponse = data as APIResponse<T>;
      if (apiResponse?.success !== undefined) {
        // 标准格式响应
        if (!apiResponse.success) {
          // success=false 的错误响应
          const errorMessage = apiResponse.error || apiResponse.message || 'API request failed';
          const requestId = apiResponse.request_id;
          const error = new Error(errorMessage);
          (error as Error & { requestId?: string; status?: number }).requestId = requestId;
          throw error;
        }
        // 返回数据（支持 data 字段或直接返回 data 本身）
        return apiResponse.data ?? apiResponse as T;
      }

      // 旧格式直接返回
      return data as T;

    } catch (error) {
      // Network error - retry
      if (error instanceof TypeError && attempt < MAX_RETRIES) {
        lastError = error;
        const jitter = Math.random() * 200;
        await new Promise(resolve => setTimeout(resolve, retryDelay + jitter));
        retryDelay *= RETRY_BACKOFF_MULTIPLIER;
        console.warn(`[API] Network error, retrying ${endpoint} (attempt ${attempt + 1}/${MAX_RETRIES})`);
      } else {
        throw error;
      }
    }
  }

  // 抛出最后的错误（如果所有重试都失败）
  throw lastError || new Error('API request failed after retries');
}

/**
 * 创建带错误信息的 Error 对象
 */
export function createApiError(message: string, requestId?: string, status?: number): Error {
  const error = new Error(message);
  (error as Error & { requestId?: string; status?: number }).requestId = requestId;
  (error as Error & { requestId?: string; status?: number }).status = status;
  return error;
}