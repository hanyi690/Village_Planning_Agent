'use client';

/**
 * KnowledgePanel - 知识库管理面板
 * 支持元数据标注的文档上传与管理
 */

import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
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
  faTags,
  faMapMarkerAlt,
  faLayerGroup,
  faBook,
  faGlobe,
  faPlus,
} from '@fortawesome/free-solid-svg-icons';
import { knowledgeApi, KnowledgeDocument, KnowledgeStats, AddDocumentOptions } from '@/lib/api';
import { getDimensionName, DIMENSIONS_BY_LAYER } from '@/config/dimensions';

// 维度标签 - 基于 Layer 1 维度，增加知识库专用标签
const LAYER1_DIMENSIONS = [
  ...DIMENSIONS_BY_LAYER[1],
  'disaster_prevention', // 知识库专用：防震减灾
] as const;

// ============================================
// 常量定义
// ============================================

// 知识库类别
const KB_CATEGORIES = [
  { value: 'policies', label: '政策法规', icon: faBook, color: 'violet' },
  { value: 'cases', label: '案例示范', icon: faFileAlt, color: 'blue' },
  { value: 'standards', label: '标准规范', icon: faDatabase, color: 'emerald' },
  { value: 'domain', label: '专业知识', icon: faLayerGroup, color: 'amber' },
  { value: 'local', label: '本地资料', icon: faGlobe, color: 'cyan' },
] as const;

type KBCategoryValue = (typeof KB_CATEGORIES)[number]['value'];

// 文档类型
const DOC_TYPES = [
  { value: 'policy', label: '政策文件', description: '政策、意见、指导、办法等' },
  { value: 'standard', label: '标准规范', description: '标准、规范、规程、技术指标等' },
  { value: 'case', label: '案例报告', description: '案例、示范、典型、经验模式等' },
  { value: 'guide', label: '指南手册', description: '指南、手册、教程、知识介绍等' },
  { value: 'report', label: '研究报告', description: '报告、调研、分析、评估研究等' },
] as const;

type DocTypeValue = (typeof DOC_TYPES)[number]['value'];

// 维度颜色映射
const DIMENSION_COLORS: Record<string, string> = {
  land_use: 'bg-amber-100 text-amber-700 border-amber-300',
  infrastructure: 'bg-blue-100 text-blue-700 border-blue-300',
  ecological_green: 'bg-emerald-100 text-emerald-700 border-emerald-300',
  historical_culture: 'bg-amber-100 text-amber-700 border-amber-300',
  traffic: 'bg-slate-100 text-slate-700 border-slate-300',
  location: 'bg-violet-100 text-violet-700 border-violet-300',
  socio_economic: 'bg-green-100 text-green-700 border-green-300',
  villager_wishes: 'bg-pink-100 text-pink-700 border-pink-300',
  superior_planning: 'bg-indigo-100 text-indigo-700 border-indigo-300',
  natural_environment: 'bg-teal-100 text-teal-700 border-teal-300',
  public_services: 'bg-cyan-100 text-cyan-700 border-cyan-300',
  architecture: 'bg-orange-100 text-orange-700 border-orange-300',
  disaster_prevention: 'bg-red-100 text-red-700 border-red-300',
};

// 地形类型
const TERRAIN_TYPES = [
  { value: 'all', label: '不限/混合', icon: '🌐' },
  { value: 'mountain', label: '山区', icon: '⛰️' },
  { value: 'plain', label: '平原', icon: '🏞️' },
  { value: 'hill', label: '丘陵', icon: '🏔️' },
  { value: 'coastal', label: '沿海', icon: '🏖️' },
  { value: 'riverside', label: '沿江/滨河', icon: '🏞️' },
] as const;

type TerrainTypeValue = (typeof TERRAIN_TYPES)[number]['value'];

interface KnowledgePanelProps {
  onClose: () => void;
}

type DocumentStatus = 'ready' | 'processing' | 'error';

interface DocumentWithStatus extends KnowledgeDocument {
  uiStatus?: DocumentStatus;
}

interface UploadFormData {
  category: KBCategoryValue;
  doc_type: DocTypeValue | '';
  dimension_tags: string[];
  terrain: TerrainTypeValue;
  regions: string[];
}

