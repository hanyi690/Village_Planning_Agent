'use client';

/**
 * ExportDialog - Export planning documents dialog
 *
 * Two export modes:
 * 1. Layer reports: select layer + format (JSON/MD/DOCX)
 * 2. Planning text: export complete planning document as DOCX
 */

import React, { memo, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  faFileExport,
  faTimes,
  faSpinner,
  faFileCode,
  faFileAlt,
  faFileWord,
  faBook,
  faDownload,
  faLayerGroup,
  faFileLines,
} from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import { planningApi } from '../api/planning-api';
import { getFormatDisplayName } from '../utils/download';

type ExportMode = 'layer' | 'planning_text';
type LayerFormat = 'json' | 'md' | 'docx';
type LayerOption = '1' | '2' | '3' | 'all';

const FORMAT_OPTIONS: { format: LayerFormat; icon: typeof faFileCode; description: string }[] = [
  { format: 'json', icon: faFileCode, description: '结构化数据' },
  { format: 'md', icon: faFileAlt, description: 'Markdown格式' },
  { format: 'docx', icon: faFileWord, description: 'Word文档' },
];

const LAYER_OPTIONS: { layer: LayerOption; label: string }[] = [
  { layer: '1', label: 'L1 现状分析' },
  { layer: '2', label: 'L2 规划思路' },
  { layer: '3', label: 'L3 详细规划' },
  { layer: 'all', label: '全部层级' },
];

const MODE_OPTIONS: { mode: ExportMode; icon: typeof faLayerGroup; label: string; description: string }[] = [
  { mode: 'layer', icon: faLayerGroup, label: '分层报告', description: '按层级导出各维度报告' },
  { mode: 'planning_text', icon: faBook, label: '规划文本', description: '导出完整规划文档 (DOCX)' },
];

interface ExportDialogProps {
  sessionId: string;
  isOpen: boolean;
  onClose: () => void;
}

