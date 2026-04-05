/**
 * Message Type Guards
 * 消息类型守卫函数
 *
 * Type guard functions for narrowing Message types at runtime.
 * Use these to safely check message types before accessing type-specific properties.
 */

import type { Message } from './index';
import type {
  TextMessage,
  FileMessage,
  ProgressMessage,
  LayerCompletedMessage,
  DimensionReportMessage,
} from './message-types';

/**
 * Check if message is from user
 */
export const isUserMessage = (msg: Message): boolean => msg.role === 'user';

/**
 * Check if message is a text message
 */
export const isTextMessage = (msg: Message): msg is TextMessage => msg.type === 'text';

/**
 * Check if message is a file message
 */
export const isFileMessage = (msg: Message): msg is FileMessage => msg.type === 'file';

/**
 * Check if message is a progress message
 */
export const isProgressMessage = (msg: Message): msg is ProgressMessage => msg.type === 'progress';

/**
 * Check if message is a layer completed message
 */
export const isLayerCompletedMessage = (msg: Message): msg is LayerCompletedMessage =>
  msg.type === 'layer_completed';

/**
 * Check if message is a dimension report message
 */
export const isDimensionReportMessage = (msg: Message): msg is DimensionReportMessage =>
  msg.type === 'dimension_report';
