'use client';

/**
 * KnowledgePanel - 知识库管理面板
 * 
 * 功能:
 * 1. 显示知识库统计信息（文档数、切片数）
 * 2. 拖拽上传文档
 * 3. 文档列表管理（查看状态、删除）
 * 4. 同步源目录
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { 
  faTimes, 
  faDatabase, 
  faUpload, 
  faSpinner, 
  faTrash, 
  faCheck, 
  faExclamationTriangle,
  faSync,
  faFileAlt,
  faCloudUploadAlt
} from '@fortawesome/free-solid-svg-icons';
import { knowledgeApi, KnowledgeDocument, KnowledgeStats } from '@/lib/api';

interface KnowledgePanelProps {
  onClose: () => void;
}

type DocumentStatus = 'ready' | 'processing' | 'error';

interface DocumentWithStatus extends KnowledgeDocument {
  uiStatus?: DocumentStatus;
}

export default function KnowledgePanel({ onClose }: KnowledgePanelProps) {
  const [mounted, setMounted] = useState(false);
  const [documents, setDocuments] = useState<DocumentWithStatus[]>([]);
  const [stats, setStats] = useState<KnowledgeStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 加载数据
  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [docsData, statsData] = await Promise.all([
        knowledgeApi.listDocuments(),
        knowledgeApi.getStats(),
      ]);
      setDocuments(docsData.map(d => ({ ...d, uiStatus: 'ready' as DocumentStatus })));
      setStats(statsData);
    } catch (err) {
      console.error('[KnowledgePanel] Failed to load data:', err);
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setMounted(true);
    document.body.style.overflow = 'hidden';
    loadData();

    return () => {
      document.body.style.overflow = 'unset';
    };
  }, [loadData]);

  // 处理文件上传
  const handleFileUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;

    setUploading(true);
    setError(null);

    try {
      for (const file of Array.from(files)) {
        // 添加到列表，标记为处理中
        const tempDoc: DocumentWithStatus = {
          source: file.name,
          doc_type: file.name.split('.').pop() || 'unknown',
          chunk_count: 0,
          uiStatus: 'processing',
        };
        setDocuments(prev => [tempDoc, ...prev]);

        try {
          await knowledgeApi.addDocument(file, 'policies');
          // 更新状态为已就绪
          setDocuments(prev => 
            prev.map(d => 
              d.source === file.name 
                ? { ...d, uiStatus: 'ready' as DocumentStatus }
                : d
            )
          );
        } catch (err) {
          // 更新状态为错误
          setDocuments(prev => 
            prev.map(d => 
              d.source === file.name 
                ? { ...d, uiStatus: 'error' as DocumentStatus }
                : d
            )
          );
          console.error('[KnowledgePanel] Upload failed:', err);
        }
      }

      // 重新加载统计
      const newStats = await knowledgeApi.getStats();
      setStats(newStats);
    } finally {
      setUploading(false);
    }
  };

  // 处理删除
  const handleDelete = async (filename: string) => {
    if (!confirm(`确定要删除 "${filename}" 吗？\n这将同时删除向量数据库中的相关数据。`)) {
      return;
    }

    try {
      await knowledgeApi.deleteDocument(filename);
      setDocuments(prev => prev.filter(d => d.source !== filename));
      
      // 更新统计
      const newStats = await knowledgeApi.getStats();
      setStats(newStats);
    } catch (err) {
      console.error('[KnowledgePanel] Delete failed:', err);
      setError(err instanceof Error ? err.message : '删除失败');
    }
  };

  // 处理同步
  const handleSync = async () => {
    setSyncing(true);
    setError(null);

    try {
      const result = await knowledgeApi.syncDocuments();
      if (result.added_count && result.added_count > 0) {
        await loadData();
      }
      alert(`同步完成\n新增: ${result.added_count || 0} 个文档`);
    } catch (err) {
      console.error('[KnowledgePanel] Sync failed:', err);
      setError(err instanceof Error ? err.message : '同步失败');
    } finally {
      setSyncing(false);
    }
  };

  // 拖拽处理
  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    handleFileUpload(e.dataTransfer.files);
  }, []);

  // 获取状态图标
  const getStatusIcon = (status?: DocumentStatus) => {
    switch (status) {
      case 'processing':
        return <FontAwesomeIcon icon={faSpinner} spin className="text-blue-500" />;
      case 'error':
        return <FontAwesomeIcon icon={faExclamationTriangle} className="text-red-500" />;
      case 'ready':
      default:
        return <FontAwesomeIcon icon={faCheck} className="text-green-500" />;
    }
  };

  // 获取状态文字
  const getStatusText = (status?: DocumentStatus) => {
    switch (status) {
      case 'processing':
        return '处理中...';
      case 'error':
        return '处理失败';
      case 'ready':
      default:
        return '已就绪';
    }
  };

  if (!mounted) return null;

  return createPortal(
    <>
      {/* Overlay */}
      <div
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.5)',
          backdropFilter: 'blur(4px)',
          zIndex: 9998,
        }}
        onClick={onClose}
      />

      {/* Panel */}
      <div style={{
        position: 'fixed',
        top: 0,
        right: 0,
        bottom: 0,
        width: '500px',
        maxWidth: '500px',
        backgroundColor: 'white',
        boxShadow: '-4px 0 25px rgba(0, 0, 0, 0.15)',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 9999,
      }}>
        {/* Header */}
        <div className="px-4 py-3 bg-green-600 text-white flex justify-between items-center">
          <h2 className="text-lg font-bold flex items-center gap-2">
            <FontAwesomeIcon icon={faDatabase} />
            知识库管理
          </h2>
          <button onClick={onClose} className="text-white/80 hover:text-white text-xl">
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>

        {/* Stats Bar */}
        {stats && (
          <div className="px-4 py-3 bg-gray-50 border-b flex items-center justify-between">
            <div className="flex items-center gap-4 text-sm text-gray-600">
              <span>
                <FontAwesomeIcon icon={faFileAlt} className="mr-1 text-green-600" />
                {stats.total_documents} 个文档
              </span>
              <span>
                <FontAwesomeIcon icon={faDatabase} className="mr-1 text-blue-600" />
                {stats.total_chunks} 个切片
              </span>
            </div>
            <button
              onClick={handleSync}
              disabled={syncing}
              className="flex items-center gap-1 px-3 py-1 text-sm text-green-600 hover:bg-green-50 rounded border border-green-200 disabled:opacity-50"
            >
              <FontAwesomeIcon icon={syncing ? faSpinner : faSync} spin={syncing} />
              同步
            </button>
          </div>
        )}

        {/* Upload Area */}
        <div
          className={`mx-4 mt-4 p-6 border-2 border-dashed rounded-lg text-center transition-colors ${
            dragActive 
              ? 'border-green-500 bg-green-50' 
              : 'border-gray-300 hover:border-green-400'
          }`}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.docx,.doc,.pptx,.ppt,.md,.txt"
            className="hidden"
            onChange={(e) => handleFileUpload(e.target.files)}
          />
          <FontAwesomeIcon 
            icon={uploading ? faSpinner : faCloudUploadAlt} 
            spin={uploading}
            className="text-4xl text-gray-400 mb-2"
          />
          <p className="text-gray-600 mb-2">
            {uploading ? '正在上传...' : '拖拽文件到此处，或'}
          </p>
          {!uploading && (
            <button
              onClick={() => fileInputRef.current?.click()}
              className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 text-sm"
            >
              选择文件
            </button>
          )}
          <p className="text-xs text-gray-400 mt-2">
            支持 PDF、Word、PPT、Markdown 格式
          </p>
        </div>

        {/* Error Message */}
        {error && (
          <div className="mx-4 mt-2 p-2 bg-red-50 border border-red-200 rounded text-red-600 text-sm flex items-center gap-2">
            <FontAwesomeIcon icon={faExclamationTriangle} />
            {error}
          </div>
        )}

        {/* Document List */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading ? (
            <div className="text-center text-gray-400 py-10">
              <FontAwesomeIcon icon={faSpinner} spin size="2x" className="text-green-600 mb-2" />
              <p>加载中...</p>
            </div>
          ) : documents.length === 0 ? (
            <div className="text-center text-gray-400 py-10">
              <FontAwesomeIcon icon={faDatabase} size="3x" className="mb-2" />
              <p>知识库为空</p>
              <p className="text-sm">上传文档开始构建知识库</p>
            </div>
          ) : (
            <div className="space-y-2">
              {documents.map((doc) => (
                <div
                  key={doc.source}
                  className="flex items-center justify-between p-3 bg-gray-50 rounded-lg border hover:bg-gray-100"
                >
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <FontAwesomeIcon icon={faFileAlt} className="text-gray-400 flex-shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-800 truncate">{doc.source}</p>
                      <p className="text-xs text-gray-500">
                        {doc.chunk_count} 个切片 · {doc.doc_type.toUpperCase()}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs flex items-center gap-1">
                      {getStatusIcon(doc.uiStatus)}
                      <span className="text-gray-500">{getStatusText(doc.uiStatus)}</span>
                    </span>
                    {doc.uiStatus !== 'processing' && (
                      <button
                        onClick={() => handleDelete(doc.source)}
                        className="p-1 text-gray-400 hover:text-red-500 transition-colors"
                        title="删除"
                      >
                        <FontAwesomeIcon icon={faTrash} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-3 bg-gray-50 border-t text-center text-xs text-gray-500">
          知识库文档用于增强规划智能体的专业能力
        </div>
      </div>
    </>,
    document.body
  );
}
