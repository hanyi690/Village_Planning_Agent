'use client';

/**
 * MessageContent Components
 * Individual message type renderers
 */

import { Message, ActionButton, ProgressMessage } from '@/types';
import {
  isProgressMessage,
  isLayerCompletedMessage,
  isDimensionReportMessage,
} from '@/types';
import StreamingText from './StreamingText';
import ActionButtonGroup from './ActionButtonGroup';
import { getButtonClasses } from '@/lib/utils';
import LayerReportMessage from './LayerReportMessage';

interface MessageContentProps {
  message: Message;
  onAction?: (action: ActionButton, message: Message) => void;
  enableStreaming?: boolean;
  dimensionContents?: Map<string, string>;  // 实时流式内容（用于 token 级显示）
}

// Progress Message Renderer
function renderProgressMessage(message: ProgressMessage) {
  return (
    <>
      <div className="mb-2">{message.content}</div>
      <div className="w-full rounded-full h-2 overflow-hidden" style={{ background: 'var(--overlay-cream-light)' }}>
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

// Layer Completed Message Renderer
function renderLayerCompletedMessage(message: Message, onAction?: (action: ActionButton, message: Message) => void, enableStreaming = true) {
  if (message.type !== 'layer_completed') return null;

  return (
    <>
      <div className="mb-2 font-bold flex items-center gap-2">
        <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-green-600 text-xs" style={{ color: 'var(--text-cream-primary)' }}>
          <i className="fas fa-check" />
        </span>
        Layer {message.layer} 已完成
      </div>
      <div className="mb-3 leading-relaxed">
        {enableStreaming ? (
          <StreamingText content={message.content} speed={50} />
        ) : (
          message.content
        )}
      </div>
      {message.summary?.key_points && message.summary.key_points.length > 0 && (
        <div className="bg-gradient-to-br from-green-50 to-emerald-50 p-3 rounded-lg mt-2 text-sm border border-green-100">
          <strong className="text-green-700 flex items-center gap-1.5 mb-2">
            <i className="fas fa-lightbulb text-yellow-500" />
            关键点:
          </strong>
          <ul className="mt-2 mb-0 pl-5 space-y-1">
            {message.summary.key_points.map((point, idx) => (
              <li key={idx} className="text-gray-700">{point}</li>
            ))}
          </ul>
        </div>
      )}
      <ActionButtonGroup
        actions={message.actions || []}
        onAction={(a) => onAction?.(a, message)}
        className="mt-3"
      />
    </>
  );
}

// Dimension Report Message Renderer
function renderDimensionReportMessage(message: Message) {
  if (message.type !== 'dimension_report') return null;

  return (
    <div className="bg-blue-50 p-3 rounded-lg border border-blue-200">
      <div className="flex items-center gap-2 mb-2">
        <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-500 text-xs font-bold text-white">
          {message.layer}
        </span>
        <span className="font-medium text-blue-700">{message.dimensionName}</span>
      </div>
      <div className="text-sm text-gray-700 whitespace-pre-wrap">
        {message.content}
      </div>
      {message.progress && (
        <div className="mt-2 text-xs text-gray-500">
          进度: {message.progress.current}/{message.progress.total} 字
        </div>
      )}
    </div>
  );
}

// Main Message Content Renderer
export default function MessageContent(props: MessageContentProps) {
  const { message, onAction, enableStreaming = true, dimensionContents } = props;

  switch (message.type) {
    case 'text':
      return (
        <div className="whitespace-pre-wrap leading-relaxed">
          {enableStreaming && message.role !== 'user' ? (
            <StreamingText
              content={message.content}
              speed={50}
              enabled={message.streamingState !== 'completed'}
            />
          ) : (
            message.content
          )}
        </div>
      );

    case 'progress':
      return isProgressMessage(message) ? renderProgressMessage(message) : null;

    case 'layer_completed':
      return isLayerCompletedMessage(message) ? (
        <LayerReportMessage 
          message={message} 
          dimensionContents={dimensionContents}
        />
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