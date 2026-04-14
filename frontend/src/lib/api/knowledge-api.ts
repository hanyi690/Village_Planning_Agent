// ============================================
// Knowledge & Files API - 知识库与文件 API
// ============================================

import { apiRequest, API_BASE_URL } from './client';
import type {
  KnowledgeDocument,
  KnowledgeStats,
  AddDocumentResponse,
  SyncResponse,
  FileUploadResponse,
  BackendFileUploadResponse,
  BackendAddDocumentResponse,
  EmbeddedImage,
  BackendEmbeddedImage,
} from './types';

// ============================================
// Files API
// ============================================

export const fileApi = {
  /**
   * Upload file and extract content
   * POST /api/files/upload
   */
  async uploadFile(file: File): Promise<FileUploadResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(`${API_BASE_URL}/api/files/upload`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        message: response.statusText || 'File upload failed',
      }));
      throw new Error((error as { message?: string; detail?: string }).message || (error as { detail?: string }).detail || 'File upload failed');
    }

    const data = await response.json() as BackendFileUploadResponse;
    // Convert snake_case from backend to camelCase for frontend
    const embeddedImages = data.embedded_images?.map((img: BackendEmbeddedImage): EmbeddedImage => ({
      imageBase64: img.image_base64,
      imageFormat: img.image_format,
      thumbnailBase64: img.thumbnail_base64,
      imageWidth: img.image_width,
      imageHeight: img.image_height,
    }));

    return {
      content: data.content,
      encoding: data.encoding,
      size: data.size,
      fileType: data.file_type,
      imageBase64: data.image_base64,
      imageFormat: data.image_format,
      thumbnailBase64: data.thumbnail_base64,
      imageWidth: data.image_width,
      imageHeight: data.image_height,
      embeddedImages,
    };
  },

  /**
   * Get file content from URL
   */
  async getFileContent(url: string): Promise<string> {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Failed to fetch file: ${response.statusText}`);
    }
    return response.text();
  },
};

// ============================================
// Knowledge API
// ============================================

import type { AddDocumentOptions } from './types';

export const knowledgeApi = {
  /**
   * 列出知识库中的所有文档
   * GET /api/knowledge/documents
   */
  async listDocuments(): Promise<KnowledgeDocument[]> {
    return apiRequest<KnowledgeDocument[]>('/api/knowledge/documents');
  },

  /**
   * 上传文档到知识库（增量添加）
   * POST /api/knowledge/documents
   */
  async addDocument(file: File, options?: AddDocumentOptions): Promise<AddDocumentResponse> {
    const formData = new FormData();
    formData.append('file', file);
    if (options?.category) {
      formData.append('category', options.category);
    }
    if (options?.doc_type) {
      formData.append('doc_type', options.doc_type);
    }
    if (options?.dimension_tags && options.dimension_tags.length > 0) {
      formData.append('dimension_tags', options.dimension_tags.join(','));
    }
    if (options?.terrain) {
      formData.append('terrain', options.terrain);
    }
    if (options?.regions && options.regions.length > 0) {
      formData.append('regions', options.regions.join(','));
    }

    const response = await fetch(`${API_BASE_URL}/api/knowledge/documents`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        message: response.statusText || 'Upload failed',
      }));
      throw new Error((error as { message?: string; detail?: string }).message || (error as { detail?: string }).detail || 'Upload failed');
    }

    const data = await response.json() as BackendAddDocumentResponse;
    // Convert snake_case from backend to camelCase for frontend
    return {
      status: data.status,
      message: data.message,
      source: data.source,
      chunksAdded: data.chunks_added,
    };
  },

  /**
   * 删除文档
   * DELETE /api/knowledge/documents/{filename}
   */
  async deleteDocument(filename: string): Promise<{ status: string; message: string }> {
    return apiRequest(`/api/knowledge/documents/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
    });
  },

  /**
   * 获取知识库统计信息
   * GET /api/knowledge/stats
   */
  async getStats(): Promise<KnowledgeStats> {
    return apiRequest<KnowledgeStats>('/api/knowledge/stats');
  },

  /**
   * 同步源目录
   * POST /api/knowledge/sync
   */
  async syncDocuments(): Promise<SyncResponse> {
    const data = await apiRequest<{ status: string; message: string; added_count?: number }>('/api/knowledge/sync', {
      method: 'POST',
    });
    // Convert snake_case from backend to camelCase for frontend
    return {
      status: data.status,
      message: data.message,
      addedCount: data.added_count,
    };
  },
};