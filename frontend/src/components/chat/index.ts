/**
 * Chat Components Index
 * 聊天组件统一导出
 */

// Core Components
export { default as MessageList } from './MessageList';
export { default as StreamingText } from './StreamingText';
export { StreamingTextWithControls } from './StreamingText';

// Message Components
export { default as MessageBubble } from './MessageBubble';
export { default as MessageContent } from './MessageContent';
export { default as ActionButtonGroup } from './ActionButtonGroup';

// Visual Feedback
export { default as ThinkingIndicator } from './ThinkingIndicator';
export {
  CompactThinkingIndicator,
  WaveThinkingIndicator,
} from './ThinkingIndicator';

// Rich Content
export { default as CodeBlock, InlineCode } from './CodeBlock';

// Panel
export { default as ChatPanel } from './ChatPanel';

// Types
export type {
  UseStreamingTextOptions,
  UseStreamingTextReturn,
} from '@/hooks/useStreamingText';

export type {
  ThinkingIndicatorProps,
  ThinkingState,
} from './ThinkingIndicator';

export type {
  CodeBlockProps,
} from './CodeBlock';
