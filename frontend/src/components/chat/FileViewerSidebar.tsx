'use client';

/**
 * FileViewerSidebar - 文件查看器侧边栏
 * 用于显示上传的文件内容（如 .docx, .txt 等）
 * 复用 LayerSidebar 的动画和 Portal 渲染逻辑
 */

import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faTimes, faFileAlt, faCopy, faCheck } from '@fortawesome/free-solid-svg-icons';
import type { FileMessage } from '@/types';
import MarkdownRenderer from '@/components/MarkdownRenderer';

interface FileViewerSidebarProps {
  file: FileMessage | null;
  onClose: () => void;
}

export default function FileViewerSidebar({ file, onClose }: FileViewerSidebarProps) {
  const [mounted, setMounted] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setMounted(true);
    document.body.style.overflow = 'hidden';

    return () => {
      document.body.style.overflow = 'unset';
    };
  }, []);

  // 复制文件内容到剪贴板
  const handleCopy = async () => {
    if (file?.fileContent) {
      try {
        await navigator.clipboard.writeText(file.fileContent);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch (err) {
        console.error('[FileViewerSidebar] Failed to copy content:', err);
      }
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
      transition: {
        duration: 0.2,
      },
    },
  };

  if (!mounted || !file) return null;

  // 格式化文件大小
  const formatFileSize = (bytes?: number): string => {
    if (!bytes) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
  };

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
        className="fixed right-0 top-0 bottom-0 w-[600px] max-w-[90vw] bg-white/95 backdrop-blur-xl shadow-2xl flex flex-col z-[9999] overflow-hidden border-l border-white/20"
      >
        {/* Header - Gradient */}
        <div
          className="px-5 py-4 flex justify-between items-center border-b border-gray-100"
          style={{
            background: 'linear-gradient(135deg, #10b981 0%, #059669 50%, #047857 100%)',
          }}
        >
          <div className="flex items-center gap-3">
            <FontAwesomeIcon icon={faFileAlt} className="text-white text-xl" />
            <div>
              <h2 className="text-lg font-bold text-white">{file.filename}</h2>
              <p className="text-xs text-white/80">
                {formatFileSize(file.fileSize)} • 上传于 {new Date(file.timestamp).toLocaleTimeString()}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Copy button */}
            <motion.button
              whileHover={{ scale: 1.1 }}
              whileTap={{ scale: 0.9 }}
              onClick={handleCopy}
              className="w-8 h-8 flex items-center justify-center text-white/80 hover:text-white rounded-full hover:bg-white/10 transition-colors"
              title="复制内容"
            >
              <FontAwesomeIcon icon={copied ? faCheck : faCopy} />
            </motion.button>
            {/* Close button */}
            <motion.button
              whileHover={{ scale: 1.1, rotate: 90 }}
              whileTap={{ scale: 0.9 }}
              onClick={onClose}
              className="w-8 h-8 flex items-center justify-center text-white/80 hover:text-white rounded-full hover:bg-white/10 transition-colors"
            >
              <FontAwesomeIcon icon={faTimes} />
            </motion.button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5">
          {file.fileContent ? (
            <MarkdownRenderer content={file.fileContent} className="bg-gray-50 rounded-lg p-4 border border-gray-200" />
          ) : (
            <div className="flex flex-col items-center justify-center py-16 text-gray-400">
              <FontAwesomeIcon icon={faFileAlt} className="text-5xl mb-4" />
              <p className="text-center">暂无文件内容</p>
            </div>
          )}
        </div>
      </motion.div>
    </>,
    document.body
  );
}
