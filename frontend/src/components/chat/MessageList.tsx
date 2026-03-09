'use client';

/**
 * MessageList - Renders list of chat messages with Gemini-style enhancements
 */

import { Message, ActionButton, LayerCompletedMessage, DimensionReportMessage, FileMessage, Checkpoint } from '@/types';
import ThinkingIndicator, { WaveThinkingIndicator } from './ThinkingIndicator';
import MessageBubble from './MessageBubble';
import LayerReportMessage from './LayerReportMessage';
import DimensionReportStreaming from './DimensionReportStreaming';
import CheckpointMarker from './CheckpointMarker';
import { parseTimestamp } from '@/lib/utils';

interface MessageListProps {
  messages: Message[];
  isTyping?: boolean;
  thinkingState?: 'analyzing' | 'generating' | 'reviewing' | 'processing' | 'waiting';
  thinkingMessage?: string;
  onAction?: (action: ActionButton, message: Message) => void;
  enableStreaming?: boolean;
  onOpenInSidebar?: (layer: number) => void;
  onViewLayerDetails?: (layer: number) => void;
  onToggleAllDimensions?: (layer: number, expand: boolean) => void;
  currentLayer?: number;
  dimensionContents?: Map<string, string>;  // NEW: 实时维度内容（解决并行更新竞态）
  // Checkpoint 回滚
  checkpoints?: Checkpoint[];
  onRollback?: (checkpointId: string) => Promise<void>;
  isRollingBack?: boolean;
}

// 格式化文件大小
function formatBytes(bytes: number | undefined): string {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export default function MessageList({
  messages,
  isTyping,
  thinkingState,
  thinkingMessage,
  onAction,
  enableStreaming = true,
  onOpenInSidebar,
  onViewLayerDetails,
  onToggleAllDimensions,
  currentLayer,
  dimensionContents,  // NEW: 实时维度内容
  checkpoints = [],
  onRollback,
  isRollingBack = false,
}: MessageListProps) {
  const handleCopy = (message: Message) => {
    if (message.type === 'text') {
      navigator.clipboard.writeText(message.content);
    }
  };

  const handleRegenerate = (message: Message) => {
    console.log('Regenerate message:', message.id);
  };

  const handleViewLayerDetails = (layer: number) => {
    onViewLayerDetails?.(layer);
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
        // Special handling for dimension_report messages (streaming dimension content)
        if (message.type === 'dimension_report') {
          const dimMsg = message as DimensionReportMessage;
          return (
            <div key={message.id} className="w-full mb-2">
              <DimensionReportStreaming
                layer={dimMsg.layer}
                dimensionKey={dimMsg.dimensionKey}
                dimensionName={dimMsg.dimensionName}
                content={dimMsg.content}
                streamingState={dimMsg.streamingState}
                wordCount={dimMsg.wordCount}
              />
            </div>
          );
        }

        // Special handling for layer_completed messages
        if (message.type === 'layer_completed') {
          const layerMsg = message as LayerCompletedMessage;
          // 计算是否有流式维度（有维度报告且有内容）
          const hasStreamingDimensions = Object.keys(layerMsg.dimensionReports || {}).length > 0;
          
          // 查找对应层级的 checkpoint
          const layerCheckpoint = checkpoints.find(cp => cp.layer === layerMsg.layer);
          
          return (
            <div key={message.id} className="w-full mb-4">
              <LayerReportMessage
                message={layerMsg}
                onOpenInSidebar={onOpenInSidebar}
                onToggleAllDimensions={(expand) => handleToggleAllDimensions(layerMsg.layer, expand)}
                currentLayer={currentLayer}
                hasStreamingDimensions={hasStreamingDimensions}
                dimensionContents={dimensionContents}  // NEW: 传递实时维度内容
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

        // 文件消息渲染 - 显示文件名 + 内容预览
        if (message.type === 'file') {
          const fileMsg = message as FileMessage;
          const previewContent = fileMsg.fileContent?.slice(0, 500) || '';
          const hasMoreContent = (fileMsg.fileContent?.length || 0) > 500;
          
          return (
            <div key={message.id} className="flex justify-end mb-4">
              <div className="max-w-[70%] bg-green-100 border border-green-300 text-gray-900 rounded-2xl px-4 py-3 shadow-md">
                {/* 文件头部信息 */}
                <div className="flex items-center gap-2 mb-2 pb-2 border-b border-white/20">
                  <i className="fas fa-file-alt text-lg" />
                  <span className="font-medium">{fileMsg.filename}</span>
                  <span className="text-xs opacity-75">({formatBytes(fileMsg.fileSize)})</span>
                </div>
                
                {/* 内容预览 */}
                {previewContent && (
                  <div className="bg-white/10 rounded-lg p-2 text-sm font-mono whitespace-pre-wrap overflow-hidden max-h-40">
                    {previewContent}
                    {hasMoreContent && (
                      <span className="text-gray-500">... (内容已截断)</span>
                    )}
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

        // Default message bubble rendering
        return (
          <MessageBubble
            key={message.id}
            message={message}
            onAction={onAction}
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