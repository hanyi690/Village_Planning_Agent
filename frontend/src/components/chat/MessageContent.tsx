'use client';

/**
 * MessageContent Components
 * Individual message type renderers
 */

import { Message, ActionButton, ProgressMessage, ActionMessage, ResultMessage, ErrorMessage } from '@/types';
import {
  isProgressMessage,
  isActionMessage,
  isResultMessage,
  isErrorMessage,
} from '@/types';
import StreamingText from './StreamingText';
import ActionButtonGroup from './ActionButtonGroup';
import { getButtonClasses } from '@/lib/utils';

interface MessageContentProps {
  message: Message;
  onAction?: (action: ActionButton, message: Message) => void;
  enableStreaming?: boolean;
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

// Action Message Renderer
function renderActionMessage(message: ActionMessage, onAction?: (action: ActionButton, message: Message) => void) {
  return (
    <>
      <div className="mb-3 leading-relaxed">{message.content}</div>
      <ActionButtonGroup actions={message.actions} onAction={(a) => onAction?.(a, message)} />
    </>
  );
}

// Result Message Renderer
function renderResultMessage(message: ResultMessage) {
  return (
    <>
      <div className="mb-3 leading-relaxed">{message.content}</div>
      <div className="text-sm mb-3 flex items-center gap-2 text-gray-600">
        <i className="fas fa-map-marker-alt text-green-600" />
        <span>村庄: {message.villageName}</span>
      </div>
      <button
        className={getButtonClasses('primary', 'md', 'lg')}
        onClick={() => message.resultUrl && (window.location.href = message.resultUrl)}
        style={{ color: 'var(--text-cream-primary)' }}
      >
        <i className="fas fa-eye mr-2" />
        查看结果
      </button>
    </>
  );
}

// Error Message Renderer
function renderErrorMessage(message: ErrorMessage, isUser: boolean) {
  return (
    <div className={`flex items-center gap-2 ${!isUser ? 'text-red-600' : ''}`} style={isUser ? { color: 'var(--text-cream-primary)' } : {}}>
      <i className="fas fa-exclamation-circle" />
      <span>{message.content}</span>
    </div>
  );
}

// System Message Renderer
// System Message Renderer
function renderSystemMessage(message: Message) {
  if (message.type !== 'system') return null;

  return (
    <div className="text-sm bg-white/60 backdrop-blur-sm p-3 rounded-lg border border-gray-200/50">
      {message.content}
    </div>
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

// Checkpoint List Message Renderer
function renderCheckpointListMessage(message: Message, onAction?: (action: ActionButton, message: Message) => void) {
  if (message.type !== 'checkpoint_list') return null;

  return (
    <>
      <div className="mb-3 flex items-center gap-2 font-semibold text-gray-700">
        <i className="fas fa-history text-blue-500" />
        <span>{message.content}</span>
      </div>
      {message.checkpoints && message.checkpoints.length > 0 && (
        <div className="mt-2 space-y-2">
          {message.checkpoints.map((cp) => (
            <div
              key={cp.checkpoint_id}
              className="bg-gradient-to-r from-blue-50 to-indigo-50 px-3 py-2.5 rounded-lg text-sm border border-blue-100 hover:shadow-sm transition-all duration-200"
            >
              <div className="flex justify-between items-center">
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-500 text-xs font-bold" style={{ color: 'var(--text-cream-primary)' }}>
                    {cp.layer}
                  </span>
                  <span className="font-medium text-gray-700">{cp.description}</span>
                </div>
                <small className="text-xs text-gray-500">{cp.timestamp}</small>
              </div>
            </div>
          ))}
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

// Main Message Content Renderer
export default function MessageContent(props: MessageContentProps) {
  const { message, onAction, enableStreaming = true } = props;

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

    case 'action':
      return isActionMessage(message) ? renderActionMessage(message, onAction) : null;

    case 'result':
      return isResultMessage(message) ? renderResultMessage(message) : null;

    case 'error':
      return isErrorMessage(message) ? renderErrorMessage(message, message.role === 'user') : null;

    case 'system':
      return renderSystemMessage(message);

    case 'layer_completed':
      return renderLayerCompletedMessage(message, onAction, enableStreaming);

    case 'checkpoint_list':
      return renderCheckpointListMessage(message, onAction);

    default:
      return null;
  }
}