// 初始表单状态
const INITIAL_FORM_STATE: UploadFormData = {
  category: 'policies',
  doc_type: '',
  dimension_tags: [],
  terrain: 'all',
  regions: [],
};

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
  const formFileInputRef = useRef<HTMLInputElement>(null);

  // 上传表单状态
  const [showUploadForm, setShowUploadForm] = useState(false);
  const [uploadForm, setUploadForm] = useState<UploadFormData>(INITIAL_FORM_STATE);
  const [regionInput, setRegionInput] = useState('');
  const [autoDetect, setAutoDetect] = useState(true);

  // 存储待处理的文件（使用 state 统一管理）
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);

  // setTimeout 清理
  const refreshTimerRef = useRef<NodeJS.Timeout | null>(null);

  // useMemo 创建查找 Map，优化渲染效率
  const categoryMap = useMemo(() => new Map(KB_CATEGORIES.map((c) => [c.value, c])), []);
  const terrainMap = useMemo(() => new Map(TERRAIN_TYPES.map((t) => [t.value, t])), []);

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
      // 清理 setTimeout
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
    };
  }, [loadData]);

  // 统一的上传处理函数
  const processFileUpload = async (files: File[], options?: AddDocumentOptions) => {
    if (files.length === 0) return;

    setUploading(true);
    setError(null);

    const uploadOptions: AddDocumentOptions = options || { category: 'policies' };

    // 先添加所有临时文档
    const tempDocs: DocumentWithStatus[] = files.map((file) => ({
      source: file.name,
      doc_type: uploadOptions.doc_type || file.name.split('.').pop() || 'unknown',
      chunk_count: 0,
      uiStatus: 'processing' as DocumentStatus,
      category: uploadOptions.category,
      dimension_tags: uploadOptions.dimension_tags,
      terrain: uploadOptions.terrain,
      regions: uploadOptions.regions,
    }));
    setDocuments((prev) => [...tempDocs, ...prev]);

    // 并行上传所有文件
    const results = await Promise.allSettled(
      files.map((file) => knowledgeApi.addDocument(file, uploadOptions))
    );

    // 处理结果
    results.forEach((result, index) => {
      const fileName = files[index].name;
      if (result.status === 'fulfilled') {
        setDocuments((prev) =>
          prev.map((d) =>
            d.source === fileName ? { ...d, uiStatus: 'ready' as DocumentStatus } : d
          )
        );
      } else {
        setDocuments((prev) =>
          prev.map((d) =>
            d.source === fileName ? { ...d, uiStatus: 'error' as DocumentStatus } : d
          )
        );
        console.error('[KnowledgePanel] Upload failed:', result.reason);
        setError(`上传失败：${fileName}`);
      }
    });

    setUploading(false);

    // 等待后台处理完成后刷新数据
    refreshTimerRef.current = setTimeout(async () => {
      await loadData();
    }, 1500);
  };

  // 处理文件上传（从拖拽或直接上传触发）
  const handleFileUpload = (files: FileList | null) => {
    if (!files || files.length === 0) return;

    const fileArray = Array.from(files);

    // 如果设置了元数据配置，先显示表单
    if (autoDetect) {
      setSelectedFiles(fileArray);
      setShowUploadForm(true);
      return;
    }

    // 直接上传（向后兼容）
    processFileUpload(fileArray, { category: 'policies' });
  };

  // 处理带 metadata 的上传（从表单提交）
  const handleUploadWithMetadata = () => {
    if (selectedFiles.length === 0) {
      setShowUploadForm(false);
      return;
    }

    const options: AddDocumentOptions = {
      category: uploadForm.category,
      doc_type: uploadForm.doc_type || undefined,
      dimension_tags: uploadForm.dimension_tags.length > 0 ? uploadForm.dimension_tags : undefined,
      terrain: uploadForm.terrain !== 'all' ? uploadForm.terrain : undefined,
      regions: uploadForm.regions.length > 0 ? uploadForm.regions : undefined,
    };

    setShowUploadForm(false);
    setSelectedFiles([]);
    setUploadForm(INITIAL_FORM_STATE);
    setRegionInput('');

    processFileUpload(selectedFiles, options);
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
      alert(`同步完成\n新增：${result.added_count || 0} 个文档`);
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

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragActive(false);
      handleFileUpload(e.dataTransfer.files);
    },
    // handleFileUpload 依赖 autoDetect state，但拖拽处理不需要在 autoDetect 变化时重新创建
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

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

  // 切换维度标签
  const toggleDimensionTag = (value: string) => {
    setUploadForm((prev) => ({
      ...prev,
      dimension_tags: prev.dimension_tags.includes(value)
        ? prev.dimension_tags.filter((t) => t !== value)
        : [...prev.dimension_tags, value],
    }));
  };

  // 添加地区
  const addRegion = () => {
    if (regionInput.trim() && !uploadForm.regions.includes(regionInput.trim())) {
      setUploadForm((prev) => ({
        ...prev,
        regions: [...prev.regions, regionInput.trim()],
      }));
      setRegionInput('');
    }
  };

  // 移除地区
  const removeRegion = (region: string) => {
    setUploadForm((prev) => ({
      ...prev,
      regions: prev.regions.filter((r) => r !== region),
    }));
  };

  // 处理地区输入键盘事件
  const handleRegionKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addRegion();
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

  const formOverlayVariants = {
    hidden: { opacity: 0 },
    visible: { opacity: 1 },
    exit: { opacity: 0 },
  };

  const formVariants = {
    hidden: { scale: 0.95, opacity: 0, y: 20 },
    visible: { scale: 1, opacity: 1, y: 0 },
    exit: { scale: 0.95, opacity: 0, y: 20 },
  };

  if (!mounted) return null;

  return createPortal(
    <>
      {/* 主面板 Overlay */}
      <motion.div
        variants={overlayVariants}
        initial="hidden"
        animate="visible"
        exit="exit"
        className="fixed inset-0 bg-black/30 backdrop-blur-sm z-[9998]"
        onClick={onClose}
      />

      {/* 主面板 - 玻璃态风格 */}
      <motion.div
        variants={panelVariants}
        initial="hidden"
        animate="visible"
        exit="exit"
        className="fixed top-0 right-0 bottom-0 w-[550px] max-w-[550px] bg-white/95 backdrop-blur-xl shadow-2xl flex flex-col z-[9999] border-l border-white/20"
      >
        {/* Header - 渐变 */}
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

        {/* 上传区域 */}
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
              onClick={() => {
                setShowUploadForm(true);
                formFileInputRef.current?.click();
              }}
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

          {/* 自动检测开关 */}
          <div className="mt-4 flex items-center justify-center gap-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={autoDetect}
                onChange={(e) => setAutoDetect(e.target.checked)}
                className="w-4 h-4 text-violet-600 rounded focus:ring-violet-500"
              />
              <span className="text-sm text-gray-600">上传时配置元数据</span>
            </label>
          </div>
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
                    className="flex flex-col gap-2 p-4 bg-gray-50/80 rounded-xl border border-gray-100 hover:border-violet-200 hover:bg-white transition-all group"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3 flex-1 min-w-0">
                        <FontAwesomeIcon
                          icon={faFileAlt}
                          className="text-gray-300 group-hover:text-violet-400 transition-colors"
                        />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-gray-800 truncate">{doc.source}</p>
                          <p className="text-xs text-gray-400">
                            {doc.chunk_count} 个切片 · {doc.doc_type?.toUpperCase() || 'UNKNOWN'}
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
                    </div>

                    {/* 元数据标签展示 */}
                    {(doc.dimension_tags || doc.terrain || doc.category) && (
                      <div className="flex flex-wrap gap-1.5 ml-9">
                        {/* 类别标签 */}
                        {doc.category && (
                          <span className="px-2 py-0.5 text-xs rounded-full bg-violet-100 text-violet-700 border border-violet-200">
                            {categoryMap.get(doc.category as KBCategoryValue)?.label ||
                              doc.category}
                          </span>
                        )}

                        {/* 维度标签 */}
                        {doc.dimension_tags?.slice(0, 5).map((tag) => {
                          const tagColor =
                            DIMENSION_COLORS[tag] || 'bg-gray-100 text-gray-700 border-gray-200';
                          return (
                            <span
                              key={tag}
                              className={`px-2 py-0.5 text-xs rounded-full border ${tagColor}`}
                            >
                              {getDimensionName(tag)}
                            </span>
                          );
                        })}
                        {doc.dimension_tags && doc.dimension_tags.length > 5 && (
                          <span className="px-2 py-0.5 text-xs text-gray-400">
                            +{doc.dimension_tags.length - 5}
                          </span>
                        )}

                        {/* 地形标签 */}
                        {doc.terrain &&
                          doc.terrain !== 'all' &&
                          (() => {
                            const terrainConfig = terrainMap.get(doc.terrain as TerrainTypeValue);
                            return terrainConfig ? (
                              <span className="px-2 py-0.5 text-xs rounded-full bg-emerald-100 text-emerald-700 border border-emerald-200">
                                {terrainConfig.icon}
                                {terrainConfig.label}
                              </span>
                            ) : null;
                          })()}

                        {/* 地区标签 */}
                        {doc.regions && doc.regions.length > 0 && (
                          <span className="px-2 py-0.5 text-xs rounded-full bg-cyan-100 text-cyan-700 border border-cyan-200">
                            <FontAwesomeIcon icon={faMapMarkerAlt} className="mr-1" />
                            {doc.regions.slice(0, 3).join(', ')}
                            {doc.regions.length > 3 && ` +${doc.regions.length - 3}`}
                          </span>
                        )}
                      </div>
                    )}
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

      {/* 上传表单弹窗 */}
      <AnimatePresence>
        {showUploadForm && (
          <motion.div
            variants={formOverlayVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[10000] flex items-center justify-center p-4"
            onClick={() => setShowUploadForm(false)}
          >
            <motion.div
              variants={formVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              {/* 表单 Header */}
              <div className="px-6 py-4 border-b border-gray-100 flex justify-between items-center sticky top-0 bg-white z-10">
                <div>
                  <h3 className="text-lg font-bold text-gray-800">配置文档元数据</h3>
                  <p className="text-sm text-gray-500">
                    {selectedFiles.length > 0
                      ? `已选择：${selectedFiles.map((f) => f.name).join(', ')}`
                      : '请选择要上传的文件'}
                  </p>
                </div>
                <button
                  onClick={() => setShowUploadForm(false)}
                  className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  <FontAwesomeIcon icon={faTimes} />
                </button>
              </div>

              {/* 表单内容 */}
              <div className="p-6 space-y-6">
                {/* 知识库类别选择 */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    <FontAwesomeIcon icon={faDatabase} className="mr-2 text-violet-500" />
                    知识库类别
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    {KB_CATEGORIES.map((cat) => (
                      <button
                        key={cat.value}
                        onClick={() => setUploadForm((prev) => ({ ...prev, category: cat.value }))}
                        className={`p-3 rounded-xl border-2 transition-all text-left ${
                          uploadForm.category === cat.value
                            ? `border-${cat.color}-500 bg-${cat.color}-50 shadow-md`
                            : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <FontAwesomeIcon
                            icon={cat.icon}
                            className={
                              uploadForm.category === cat.value
                                ? `text-${cat.color}-600`
                                : 'text-gray-400'
                            }
                          />
                          <span className="text-sm font-medium text-gray-700">{cat.label}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* 文档类型选择 */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    <FontAwesomeIcon icon={faBook} className="mr-2 text-blue-500" />
                    文档类型（可选，默认自动识别）
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    {DOC_TYPES.map((type) => (
                      <button
                        key={type.value}
                        onClick={() =>
                          setUploadForm((prev) => ({
                            ...prev,
                            doc_type: prev.doc_type === type.value ? '' : type.value,
                          }))
                        }
                        className={`p-3 rounded-xl border-2 transition-all text-left ${
                          uploadForm.doc_type === type.value
                            ? 'border-blue-500 bg-blue-50 shadow-md'
                            : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                        }`}
                      >
                        <div className="text-sm font-medium text-gray-800">{type.label}</div>
                        <div className="text-xs text-gray-500 mt-1">{type.description}</div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* 维度标签选择 */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    <FontAwesomeIcon icon={faTags} className="mr-2 text-emerald-500" />
                    维度标签（可选，默认自动识别）
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {LAYER1_DIMENSIONS.map((dimKey) => {
                      const colorClass =
                        DIMENSION_COLORS[dimKey] || 'bg-gray-100 text-gray-700 border-gray-200';
                      return (
                        <button
                          key={dimKey}
                          onClick={() => toggleDimensionTag(dimKey)}
                          className={`px-3 py-1.5 text-sm rounded-full border-2 transition-all ${
                            uploadForm.dimension_tags.includes(dimKey)
                              ? colorClass + ' border-current shadow-sm'
                              : 'border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50'
                          }`}
                        >
                          {getDimensionName(dimKey)}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* 地形类型选择 */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    <FontAwesomeIcon icon={faGlobe} className="mr-2 text-amber-500" />
                    地形类型
                  </label>
                  <div className="grid grid-cols-3 gap-2">
                    {TERRAIN_TYPES.map((terrain) => (
                      <button
                        key={terrain.value}
                        onClick={() =>
                          setUploadForm((prev) => ({ ...prev, terrain: terrain.value }))
                        }
                        className={`p-3 rounded-xl border-2 transition-all text-center ${
                          uploadForm.terrain === terrain.value
                            ? 'border-amber-500 bg-amber-50 shadow-md'
                            : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                        }`}
                      >
                        <div className="text-2xl mb-1">{terrain.icon}</div>
                        <div className="text-sm font-medium text-gray-700">{terrain.label}</div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* 地区输入 */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    <FontAwesomeIcon icon={faMapMarkerAlt} className="mr-2 text-cyan-500" />
                    涉及地区（可选）
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={regionInput}
                      onChange={(e) => setRegionInput(e.target.value)}
                      onKeyDown={handleRegionKeyDown}
                      placeholder="输入地区名称，按回车添加"
                      className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500 text-sm"
                    />
                    <button
                      onClick={addRegion}
                      className="px-4 py-2 bg-cyan-500 text-white rounded-lg hover:bg-cyan-600 transition-colors flex items-center gap-1"
                    >
                      <FontAwesomeIcon icon={faPlus} />
                      添加
                    </button>
                  </div>
                  {/* 已添加的地区标签 */}
                  {uploadForm.regions.length > 0 && (
                    <div className="flex flex-wrap gap-2 mt-2">
                      {uploadForm.regions.map((region) => (
                        <span
                          key={region}
                          className="px-3 py-1 bg-cyan-100 text-cyan-700 rounded-full text-sm flex items-center gap-2"
                        >
                          <FontAwesomeIcon icon={faMapMarkerAlt} />
                          {region}
                          <button
                            onClick={() => removeRegion(region)}
                            className="text-cyan-500 hover:text-cyan-700"
                          >
                            <FontAwesomeIcon icon={faTimes} />
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* 表单 Footer */}
              <div className="px-6 py-4 border-t border-gray-100 bg-gray-50 sticky bottom-0 flex justify-between items-center gap-3">
                {/* 隐藏的文件输入 */}
                <input
                  ref={formFileInputRef}
                  type="file"
                  multiple
                  accept=".pdf,.docx,.doc,.pptx,.ppt,.md,.txt"
                  className="hidden"
                  onChange={(e) => {
                    const files = e.target.files;
                    if (files && files.length > 0) {
                      setSelectedFiles(Array.from(files));
                    }
                    // 重置 input 以便可以再次选择相同文件
                    e.target.value = '';
                  }}
                />
                {/* 文件选择按钮 */}
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  onClick={() => formFileInputRef.current?.click()}
                  className="px-5 py-2.5 text-violet-600 bg-white hover:bg-violet-50 rounded-lg border border-violet-200 transition-colors font-medium flex items-center gap-2"
                >
                  <FontAwesomeIcon icon={faPlus} />
                  选择文件
                </motion.button>

                <div className="flex justify-end gap-3">
                  <button
                    onClick={() => {
                      setShowUploadForm(false);
                      setSelectedFiles([]);
                      setUploadForm(INITIAL_FORM_STATE);
                      setRegionInput('');
                    }}
                    className="px-5 py-2.5 text-gray-600 hover:text-gray-800 hover:bg-gray-200 rounded-lg transition-colors font-medium"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleUploadWithMetadata}
                    disabled={uploading || selectedFiles.length === 0}
                    className="px-6 py-2.5 bg-gradient-to-r from-violet-500 to-blue-500 text-white rounded-lg hover:from-violet-600 hover:to-blue-600 transition-all font-medium shadow-lg disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                  >
                    {uploading ? (
                      <>
                        <FontAwesomeIcon icon={faSpinner} spin />
                        上传中...
                      </>
                    ) : (
                      <>
                        <FontAwesomeIcon icon={faCloudUploadAlt} />
                        开始上传
                      </>
                    )}
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>,
    document.body
  );
}
