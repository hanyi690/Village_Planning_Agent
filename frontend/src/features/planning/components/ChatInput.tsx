'use client';

import React, { useCallback, useRef, useState } from 'react';
import { faArrowUp } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

interface ChatInputProps {
  disabled?: boolean;
  onSend: (message: string) => void | Promise<void>;
}

const TEXTAREA_MAX_HEIGHT = 144;

/**
 * Compact ChatGPT-style composer.
 *
 * Workflow shortcuts and the previous fake upload action intentionally live
 * outside the composer. This control has one job: send a clear chat turn.
 */
export default function ChatInput({ disabled = false, onSend }: ChatInputProps) {
  const [inputValue, setInputValue] = useState('');
  const [isSending, setIsSending] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const resizeTextarea = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, TEXTAREA_MAX_HEIGHT)}px`;
    textarea.style.overflowY =
      textarea.scrollHeight > TEXTAREA_MAX_HEIGHT ? 'auto' : 'hidden';
  }, []);

  const handleInputChange = useCallback(
    (event: React.ChangeEvent<HTMLTextAreaElement>) => {
      setInputValue(event.target.value);
      window.requestAnimationFrame(resizeTextarea);
    },
    [resizeTextarea],
  );

  const handleSend = useCallback(async () => {
    const message = inputValue.trim();
    if (!message || disabled || isSending) return;

    setInputValue('');
    setIsSending(true);
    window.requestAnimationFrame(resizeTextarea);

    try {
      await onSend(message);
    } catch {
      // Preserve a message when the caller rejects before it can add a visible
      // error turn. The normal planning handler catches and renders its errors.
      setInputValue(message);
      window.requestAnimationFrame(resizeTextarea);
    } finally {
      setIsSending(false);
      textareaRef.current?.focus();
    }
  }, [disabled, inputValue, isSending, onSend, resizeTextarea]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (
        event.key === 'Enter' &&
        !event.shiftKey &&
        !event.nativeEvent.isComposing
      ) {
        event.preventDefault();
        void handleSend();
      }
    },
    [handleSend],
  );

  const cannotSend = disabled || isSending || inputValue.trim().length === 0;

  return (
    <div className="bg-white px-3 pb-4 pt-2 safe-area-bottom">
      <div
        className={`flex items-end gap-2 rounded-2xl border bg-slate-50 px-3 py-2 shadow-sm transition-colors ${
          disabled
            ? 'border-slate-200 opacity-70'
            : 'border-slate-200 focus-within:border-sky-400 focus-within:bg-white focus-within:ring-2 focus-within:ring-sky-100'
        }`}
      >
        <textarea
          ref={textareaRef}
          rows={1}
          value={inputValue}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          disabled={disabled || isSending}
          aria-label="发送消息"
          placeholder={disabled ? '开始规划后即可对话' : '询问规划内容或提出修改意见'}
          className="min-h-[36px] max-h-36 flex-1 resize-none overflow-hidden bg-transparent px-1 py-2 text-sm leading-5 text-slate-800 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed"
        />

        <button
          type="button"
          onClick={() => void handleSend()}
          disabled={cannotSend}
          aria-label={isSending ? '正在发送' : '发送消息'}
          title="发送消息"
          className="mb-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white transition-colors hover:bg-sky-600 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {isSending ? (
            <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />
          ) : (
            <FontAwesomeIcon icon={faArrowUp} style={{ width: 13, height: 13 }} />
          )}
        </button>
      </div>

      <p className="mt-1.5 text-center text-[10px] text-slate-400">
        Enter 发送 · Shift + Enter 换行
      </p>
    </div>
  );
}
