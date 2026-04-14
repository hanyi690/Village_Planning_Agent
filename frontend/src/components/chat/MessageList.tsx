'use client';

/**
 * MessageList - Renders list of chat messages with Gemini-style enhancements
 */

import { useMemo } from 'react';
import {
  Message,
  LayerCompletedMessage,
  DimensionReportMessage,
  FileMessage,
  Checkpoint,
  GisResultMessage,
  ToolStatusMessage,
} from '@/types';
import { isGisResultMessage, isToolStatusMessage } from '@/types/message/message-guards';
import ThinkingIndicator from './ThinkingIndicator';
import MessageBubble from './MessageBubble';
import LayerReportMessage from './LayerReportMessage';
import CheckpointMarker from './CheckpointMarker';
import ToolStatusCard from './ToolStatusCard';
import GisResultCard from './GisResultCard';
import { parseTimestamp } from '@/lib/utils';
import { formatFileSize } from '@/lib/utils';
import { DEFAULT_IMAGE_FORMAT } from '@/lib/constants';
import MarkdownRenderer from '@/components/MarkdownRenderer';

interface MessageListProps {
  messages: Message[];
  isTyping?: boolean;
  thinkingState?: 'analyzing' | 'generating' | 'reviewing' | 'processing' | 'waiting';
  thinkingMessage?: string;
  enableStreaming?: boolean;
  onOpenInSidebar?: (layer: number) => void;
  onViewLayerDetails?: (layer: number) => void;
  onToggleAllDimensions?: (layer: number, expand: boolean) => void;
  currentLayer?: number;
  dimensionContents?: Record<string, string>;
  // Checkpoint 回滚
  checkpoints?: Checkpoint[];
  onRollback?: (checkpointId: string) => Promise<void>;
  isRollingBack?: boolean;
  onViewFileInSidebar?: (file: FileMessage) => void;
}

