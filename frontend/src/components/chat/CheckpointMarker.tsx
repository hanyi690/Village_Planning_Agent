'use client';

/**
 * CheckpointMarker - 对话时间线中的检查点标记
 *
 * 类似 VS Code Copilot / AI SDK 的 Checkpoint 组件设计
 * 在每个层级完成后显示，支持一键回滚
 *
 * 检查点类型：
 * - key: 关键检查点（层级完成），醒目标记，可回滚
 * - regular: 普通检查点（中间节点），淡化展示
 */

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faBookmark, faUndo, faSpinner, faExclamationTriangle, faCircle } from '@fortawesome/free-solid-svg-icons';
import { formatFullTimestamp, parseTimestamp } from '@/lib/utils';
import type { Checkpoint } from '@/types';

interface CheckpointMarkerProps {
  checkpoint: Checkpoint;
  onRollback: (checkpointId: string) => Promise<void>;
  isRollingBack?: boolean;
}

export default function CheckpointMarker({
  checkpoint,
  onRollback,
  isRollingBack = false,
}: CheckpointMarkerProps) {
  const [showConfirm, setShowConfirm] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);

  const layerNames: Record<number, string> = {
    1: '现状分析',
    2: '规划思路',
    3: '详细规划',
  };

  const layerName = layerNames[checkpoint.layer] || `第 ${checkpoint.layer} 层`;
  
  // 检查点类型
  const isKeyCheckpoint = checkpoint.type === 'key';
  
  // ✅ 使用安全的时间解析函数
  const parsedDate = parseTimestamp(checkpoint.timestamp);
  const timestamp = parsedDate 
    ? formatFullTimestamp(checkpoint.timestamp) 
    : '刚刚';  // 解析失败时显示"刚刚"

  const handleRollbackClick = () => {
    setShowConfirm(true);
  };

  const handleConfirmRollback = async () => {
    setIsProcessing(true);
    try {
      await onRollback(checkpoint.checkpoint_id);
      setShowConfirm(false);
    } catch (error) {
      console.error('[CheckpointMarker] Rollback failed:', error);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleCancel = () => {
    setShowConfirm(false);
  };

  // 根据检查点类型设置样式
  const containerClass = isKeyCheckpoint
    ? "relative my-4"  // 关键检查点：正常间距
    : "relative my-2 opacity-60";  // 普通检查点：减小间距，淡化

  const iconGradient = isKeyCheckpoint
    ? "bg-gradient-to-br from-violet-500 to-blue-500"  // 关键检查点：醒目渐变
    : "bg-gradient-to-br from-gray-400 to-gray-500";  // 普通检查点：灰色

  const iconSize = isKeyCheckpoint ? "w-8 h-8" : "w-6 h-6";
  const separatorWidth = isKeyCheckpoint ? "w-16" : "w-8";

  return (
    <div className={containerClass}>
      {/* 主时间线标记 */}
      <div className="flex items-center gap-3 py-2">
        {/* 左侧：图标和分隔线 */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className={`${iconSize} rounded-full ${iconGradient} flex items-center justify-center shadow-lg`}
          >
            <FontAwesomeIcon 
              icon={isKeyCheckpoint ? faBookmark : faCircle} 
              className={`text-white ${isKeyCheckpoint ? 'text-sm' : 'text-xs'}`} 
            />
          </motion.div>
          
          {/* 分隔线 */}
          <div className={`${separatorWidth} h-0.5 bg-gradient-to-r from-violet-300 to-gray-200`} />
        </div>

        {/* 中间：信息 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`text-sm ${isKeyCheckpoint ? 'font-medium' : 'font-normal'} text-gray-700`}>
              {layerName} 完成
            </span>
            {isKeyCheckpoint && checkpoint.phase && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-violet-100 text-violet-600">
                关键点
              </span>
            )}
            <span className="text-xs text-gray-400">
              {timestamp}
            </span>
          </div>
          {checkpoint.description && (
            <p className="text-xs text-gray-500 truncate mt-0.5">
              {checkpoint.description}
            </p>
          )}
        </div>

        {/* 右侧：回滚按钮（仅关键检查点显示） */}
        {isKeyCheckpoint && (
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={handleRollbackClick}
            disabled={isRollingBack || isProcessing}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-violet-600 bg-violet-50 hover:bg-violet-100 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <FontAwesomeIcon icon={faUndo} className="text-xs" />
            <span>恢复到此点</span>
          </motion.button>
        )}
      </div>

      {/* 确认弹窗 */}
      <AnimatePresence>
        {showConfirm && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="absolute left-0 right-0 top-full mt-2 z-50 bg-white rounded-xl shadow-xl border border-gray-100 p-4"
          >
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0">
                <FontAwesomeIcon
                  icon={faExclamationTriangle}
                  className="text-amber-500"
                />
              </div>
              
              <div className="flex-1">
                <h4 className="text-sm font-semibold text-gray-900 mb-1">
                  确认回滚
                </h4>
                <p className="text-xs text-gray-500 mb-3">
                  将恢复到「{layerName}」完成时的状态，之后的内容将被清除。此操作不可撤销。
                </p>
                
                <div className="flex gap-2">
                  <button
                    onClick={handleCancel}
                    disabled={isProcessing}
                    className="px-3 py-1.5 text-xs font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors disabled:opacity-50"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleConfirmRollback}
                    disabled={isProcessing}
                    className="px-3 py-1.5 text-xs font-medium text-white bg-violet-500 hover:bg-violet-600 rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1.5"
                  >
                    {isProcessing ? (
                      <>
                        <FontAwesomeIcon icon={faSpinner} spin className="text-xs" />
                        <span>恢复中...</span>
                      </>
                    ) : (
                      <span>确认恢复</span>
                    )}
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
