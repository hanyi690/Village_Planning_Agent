'use client';

import { useMemo } from 'react';
import {
  Message,
  LayerCompletedMessage,
  FileMessage,
  Checkpoint,
  GisResultMessage,
  ToolStatusMessage,
} from '../../types';
import { isGisResultMessage, isToolStatusMessage } from '@/types/message/message-guards';
import ThinkingIndicator from './ThinkingIndicator';
import MessageBubble from './MessageBubble';
import LayerReportMessage from './LayerReportMessage';
import CheckpointMarker from './CheckpointMarker';
import ToolStatusCard from './ToolStatusCard';
import GisResultCard from './GisResultCard';

interface MessageListProps {
  messages: Message[];
  isTyping?: boolean;
  thinkingState?: 'analyzing' | 'generating' | 'reviewing' | 'processing' | 'waiting';
  thinkingMessage?: string;
  checkpoints?: Checkpoint[];
  onRollback?: (checkpointId: string) => Promise<void>;
  isRollingBack?: boolean;
}

export default function MessageList({
  messages,
  isTyping,
  thinkingState,
  thinkingMessage,
  checkpoints = [],
  onRollback,
  isRollingBack = false,
}: MessageListProps) {
  const keyCheckpointByLayer = useMemo(() => {
    const map = new Map<number, Checkpoint>();
    for (const cp of checkpoints) {
      if (cp.type === 'key') {
        const existing = map.get(cp.layer);
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

  return (
    <div className="p-3 space-y-3">
      {messages.length === 0 && (
        <div className="text-center text-slate-500 py-8">
          <p className="text-sm">开始规划后，消息将显示在这里</p>
        </div>
      )}

      {messages.map((message) => {
        if (message.type === 'layer_completed') {
          const layerMsg = message as LayerCompletedMessage;
          const layerCheckpoint = keyCheckpointByLayer.get(layerMsg.layer);

          return (
            <div key={message.id}>
              <LayerReportMessage message={layerMsg} />
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

        if (message.type === 'file') {
          const fileMsg = message as FileMessage;

          return (
            <div key={message.id} className="flex justify-end">
              <div className="px-3 py-2 bg-sky-50 border border-sky-200 rounded-lg text-sm text-sky-700">
                <span className="font-medium">{fileMsg.filename}</span>
                <span className="text-sky-400 mx-1">·</span>
                <span>{fileMsg.fileSize ? `${(fileMsg.fileSize / 1024).toFixed(1)}KB` : ''}</span>
              </div>
            </div>
          );
        }

        if (isGisResultMessage(message)) {
          return (
            <GisResultCard
              key={message.id}
              message={message as GisResultMessage}
            />
          );
        }

        if (isToolStatusMessage(message)) {
          return (
            <ToolStatusCard
              key={message.id}
              message={message as ToolStatusMessage}
            />
          );
        }

        return (
          <MessageBubble
            key={message.id}
            message={message}
            onCopy={handleCopy}
            onRegenerate={handleRegenerate}
          />
        );
      })}

      {thinkingState && thinkingMessage && (
        <div className="flex justify-start">
          <div className="px-4 py-2 bg-white border border-slate-200 rounded-lg">
            <ThinkingIndicator state={thinkingState} message={thinkingMessage} size="md" />
          </div>
        </div>
      )}

      {isTyping && !thinkingState && (
        <div className="flex justify-start">
          <div className="px-4 py-2 bg-white border border-slate-200 rounded-lg text-sm text-slate-500">
            正在思考...
          </div>
        </div>
      )}
    </div>
  );
}