const ExportDialog = memo(function ExportDialog({
  sessionId,
  isOpen,
  onClose,
}: ExportDialogProps) {
  const [exportMode, setExportMode] = useState<ExportMode>('planning_text');
  const [selectedFormats, setSelectedFormats] = useState<LayerFormat[]>(['docx']);
  const [selectedLayers, setSelectedLayers] = useState<LayerOption[]>(['all']);
  const [isExporting, setIsExporting] = useState(false);
  const [downloadedFiles, setDownloadedFiles] = useState<string[]>([]);
  const [errors, setErrors] = useState<string[]>([]);

  // Prevent SSR mismatch
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => { setMounted(true); }, []);

  // Handle escape key
  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Prevent body scroll when dialog is open
  React.useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [isOpen]);

  // Reset state when dialog closes
  React.useEffect(() => {
    if (!isOpen) {
      setDownloadedFiles([]);
      setErrors([]);
    }
  }, [isOpen]);

  const toggleFormat = useCallback((format: LayerFormat) => {
    setSelectedFormats((prev) =>
      prev.includes(format)
        ? prev.filter((f) => f !== format)
        : [...prev, format]
    );
  }, []);

  const toggleLayer = useCallback((layer: LayerOption) => {
    if (layer === 'all') {
      setSelectedLayers((prev) => (prev.includes('all') ? [] : ['all']));
      return;
    }
    setSelectedLayers((prev) => {
      if (prev.includes('all')) return [layer];
      if (!prev.includes(layer)) return [...prev, layer];
      const remaining = prev.filter((l) => l !== layer);
      return remaining.length === 0 ? ['all'] : remaining;
    });
  }, []);

  const canExport = exportMode === 'planning_text'
    || (selectedFormats.length > 0 && selectedLayers.length > 0);

  const handleExport = useCallback(async () => {
    if (!sessionId) return;

    setIsExporting(true);
    setDownloadedFiles([]);
    setErrors([]);

    const succeeded: string[] = [];
    const failed: string[] = [];

    try {
      if (exportMode === 'planning_text') {
        const filename = await planningApi.exportPlanningTextDocx(sessionId, '村庄规划').catch((err) => {
          failed.push(err instanceof Error ? err.message : '导出规划文本失败');
          return '';
        });
        if (filename) succeeded.push(filename);
      } else {
        const layersToExport = selectedLayers.includes('all')
          ? [1, 2, 3]
          : selectedLayers.map(Number);

        const tasks: Promise<string>[] = [];

        for (const layer of layersToExport) {
          if (selectedFormats.includes('json')) {
            tasks.push(
              planningApi.exportLayerJson(sessionId, layer).catch((err) => {
                failed.push(err instanceof Error ? err.message : `导出 L${layer} JSON 失败`);
                return '';
              })
            );
          }
          if (selectedFormats.includes('md')) {
            tasks.push(
              planningApi.exportLayerMd(sessionId, layer).catch((err) => {
                failed.push(err instanceof Error ? err.message : `导出 L${layer} MD 失败`);
                return '';
              })
            );
          }
          if (selectedFormats.includes('docx')) {
            tasks.push(
              planningApi.exportLayerDocx(sessionId, layer, false).catch((err) => {
                failed.push(err instanceof Error ? err.message : `导出 L${layer} DOCX 失败`);
                return '';
              })
            );
          }
        }

        const results = await Promise.all(tasks);
        for (const filename of results) {
          if (filename) succeeded.push(filename);
        }
      }

      setDownloadedFiles(succeeded);
      if (failed.length > 0) setErrors(failed);
    } catch {
      setErrors(['导出失败，请稍后重试']);
    } finally {
      setIsExporting(false);
    }
  }, [sessionId, exportMode, selectedFormats, selectedLayers]);

  if (!mounted) return null;

  return createPortal(
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 bg-black/30 backdrop-blur-sm z-[9998]"
            onClick={onClose}
          />

          {/* Dialog */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
            className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[400px] max-w-[90vw] bg-white rounded-2xl shadow-2xl z-[9999] overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-emerald-100 to-teal-100 flex items-center justify-center">
                  <FontAwesomeIcon icon={faFileExport} className="text-emerald-600" style={{ width: 16, height: 16 }} />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-slate-800">导出文档</h2>
                  <p className="text-xs text-slate-400">选择导出类型和格式</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
              >
                <FontAwesomeIcon icon={faTimes} style={{ width: 14, height: 14 }} />
              </button>
            </div>

            {/* Content */}
            <div className="px-5 py-4 space-y-4">
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs text-emerald-800">
                <b>v1 客户端导出</b>：分层报告导出 JSON/Markdown；规划文本导出 Markdown。
                DELIVER 阶段产物（HTML/PNG/GeoJSON）请在交付完成后从合规面板或空间成果图查看。
              </div>
              {/* Export Mode Selection */}
              <div>
                <label className="text-sm font-medium text-slate-600 mb-2 block">导出类型</label>
                <div className="grid grid-cols-2 gap-2">
                  {MODE_OPTIONS.map((opt) => (
                    <button
                      key={opt.mode}
                      onClick={() => setExportMode(opt.mode)}
                      className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all ${
                        exportMode === opt.mode
                          ? 'bg-emerald-100 text-emerald-700 border border-emerald-200'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                      }`}
                    >
                      <FontAwesomeIcon
                        icon={opt.icon}
                        className={exportMode === opt.mode ? 'text-emerald-500' : 'text-slate-400'}
                        style={{ width: 14, height: 14 }}
                      />
                      <span>{opt.label}</span>
                    </button>
                  ))}
                </div>
                <p className="text-xs text-slate-400 mt-1.5">
                  {exportMode === 'planning_text'
                    ? '导出已生成的完整规划文本文档 (DOCX)'
                    : '按层级导出各维度分析报告'}
                </p>
              </div>

              {/* Layer + Format options (only for layer mode) */}
              {exportMode === 'layer' && (
                <>
                  {/* Layer Selection */}
                  <div>
                    <label className="text-sm font-medium text-slate-600 mb-2 block">层级</label>
                    <div className="flex flex-wrap gap-2">
                      {LAYER_OPTIONS.map((opt) => (
                        <button
                          key={opt.layer}
                          onClick={() => toggleLayer(opt.layer)}
                          className={`px-3 py-1.5 rounded-lg text-sm transition-all ${
                            selectedLayers.includes(opt.layer)
                              ? 'bg-emerald-100 text-emerald-700 border border-emerald-200'
                              : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                          }`}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Format Selection */}
                  <div>
                    <label className="text-sm font-medium text-slate-600 mb-2 block">格式</label>
                    <div className="grid grid-cols-3 gap-2">
                      {FORMAT_OPTIONS.map((opt) => (
                        <button
                          key={opt.format}
                          onClick={() => toggleFormat(opt.format)}
                          className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all ${
                            selectedFormats.includes(opt.format)
                              ? 'bg-emerald-100 text-emerald-700 border border-emerald-200'
                              : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                          }`}
                        >
                          <FontAwesomeIcon
                            icon={opt.icon}
                            className={selectedFormats.includes(opt.format) ? 'text-emerald-500' : 'text-slate-400'}
                            style={{ width: 14, height: 14 }}
                          />
                          <span>{getFormatDisplayName(opt.format)}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}

              {/* Planning text mode info */}
              {exportMode === 'planning_text' && (
                <div className="bg-emerald-50 rounded-lg px-4 py-3 flex items-center gap-3">
                  <FontAwesomeIcon icon={faFileLines} className="text-emerald-500" style={{ width: 20, height: 20 }} />
                  <div>
                    <p className="text-sm text-emerald-700 font-medium">完整规划文本</p>
                    <p className="text-xs text-emerald-600">导出已存储的最新版本为 DOCX 格式</p>
                  </div>
                </div>
              )}

              {/* Downloaded Files */}
              {downloadedFiles.length > 0 && (
                <div className="pt-2">
                  <label className="text-sm font-medium text-slate-600 mb-2 block">已下载</label>
                  <div className="space-y-1">
                    {downloadedFiles.map((filename) => (
                      <div key={filename} className="flex items-center gap-2 text-sm text-slate-500">
                        <FontAwesomeIcon icon={faDownload} className="text-emerald-500" style={{ width: 12, height: 12 }} />
                        <span>{filename}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Errors */}
              {errors.length > 0 && (
                <div className="pt-2">
                  <label className="text-sm font-medium text-red-600 mb-2 block">错误</label>
                  <div className="space-y-1">
                    {errors.map((err, i) => (
                      <div key={i} className="text-sm text-red-500">
                        {err}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-5 py-4 border-t border-slate-100 shrink-0 flex gap-3">
              <button
                onClick={onClose}
                className="flex-1 py-2.5 rounded-lg text-sm text-slate-600 bg-slate-100 hover:bg-slate-200 transition-colors"
              >
                关闭
              </button>
              <button
                onClick={handleExport}
                disabled={isExporting || !canExport}
                className="flex-1 py-2.5 rounded-lg text-sm text-white bg-emerald-500 hover:bg-emerald-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {isExporting ? (
                  <>
                    <FontAwesomeIcon icon={faSpinner} className="animate-spin" style={{ width: 14, height: 14 }} />
                    <span>导出中...</span>
                  </>
                ) : (
                  <>
                    <FontAwesomeIcon icon={faDownload} style={{ width: 14, height: 14 }} />
                    <span>导出</span>
                  </>
                )}
              </button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>,
    document.body
  );
});

export default ExportDialog;