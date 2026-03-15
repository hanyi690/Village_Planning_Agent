'use client';

/**
 * KnowledgePanel - Gemini Style
 * 知识库管理面板 - 玻璃态效果 + Framer Motion 动画
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faTimes,
  faDatabase,
  faSpinner,
  faTrash,
  faCheck,
  faExclamationTriangle,
  faSync,
  faFileAlt,
  faCloudUploadAlt,
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
      setDocuments(docsData.map((d) => ({ ...d, uiStatus: 'ready' as DocumentStatus })));
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
        const tempDoc: DocumentWithStatus = {
          source: file.name,
          doc_type: file.name.split('.').pop() || 'unknown',
          chunk_count: 0,
          uiStatus: 'processing',
        };
        setDocuments((prev) => [tempDoc, ...prev]);

        try {
          await knowledgeApi.addDocument(file, 'policies');
          setDocuments((prev) =>
            prev.map((d) =>
              d.source === file.name ? { ...d, uiStatus: 'ready' as DocumentStatus } : d
            )
          );
        } catch (err) {
          setDocuments((prev) =>
            prev.map((d) =>
              d.source === file.name ? { ...d, uiStatus: 'error' as DocumentStatus } : d
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

  // 处理删除
  const handleDelete = async (filename: string) => {
    if (!confirm(`确定要删除 "${filename}" 吗？\n这将同时删除向量数据库中的相关数据。`)) {
      return;
    }

    try {
      await knowledgeApi.deleteDocument(filename);
      setDocuments((prev) => prev.filter((d) => d.source !== filename));

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
        return <FontAwesomeIcon icon={faCheck} className="text-emerald-500" />;
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

  // Animation variants
  const overlayVariants = {
    hidden: { opacity: 0 },
    visible: { opacity: 1 },
    exit: { opacity: 0 },
  };

  const panelVariants = {
    hidden: { x: '100%', opacity: 0 },
    visible: {
      x: 0,
      opacity: 1,
      transition: {
        type: 'spring' as const,
        stiffness: 300,
        damping: 30,
      },
    },
    exit: {
      x: '100%',
      opacity: 0,
      transition: { duration: 0.2 },
    },
  };

  const itemVariants = {
    hidden: { opacity: 0, y: 10 },
    visible: { opacity: 1, y: 0 },
  };

  if (!mounted) return null;

  return createPortal(
    <>
      {/* Overlay */}
      <motion.div
        variants={overlayVariants}
        initial="hidden"
        animate="visible"
        exit="exit"
        className="fixed inset-0 bg-black/30 backdrop-blur-sm z-[9998]"
        onClick={onClose}
      />

      {/* Panel - Glass morphism style */}
      <motion.div
        variants={panelVariants}
        initial="hidden"
        animate="visible"
        exit="exit"
        className="fixed top-0 right-0 bottom-0 w-[500px] max-w-[500px] bg-white/95 backdrop-blur-xl shadow-2xl flex flex-col z-[9999] border-l border-white/20"
      >
        {/* Header - Gradient */}
        <div
          className="px-5 py-4 flex justify-between items-center"
          style={{
            background: 'linear-gradient(135deg, #8b5cf6 0%, #3b82f6 50%, #ec4899 100%)',
          }}
        >
          <h2 className="flex items-center gap-2 text-lg font-bold text-white">
            <FontAwesomeIcon icon={faDatabase} />
            知识库管理
          </h2>
          <motion.button
            whileHover={{ scale: 1.1, rotate: 90 }}
            whileTap={{ scale: 0.9 }}
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center text-white/80 hover:text-white rounded-full hover:bg-white/10 transition-colors"
          >
            <FontAwesomeIcon icon={faTimes} />
          </motion.button>
        </div>

        {/* Stats Bar */}
        {stats && (
          <div className="px-5 py-3 bg-gray-50/80 border-b border-gray-100 flex items-center justify-between">
            <div className="flex items-center gap-4 text-sm text-gray-600">
              <span className="flex items-center gap-1.5">
                <FontAwesomeIcon icon={faFileAlt} className="text-violet-500" />
                {stats.total_documents} 个文档
              </span>
              <span className="flex items-center gap-1.5">
                <FontAwesomeIcon icon={faDatabase} className="text-blue-500" />
                {stats.total_chunks} 个切片
              </span>
            </div>
            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={handleSync}
              disabled={syncing}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-violet-600 bg-white hover:bg-violet-50 rounded-lg border border-violet-200 disabled:opacity-50 transition-colors"
            >
              <FontAwesomeIcon icon={syncing ? faSpinner : faSync} spin={syncing} />
              同步
            </motion.button>
          </div>
        )}

        {/* Upload Area */}
        <motion.div
          whileHover={{ scale: 1.01 }}
          className={`mx-5 mt-4 p-6 border-2 border-dashed rounded-2xl text-center transition-all duration-300 ${
            dragActive
              ? 'border-violet-400 bg-violet-50/50 scale-[1.02]'
              : 'border-gray-200 hover:border-violet-300 hover:bg-violet-50/30'
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
          <motion.div
            animate={uploading ? { rotate: 360 } : {}}
            transition={{ duration: 1, repeat: uploading ? Infinity : 0, ease: 'linear' }}
          >
            <FontAwesomeIcon
              icon={uploading ? faSpinner : faCloudUploadAlt}
              className="text-4xl text-gray-300 mb-3"
            />
          </motion.div>
          <p className="text-gray-500 mb-3">{uploading ? '正在上传...' : '拖拽文件到此处，或'}</p>
          {!uploading && (
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={() => fileInputRef.current?.click()}
              className="px-5 py-2.5 text-white font-medium rounded-full shadow-md"
              style={{
                background: 'linear-gradient(135deg, #8b5cf6 0%, #3b82f6 100%)',
                boxShadow: '0 4px 15px rgba(139, 92, 246, 0.3)',
              }}
            >
              选择文件
            </motion.button>
          )}
          <p className="text-xs text-gray-400 mt-3">支持 PDF、Word、PPT、Markdown 格式</p>
        </motion.div>

        {/* Error Message */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="mx-5 mt-3 p-3 bg-red-50 border border-red-200 rounded-xl text-red-600 text-sm flex items-center gap-2"
            >
              <FontAwesomeIcon icon={faExclamationTriangle} />
              {error}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Document List */}
        <div className="flex-1 overflow-y-auto p-5">
          <AnimatePresence mode="wait">
            {loading ? (
              <motion.div
                key="loading"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="text-center py-10"
              >
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                >
                  <FontAwesomeIcon icon={faSpinner} className="text-3xl text-violet-500" />
                </motion.div>
                <p className="mt-3 text-gray-400">加载中...</p>
              </motion.div>
            ) : documents.length === 0 ? (
              <motion.div
                key="empty"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                className="text-center py-16"
              >
                <FontAwesomeIcon icon={faDatabase} className="text-5xl text-gray-200 mb-4" />
                <p className="text-gray-400">知识库为空</p>
                <p className="text-sm text-gray-300 mt-1">上传文档开始构建知识库</p>
              </motion.div>
            ) : (
              <motion.div
                key="list"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="space-y-2"
              >
                {documents.map((doc, index) => (
                  <motion.div
                    key={doc.source}
                    variants={itemVariants}
                    initial="hidden"
                    animate="visible"
                    transition={{ delay: index * 0.03 }}
                    whileHover={{ scale: 1.01, x: 4 }}
                    className="flex items-center justify-between p-4 bg-gray-50/80 rounded-xl border border-gray-100 hover:border-violet-200 hover:bg-white transition-all group"
                  >
                    <div className="flex items-center gap-3 flex-1 min-w-0">
                      <FontAwesomeIcon
                        icon={faFileAlt}
                        className="text-gray-300 group-hover:text-violet-400 transition-colors"
                      />
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-gray-800 truncate">{doc.source}</p>
                        <p className="text-xs text-gray-400">
                          {doc.chunk_count} 个切片 · {doc.doc_type.toUpperCase()}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs flex items-center gap-1.5">
                        {getStatusIcon(doc.uiStatus)}
                        <span className="text-gray-400">{getStatusText(doc.uiStatus)}</span>
                      </span>
                      {doc.uiStatus !== 'processing' && (
                        <motion.button
                          whileHover={{ scale: 1.1 }}
                          whileTap={{ scale: 0.9 }}
                          onClick={() => handleDelete(doc.source)}
                          className="p-1.5 text-gray-300 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                          title="删除"
                        >
                          <FontAwesomeIcon icon={faTrash} />
                        </motion.button>
                      )}
                    </div>
                  </motion.div>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 bg-gray-50/80 border-t border-gray-100 text-center text-xs text-gray-400">
          知识库文档用于增强规划智能体的专业能力
        </div>
      </motion.div>
    </>,
    document.body
  );
}