export default function MessageList({
  messages,
  isTyping,
  thinkingState,
  thinkingMessage,
  enableStreaming = true,
  onOpenInSidebar,
  onViewLayerDetails: _onViewLayerDetails,
  onToggleAllDimensions,
  currentLayer,
  dimensionContents,
  checkpoints = [],
  onRollback,
  isRollingBack = false,
  onViewFileInSidebar,
}: MessageListProps) {
  // Pre-compute checkpoint lookups to avoid O(n*m) filter+sort in render loop
  const keyCheckpointByLayer = useMemo(() => {
    const map = new Map<number, Checkpoint>();
    for (const cp of checkpoints) {
      if (cp.type === 'key') {
        const existing = map.get(cp.layer);
        // Keep the latest timestamp
        if (!existing || cp.timestamp > existing.timestamp) {
          map.set(cp.layer, cp);
        }
      }
    }
    return map;
  }, [checkpoints]);

  const revisionCheckpointByLayer = useMemo(() => {
    const map = new Map<number, Checkpoint>();
    for (const cp of checkpoints) {
      if (cp.isRevision) {
        const existing = map.get(cp.layer);
        // Keep the latest timestamp
        if (!existing || cp.timestamp > existing.timestamp) {
          map.set(cp.layer, cp);
        }
      }
    }
    return map;
  }, [checkpoints]);

  const handleCopy = (message: Message) => {
    if (message.type === 'text') {
      navigator.clipboard.writeText(message.content);
    }
  };

  const handleRegenerate = (message: Message) => {
    console.log('Regenerate message:', message.id);
  };

  const handleToggleAllDimensions = (layer: number, expand: boolean) => {
    onToggleAllDimensions?.(layer, expand);
  };

  return (
    <div>
      {/* Welcome message */}
      {messages.length === 0 && (
        <div className="flex justify-start mb-4">
          <div className="max-w-[70%] bg-white border border-gray-200 rounded-2xl px-6 py-4 shadow-sm">
            <div className="text-center text-gray-600">
              <i className="fas fa-robot text-3xl mb-3 text-green-600" />
              <p className="text-lg font-medium mb-1">欢迎使用村庄规划助手</p>
              <p className="text-sm opacity-75">请输入村庄信息，开始您的规划任务</p>
            </div>
          </div>
        </div>
      )}

      {/* Regular messages - 包含所有消息类型 */}
      {messages.map((message) => {
        // dimension_report messages are no longer rendered independently
        // They are aggregated into layer_report messages for cleaner display

        // Special handling for layer_completed messages
        if (message.type === 'layer_completed') {
          const layerMsg = message as LayerCompletedMessage;
          // 计算是否有流式维度（有维度报告且有内容）
          const hasStreamingDimensions = Object.keys(layerMsg.dimensionReports || {}).length > 0;

          // Use pre-computed checkpoint lookup
          const layerCheckpoint = keyCheckpointByLayer.get(layerMsg.layer);

          return (
            <div key={message.id} className="w-full mb-4">
              <LayerReportMessage
                message={layerMsg}
                onOpenInSidebar={onOpenInSidebar}
                onToggleAllDimensions={(expand) =>
                  handleToggleAllDimensions(layerMsg.layer, expand)
                }
                currentLayer={currentLayer}
                hasStreamingDimensions={hasStreamingDimensions}
                dimensionContents={dimensionContents} // NEW: 传递实时维度内容
              />

              {/* Checkpoint 回滚标记 */}
              {layerCheckpoint && onRollback && (
                <CheckpointMarker
                  checkpoint={layerCheckpoint}
                  onRollback={onRollback}
                  isRollingBack={isRollingBack}
                />
              )}
            </div>
          );
        }

        // dimension_report revision messages with checkpoint marker
        if (message.type === 'dimension_report' && (message as DimensionReportMessage).isRevision) {
          const dimMsg = message as DimensionReportMessage;

          // Use pre-computed checkpoint lookup
          const revisionCheckpoint = revisionCheckpointByLayer.get(dimMsg.layer);

          return (
            <div key={message.id} className="w-full mb-4">
              <MessageBubble
                message={message}
                onCopy={handleCopy}
                onRegenerate={handleRegenerate}
                enableStreaming={enableStreaming}
                dimensionContents={dimensionContents}
              />
              {/* Revision checkpoint marker */}
              {revisionCheckpoint && onRollback && (
                <CheckpointMarker
                  checkpoint={revisionCheckpoint}
                  onRollback={onRollback}
                  isRollingBack={isRollingBack}
                />
              )}
            </div>
          );
        }

        // 文件消息渲染 - 显示文件名 + 内容预览或图片缩略图
        if (message.type === 'file') {
          const fileMsg = message as FileMessage;
          const isImageFile = fileMsg.fileType === 'image' && (fileMsg.thumbnailBase64 || fileMsg.imageBase64);
          const imageSrc = isImageFile
            ? `data:image/${fileMsg.imageFormat || DEFAULT_IMAGE_FORMAT};base64,${fileMsg.thumbnailBase64 || fileMsg.imageBase64}`
            : null;
          const previewContent = !isImageFile ? (fileMsg.fileContent?.slice(0, 500) || '') : '';
          const hasMoreContent = !isImageFile && (fileMsg.fileContent?.length || 0) > 500;

          return (
            <div key={message.id} className="flex justify-end mb-4">
              <div className="max-w-[70%] bg-green-100 border border-green-300 text-gray-900 rounded-2xl px-4 py-3 shadow-md">
                {/* 文件头部信息 - 图标可点击 */}
                <div className="flex items-center gap-2 mb-2 pb-2 border-b border-white/20">
                  <button
                    onClick={() => onViewFileInSidebar?.(fileMsg)}
                    className="hover:opacity-70 transition-opacity"
                    title="在侧边栏查看完整文件"
                  >
                    <i className={`fas ${isImageFile ? 'fa-image' : 'fa-file-alt'} text-lg`} />
                  </button>
                  <span className="font-medium">{fileMsg.filename}</span>
                  {fileMsg.imageWidth && fileMsg.imageHeight && (
                    <span className="text-xs opacity-75">
                      ({fileMsg.imageWidth}x{fileMsg.imageHeight})
                    </span>
                  )}
                  <span className="text-xs opacity-75">({formatFileSize(fileMsg.fileSize)})</span>
                </div>

                {/* 图片缩略图 */}
                {isImageFile && imageSrc && (
                  <div className="mb-2">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={imageSrc}
                      alt={fileMsg.filename}
                      className="rounded-lg shadow-sm max-w-[200px] h-auto cursor-pointer hover:opacity-90 transition-opacity"
                      onClick={() => onViewFileInSidebar?.(fileMsg)}
                      title="点击查看大图"
                      loading="lazy"
                    />
                  </div>
                )}

                {/* 文档内容预览 */}
                {!isImageFile && previewContent && (
                  <div className="bg-white/10 rounded-lg p-2 text-sm font-mono whitespace-pre-wrap overflow-auto max-h-full">
                    <MarkdownRenderer content={previewContent} className="text-sm" />
                    {hasMoreContent && <span className="text-gray-500">... (内容已截断)</span>}
                  </div>
                )}

                {/* 时间戳 */}
                <div className="text-xs opacity-60 mt-2 text-right">
                  {(() => {
                    const date = parseTimestamp(message.timestamp);
                    return date ? date.toLocaleTimeString() : '刚刚';
                  })()}
                </div>
              </div>
            </div>
          );
        }

        // GIS result message rendering
        if (isGisResultMessage(message)) {
          return (
            <GisResultCard
              key={message.id}
              message={message as GisResultMessage}
            />
          );
        }

        // Tool status message rendering
        if (isToolStatusMessage(message)) {
          return (
            <ToolStatusCard
              key={message.id}
              message={message as ToolStatusMessage}
            />
          );
        }

        // Default message bubble rendering
        return (
          <MessageBubble
            key={message.id}
            message={message}
            onCopy={handleCopy}
            onRegenerate={handleRegenerate}
            enableStreaming={enableStreaming}
            dimensionContents={dimensionContents}
          />
        );
      })}

      {/* Thinking indicator */}
      {thinkingState && thinkingMessage && (
        <div className="flex justify-start mb-4">
          <div className="max-w-[70%] bg-white border border-gray-200 rounded-2xl px-4 py-3 shadow-sm">
            <ThinkingIndicator state={thinkingState} message={thinkingMessage} size="md" />
          </div>
        </div>
      )}

      {/* Typing indicator */}
      {isTyping && !thinkingState && (
        <div className="flex justify-start mb-4">
          <div className="max-w-[70%] bg-white border border-gray-200 rounded-2xl px-4 py-3 shadow-sm">
            <div className="typing-indicator flex items-center gap-2 text-sm text-gray-600">
              <i className="fas fa-spinner fa-spin text-green-600" />
              正在思考...
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
