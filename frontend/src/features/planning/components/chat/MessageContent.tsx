'use client';

/**
 * MessageContent Components
 * Individual message type renderers
 */

import { Message, ProgressMessage, DimensionReportMessage } from '../../types';
import { isProgressMessage, isLayerCompletedMessage, isDimensionReportMessage } from '../../types';
import StreamingText from './StreamingText';
import LayerReportMessage from './LayerReportMessage';
import MarkdownRenderer from '@/features/planning/components/ui/MarkdownRenderer';
import { formatWordCount } from '@/features/planning/utils';

interface MessageContentProps {
  message: Message;
  enableStreaming?: boolean;
  dimensionContents?: Record<string, string>; // 实时流式内容（用于 token 级显示）
}

// Progress Message Renderer
function renderProgressMessage(message: ProgressMessage) {
  return (
    <>
      <div className="mb-2">{message.content}</div>
      <div
        className="w-full rounded-full h-2 overflow-hidden"
        style={{ background: 'var(--overlay-cream-light)' }}
      >
        <div
          className="h-2 rounded-full transition-all duration-300 shadow-sm"
          style={{ width: `${message.progress}%`, background: 'var(--text-cream-primary)' }}
          role="progressbar"
          aria-valuenow={message.progress}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
      {message.currentLayer && (
        <div className="text-xs mt-1.5 opacity-90 font-medium flex items-center gap-1">
          <i className="fas fa-layer-group" />
          当前: {message.currentLayer}
        </div>
      )}
    </>
  );
}

// Dimension Report Message Renderer
function renderDimensionReportMessage(message: DimensionReportMessage) {
  return (
    <div className="bg-blue-50 p-3 rounded-lg border border-blue-200">
      <div className="flex items-center gap-2 mb-2">
        <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-500 text-xs font-bold text-white">
          {message.layer}
        </span>
        <span className="font-medium text-blue-700">{message.dimensionName}</span>
        {/* Revision marker */}
        {message.isRevision && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-600">
            修复
          </span>
        )}
        {/* Streaming state indicator */}
        {message.streamingState === 'streaming' && (
          <span className="text-xs text-blue-500 animate-pulse">生成中...</span>
        )}
        {message.streamingState === 'error' && (
          <span className="text-xs text-red-500">生成错误</span>
        )}
      </div>
      {/* Markdown rendered content */}
      <div className="text-sm text-gray-700">
        <MarkdownRenderer content={message.content} className="text-sm" />
      </div>
      {/* Word count when completed */}
      {message.streamingState === 'completed' && message.wordCount > 0 && (
        <div className="mt-2 text-xs text-gray-500">
          字数: {formatWordCount(message.wordCount)}
        </div>
      )}
      {/* Progress during streaming */}
      {message.progress && message.streamingState === 'streaming' && (
        <div className="mt-2 text-xs text-gray-500">
          进度: {message.progress.current}/{message.progress.total} 字
        </div>
      )}
    </div>
  );
}

// Main Message Content Renderer
export default function MessageContent(props: MessageContentProps) {
  // SSE already updates message.content incrementally. A second client-side
  // typewriter pass would replay historical messages whenever the panel mounts.
  const { message, enableStreaming = false } = props;

  switch (message.type) {
    case 'text':
      if (message.role === 'user') {
        return <div className="whitespace-pre-wrap leading-relaxed">{message.content}</div>;
      }

      return (
        <div className="min-w-0 overflow-x-auto leading-relaxed">
          {enableStreaming && message.streamingState === 'streaming' ? (
            <StreamingText
              content={message.content}
              speed={50}
              enabled
            />
          ) : (
            <MarkdownRenderer
              content={message.content}
              className="text-sm [&_p]:my-0 [&_p+_*]:mt-2 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:my-1"
            />
          )}
        </div>
      );

    case 'progress':
      return isProgressMessage(message) ? renderProgressMessage(message) : null;

    case 'layer_completed':
      return isLayerCompletedMessage(message) ? (
        <LayerReportMessage message={message} />
      ) : null;

    case 'dimension_report':
      return isDimensionReportMessage(message) ? renderDimensionReportMessage(message) : null;

    case 'file':
      return (
        <div className="flex items-center gap-2 p-2 bg-gray-100 rounded-lg">
          <i className="fas fa-file text-gray-500" />
          <span className="text-sm">{message.filename}</span>
        </div>
      );

    default:
      return null;
  }
}
