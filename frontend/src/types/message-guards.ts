/**
 * Message Type Guards
 * 消息类型守卫函数
 *
 * Type guard functions for narrowing Message types at runtime.
 * Use these to safely check message types before accessing type-specific properties.
 */

import type {
  Message,
} from './message';
import type {
  TextMessage,
  FileMessage,
  ActionMessage,
  ProgressMessage,
  ResultMessage,
  ErrorMessage,
  SystemMessage,
  LayerCompletedMessage,
  ReviewRequestMessage,
  CheckpointListMessage,
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
 * Check if message is a system message
 */
export const isSystemMessage = (msg: Message): msg is SystemMessage => msg.type === 'system';

/**
 * Check if message is an action message
 */
export const isActionMessage = (msg: Message): msg is ActionMessage => msg.type === 'action';

/**
 * Check if message is a progress message
 */
export const isProgressMessage = (msg: Message): msg is ProgressMessage => msg.type === 'progress';

/**
 * Check if message is a result message
 */
export const isResultMessage = (msg: Message): msg is ResultMessage => msg.type === 'result';

/**
 * Check if message is an error message
 */
export const isErrorMessage = (msg: Message): msg is ErrorMessage => msg.type === 'error';

/**
 * Check if message is a layer completed message
 */
export const isLayerCompletedMessage = (msg: Message): msg is LayerCompletedMessage => msg.type === 'layer_completed';

/**
 * Check if message is a review request message
 */
export const isReviewRequestMessage = (msg: Message): msg is ReviewRequestMessage => msg.type === 'review_request';

/**

 * Check if message is a checkpoint list message

 */

export const isCheckpointListMessage = (msg: Message): msg is CheckpointListMessage => msg.type === 'checkpoint_list';
