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
import FileViewerSidebar from './FileViewerSidebar';
import { usePlanningStore } from '@/features/planning/store';

interface MessageListProps {
  messages: Message[];
  onFileClick?: (file: FileMessage) => void;
  isTyping?: boolean;
  thinkingState?: 'analyzing' | 'generating' | 'reviewing' | 'processing' | 'waiting';
  thinkingMessage?: string;
  checkpoints?: Checkpoint[];
  onRollback?: (checkpointId: string) => Promise<void>;
  isRollingBack?: boolean;
}

export default function MessageList({
  messages,
  onFileClick,
  isTyping,
  thinkingState,
  thinkingMessage,
  checkpoints = [],
  onRollback,
  isRollingBack = false,
}: MessageListProps) {
  const viewingFile = usePlanningStore((state) => state.viewingFile);
  const openFile = onFileClick ?? ((file: FileMessage) => usePlanningStore.getState().setViewingFile(file));
  const closeFile = () => usePlanningStore.getState().setViewingFile(null);
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

  return (
    <div className="min-h-full p-4">
      {messages.length === 0 && (
        <div className="flex min-h-[320px] flex-col items-center justify-center px-6 text-center">
          <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-sky-500 to-cyan-500 text-xs font-semibold text-white shadow-sm">
            AI
          </div>
          <p className="text-sm font-medium text-slate-700">有什么可以帮你？</p>
          <p className="mt-1.5 max-w-[260px] text-xs leading-5 text-slate-400">
            可以询问当前规划结论、数据依据，或提出具体修改意见。
          </p>
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
              <button
                type="button"
                onClick={() => openFile(fileMsg)}
                className="px-3 py-2 bg-sky-50 border border-sky-200 rounded-lg text-left text-sm text-sky-700 transition hover:bg-sky-100 disabled:cursor-default"
                title={onFileClick ? '点击查看文件' : undefined}
              >
                <span className="font-medium">{fileMsg.filename}</span>
                <span className="text-sky-400 mx-1">·</span>
                <span>{fileMsg.fileSize ? `${(fileMsg.fileSize / 1024).toFixed(1)}KB` : ''}</span>
              </button>
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
      {viewingFile && <FileViewerSidebar file={viewingFile} onClose={closeFile} />}
    </div>
  );
}
