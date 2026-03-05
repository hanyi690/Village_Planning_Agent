'use client';

/**
 * KnowledgePanel - 知识库管理面板 (Gemini Dark Style)
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

  const handleFileUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;

    setUploading(true);
    setError(null);

    try {
      for (const file of Array.from(files)) {
        const tempDoc: DocumentWithStatus = {
          source: file.name,
          doc_type: file.name.split('.').pop() || 'unknown',
          chunk_count: 0,
          uiStatus: 'processing',
        };
        setDocuments(prev => [tempDoc, ...prev]);

        try {
          await knowledgeApi.addDocument(file, 'policies');
          setDocuments(prev => 
            prev.map(d => 
              d.source === file.name 
                ? { ...d, uiStatus: 'ready' as DocumentStatus }
                : d
            )
          );
        } catch (err) {
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

      const newStats = await knowledgeApi.getStats();
      setStats(newStats);
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (filename: string) => {
    if (!confirm(`确定要删除 "${filename}" 吗？\n这将同时删除向量数据库中的相关数据。`)) {
      return;
    }

    try {
      await knowledgeApi.deleteDocument(filename);
      setDocuments(prev => prev.filter(d => d.source !== filename));
      
      const newStats = await knowledgeApi.getStats();
      setStats(newStats);
    } catch (err) {
      console.error('[KnowledgePanel] Delete failed:', err);
      setError(err instanceof Error ? err.message : '删除失败');
    }
  };

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

  const getStatusIcon = (status?: DocumentStatus) => {
    switch (status) {
      case 'processing':
        return <FontAwesomeIcon icon={faSpinner} spin className="text-blue-400" style={{ width: '12px', height: '12px' }} />;
      case 'error':
        return <FontAwesomeIcon icon={faExclamationTriangle} className="text-red-400" style={{ width: '12px', height: '12px' }} />;
      case 'ready':
      default:
        return <FontAwesomeIcon icon={faCheck} className="text-green-400" style={{ width: '12px', height: '12px' }} />;
    }
  };

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
      {/* Overlay - Gemini style */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[9998] animate-fade-in"
        onClick={onClose}
      />

      {/* Panel - Gemini dark style */}
      <div className="fixed top-0 right-0 bottom-0 w-[500px] max-w-[500px] bg-[#1a1a1a] border-l border-[#2d2d2d] flex flex-col z-[9999] animate-slide-in-right">
        
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#2d2d2d]">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500/20 to-blue-600/10 border border-blue-500/30">
              <FontAwesomeIcon icon={faDatabase} className="text-blue-400" style={{ width: '14px', height: '14px' }} />
            </div>
            <h2 className="text-lg font-semibold text-white">知识库管理</h2>
          </div>
          <button 
            onClick={onClose} 
            className="p-2 rounded-lg text-zinc-400 hover:text-white hover:bg-[#2d2d2d] transition-colors"
          >
            <FontAwesomeIcon icon={faTimes} style={{ width: '16px', height: '16px' }} />
          </button>
        </div>

        {/* Stats Bar */}
        {stats && (
          <div className="px-5 py-3 bg-[#1e1e1e] border-b border-[#2d2d2d] flex items-center justify-between">
            <div className="flex items-center gap-4 text-sm text-zinc-400">
              <span className="flex items-center gap-1.5">
                <FontAwesomeIcon icon={faFileAlt} className="text-green-400" style={{ width: '12px', height: '12px' }} />
                {stats.total_documents} 个文档
              </span>
              <span className="flex items-center gap-1.5">
                <FontAwesomeIcon icon={faDatabase} className="text-blue-400" style={{ width: '12px', height: '12px' }} />
                {stats.total_chunks} 个切片
              </span>
            </div>
            <button
              onClick={handleSync}
              disabled={syncing}
              className="flex items-center gap-2 px-3 py-1.5 text-sm text-green-400 bg-green-500/10 hover:bg-green-500/20 rounded-lg border border-green-500/30 disabled:opacity-50 transition-colors"
            >
              <FontAwesomeIcon icon={syncing ? faSpinner : faSync} spin={syncing} style={{ width: '12px', height: '12px' }} />
              同步
            </button>
          </div>
        )}

        {/* Upload Area */}
        <div
          className={`mx-5 mt-4 p-6 border-2 border-dashed rounded-xl text-center transition-all ${
            dragActive 
              ? 'border-green-500 bg-green-500/10' 
              : 'border-[#3f3f46] hover:border-green-500/50 bg-[#1e1e1e]'
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
            className="text-4xl text-zinc-500 mb-3"
          />
          <p className="text-zinc-300 mb-2">
            {uploading ? '正在上传...' : '拖拽文件到此处，或'}
          </p>
          {!uploading && (
            <button
              onClick={() => fileInputRef.current?.click()}
              className="px-5 py-2 bg-gradient-to-r from-green-600 to-green-500 text-white rounded-lg text-sm font-medium hover:from-green-500 hover:to-green-400 transition-all shadow-lg shadow-green-500/20"
            >
              选择文件
            </button>
          )}
          <p className="text-xs text-zinc-500 mt-3">
            支持 PDF、Word、PPT、Markdown 格式
          </p>
        </div>

        {/* Error Message */}
        {error && (
          <div className="mx-5 mt-3 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm flex items-center gap-2">
            <FontAwesomeIcon icon={faExclamationTriangle} style={{ width: '14px', height: '14px' }} />
            {error}
          </div>
        )}

        {/* Document List */}
        <div className="flex-1 overflow-y-auto p-5">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-16 text-zinc-400">
              <div className="w-10 h-10 border-2 border-green-500/30 border-t-green-500 rounded-full animate-spin mb-4" />
              <p className="text-sm">加载中...</p>
            </div>
          ) : documents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
              <FontAwesomeIcon icon={faDatabase} className="text-4xl mb-4" />
              <p>知识库为空</p>
              <p className="text-sm mt-1">上传文档开始构建知识库</p>
            </div>
          ) : (
            <div className="space-y-2">
              {documents.map((doc) => (
                <div
                  key={doc.source}
                  className="flex items-center justify-between p-3 bg-[#1e1e1e] rounded-xl border border-[#2d2d2d] hover:border-[#3f3f46] transition-colors"
                >
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-[#2d2d2d]">
                      <FontAwesomeIcon icon={faFileAlt} className="text-zinc-400" style={{ width: '14px', height: '14px' }} />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-white truncate">{doc.source}</p>
                      <p className="text-xs text-zinc-500">
                        {doc.chunk_count} 个切片 · {doc.doc_type.toUpperCase()}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs flex items-center gap-1.5">
                      {getStatusIcon(doc.uiStatus)}
                      <span className="text-zinc-500">{getStatusText(doc.uiStatus)}</span>
                    </span>
                    {doc.uiStatus !== 'processing' && (
                      <button
                        onClick={() => handleDelete(doc.source)}
                        className="p-2 text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                        title="删除"
                      >
                        <FontAwesomeIcon icon={faTrash} style={{ width: '12px', height: '12px' }} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 bg-[#151515] border-t border-[#2d2d2d] text-center text-xs text-zinc-500">
          知识库文档用于增强规划智能体的专业能力
        </div>
      </div>
    </>,
    document.body
  );
}