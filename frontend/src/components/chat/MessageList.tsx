'use client';

/**
 * MessageList - Gemini Style Chat Messages
 */

import { Message, ActionButton, LayerCompletedMessage, DimensionReportMessage, FileMessage } from '@/types';
import ThinkingIndicator, { WaveThinkingIndicator } from './ThinkingIndicator';
import MessageBubble from './MessageBubble';
import LayerReportMessage from './LayerReportMessage';
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
  currentLayer?: number;
  dimensionContents?: Map<string, string>;
}

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
  dimensionContents,
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
    <div className="space-y-4">
      {/* Welcome message - Gemini style */}
      {messages.length === 0 && (
        <div className="flex justify-center py-12 animate-fade-in">
          <div className="text-center max-w-md">
            {/* Animated icon */}
            <div className="inline-flex items-center justify-center w-20 h-20 rounded-3xl bg-gradient-to-br from-green-500/20 to-cyan-500/10 border border-green-500/20 mb-6 animate-float">
              <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-br from-green-400 to-cyan-400 rounded-2xl blur-xl opacity-50" />
                <svg className="relative w-10 h-10 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
              </div>
            </div>
            
            <h3 className="text-xl font-semibold text-white mb-2">
              欢迎使用村庄规划助手
            </h3>
            <p className="text-zinc-400 text-sm mb-6">
              请输入村庄信息，开始您的规划任务
            </p>
            
            {/* Quick tips */}
            <div className="grid grid-cols-1 gap-2 text-left">
              {[
                { icon: '📍', text: '输入村庄名称和位置' },
                { icon: '📝', text: '描述规划目标和需求' },
                { icon: '🎯', text: 'AI 生成专业规划方案' },
              ].map((tip, i) => (
                <div key={i} className="flex items-center gap-3 px-4 py-2.5 bg-[#1a1a1a] rounded-xl border border-[#2d2d2d]">
                  <span className="text-lg">{tip.icon}</span>
                  <span className="text-sm text-zinc-300">{tip.text}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Messages */}
      {messages.map((message) => {
        // Dimension report streaming
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

        // Layer completed
        if (message.type === 'layer_completed') {
          const layerMsg = message as LayerCompletedMessage;
          const hasStreamingDimensions = Object.keys(layerMsg.dimensionReports || {}).length > 0;
          
          return (
            <div key={message.id} className="w-full mb-4">
              <LayerReportMessage
                message={layerMsg}
                onOpenInSidebar={onOpenInSidebar}
                onToggleAllDimensions={(expand) => handleToggleAllDimensions(layerMsg.layer, expand)}
                currentLayer={currentLayer}
                hasStreamingDimensions={hasStreamingDimensions}
                dimensionContents={dimensionContents}
              />
            </div>
          );
        }

        // File message
        if (message.type === 'file') {
          const fileMsg = message as FileMessage;
          const previewContent = fileMsg.fileContent?.slice(0, 500) || '';
          const hasMoreContent = (fileMsg.fileContent?.length || 0) > 500;
          
          return (
            <div key={message.id} className="flex justify-end mb-4 animate-slide-up">
              <div className="max-w-[70%] bg-gradient-to-r from-green-600 to-green-500 text-white rounded-2xl rounded-br-md px-4 py-3 shadow-lg shadow-green-500/20">
                {/* File header */}
                <div className="flex items-center gap-2 mb-2 pb-2 border-b border-white/20">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <span className="font-medium text-sm">{fileMsg.filename}</span>
                  <span className="text-xs opacity-75">({formatBytes(fileMsg.fileSize)})</span>
                </div>
                
                {/* Content preview */}
                {previewContent && (
                  <div className="bg-black/20 rounded-lg p-3 text-sm font-mono whitespace-pre-wrap overflow-hidden max-h-40 text-white/90">
                    {previewContent}
                    {hasMoreContent && (
                      <span className="text-white/50">... (内容已截断)</span>
                    )}
                  </div>
                )}
                
                {/* Timestamp */}
                <div className="flex justify-end mt-2 text-[10px] text-white/60 font-medium">
                  {new Date(message.timestamp).toLocaleTimeString()}
                </div>
              </div>
            </div>
          );
        }

        // Default message bubble
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

      {/* Thinking indicator - Gemini style */}
      {thinkingState && thinkingMessage && (
        <div className="flex justify-start mb-4 animate-fade-in">
          <div className="max-w-[70%] bg-[#1e1e1e] border border-[#2d2d2d] rounded-2xl rounded-bl-md px-4 py-3">
            <ThinkingIndicator state={thinkingState} message={thinkingMessage} size="md" />
          </div>
        </div>
      )}

      {/* Typing indicator */}
      {isTyping && !thinkingState && (
        <div className="flex justify-start mb-4 animate-fade-in">
          <div className="flex items-center gap-3 px-4 py-3 bg-[#1e1e1e] border border-[#2d2d2d] rounded-2xl rounded-bl-md">
            {/* Animated dots */}
            <div className="flex gap-1">
              <div className="w-2 h-2 bg-green-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <div className="w-2 h-2 bg-green-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <div className="w-2 h-2 bg-green-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
            <span className="text-sm text-zinc-400">正在思考...</span>
          </div>
        </div>
      )}
    </div>
  );
}
