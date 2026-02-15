'use client';

/**
 * MessageList - Renders list of chat messages with Gemini-style enhancements
 */

import { Message, ActionButton, LayerCompletedMessage, ReviewInteractionMessage, DimensionReportMessage } from '@/types';
import { isReviewInteractionMessage } from '@/types';
import ThinkingIndicator, { WaveThinkingIndicator } from './ThinkingIndicator';
import MessageBubble from './MessageBubble';
import LayerReportMessage from './LayerReportMessage';
import ReviewInteractionMessageComponent from './ReviewInteractionMessage';
import DimensionReportStreaming from './DimensionReportStreaming';

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
  // Review interaction callbacks
  onReviewApprove?: (message: ReviewInteractionMessage) => Promise<void>;
  onReviewReject?: (
    message: ReviewInteractionMessage,
    feedback: string,
    dimensions?: string[]
  ) => Promise<void>;
  onReviewRollback?: (
    message: ReviewInteractionMessage,
    checkpointId: string
  ) => Promise<void>;
  reviewDisabled?: boolean;
  currentLayer?: number;  // NEW: 当前活跃层
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
  onReviewApprove,
  onReviewReject,
  onReviewRollback,
  reviewDisabled = false,
  currentLayer,
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

      {/* Regular messages - 过滤掉 dimension_report 类型 */}
      {messages
        .filter(message => message.type !== 'dimension_report')
        .map((message) => {
        // Special handling for layer_completed messages
        if (message.type === 'layer_completed') {
          const layerMsg = message as LayerCompletedMessage;
          // 计算是否有流式维度（有维度报告且有内容）
          const hasStreamingDimensions = Object.keys(layerMsg.dimensionReports || {}).length > 0;
          
          return (
            <div key={message.id} className="w-full mb-4">
              <LayerReportMessage
                message={layerMsg}
                onOpenInSidebar={onOpenInSidebar}
                onToggleAll={(expand) => handleToggleAllDimensions(message.layer, expand)}
                currentLayer={currentLayer}
                hasStreamingDimensions={hasStreamingDimensions}
              />
            </div>
          );
        }

        // Special handling for dimension_report messages (streaming dimension content)
        if (message.type === 'dimension_report') {
          return (
            <div key={message.id} className="w-full mb-2">
              <DimensionReportStreaming
                layer={message.layer}
                dimensionKey={message.dimensionKey}
                dimensionName={message.dimensionName}
                content={message.content}
                streamingState={message.streamingState}
                wordCount={message.wordCount}
              />
            </div>
          );
        }

        // Special handling for review_interaction messages
        if (isReviewInteractionMessage(message)) {
          const reviewMsg = message as ReviewInteractionMessage;
          return (
            <div key={message.id} className="w-full mb-4">
              <ReviewInteractionMessageComponent
                message={reviewMsg}
                onApprove={onReviewApprove ? () => onReviewApprove(reviewMsg) : async () => {}}
                onReject={onReviewReject ? (feedback, dimensions) => onReviewReject(reviewMsg, feedback, dimensions) : async () => {}}
                onRollback={onReviewRollback ? (checkpointId) => onReviewRollback(reviewMsg, checkpointId) : async () => {}}
                disabled={reviewDisabled}
              />
            </div>
          );
        }

        // Filter out file messages (handled separately)
        if (message.type === 'file') return null;

        // Default message bubble rendering
        return (
          <MessageBubble
            key={message.id}
            message={message}
            onAction={onAction}
            onCopy={handleCopy}
            onRegenerate={handleRegenerate}
            enableStreaming={enableStreaming}
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
