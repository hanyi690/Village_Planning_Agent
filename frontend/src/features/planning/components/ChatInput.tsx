'use client';

/**
 * ChatInput - 简化输入框组件
 *
 * 固定底部输入框，约60px高度
 * 无消息列表，仅保留输入框和发送按钮
 * 新增"模拟反馈"快捷按钮（演示专用）
 *
 * Brutalist aesthetic: no rounded corners, 2px borders, orange-red accent
 */

import React, { useState, useCallback } from 'react';
import { faPaperPlane, faCommentDots } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

interface ChatInputProps {
  disabled?: boolean;
  onSend: (message: string) => void;
}

// Demo preset feedback messages
const DEMO_FEEDBACKS = [
  '需要补充交通数据',
  '重新分析资源禀赋',
  '调整发展目标',
];

export default function ChatInput({ disabled, onSend }: ChatInputProps) {
  // State
  const [inputValue, setInputValue] = useState('');
  const [showPresets, setShowPresets] = useState(false);

  // Handlers
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setInputValue(e.target.value);
  }, []);

  const handleSend = useCallback(() => {
    if (inputValue.trim() && !disabled) {
      onSend(inputValue.trim());
      setInputValue('');
    }
  }, [inputValue, disabled, onSend]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);

  const handlePresetClick = useCallback((preset: string) => {
    if (!disabled) {
      onSend(preset);
      setShowPresets(false);
    }
  }, [disabled, onSend]);

  return (
    <div className="h-full flex items-center gap-2 px-4 bg-[#0D0D0D]">
      {/* Main input */}
      <div className="flex-1 flex items-center gap-2">
        <input
          type="text"
          value={inputValue}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={disabled ? '等待规划开始...' : '输入反馈或问题...'}
          className="flex-1 h-[40px] px-3 bg-[#1A1A1A] border-2 border-[#333] text-[#E5E5E5] placeholder-[#666] focus:border-[#00FFB3] focus:outline-none transition-colors disabled:opacity-50"
        />

        {/* Send button */}
        <button
          onClick={handleSend}
          disabled={disabled || !inputValue.trim()}
          className="h-[40px] px-4 bg-[#FF3D00] border-2 border-[#FF3D00] text-white hover:bg-[#FF3D00]/80 hover:border-[#FF3D00]/80 disabled:opacity-50 disabled:bg-[#333] disabled:border-[#333] disabled:text-[#666] transition-colors"
        >
          <FontAwesomeIcon icon={faPaperPlane} style={{ width: 14, height: 14 }} />
        </button>
      </div>

      {/* Demo preset button */}
      <div className="relative">
        <button
          onClick={() => setShowPresets((prev) => !prev)}
          disabled={disabled}
          className="h-[40px] px-3 bg-[#1A1A1A] border-2 border-[#333] text-[#888] hover:text-[#00FFB3] hover:border-[#00FFB3] disabled:opacity-50 transition-colors"
          title="模拟反馈（演示专用）"
        >
          <FontAwesomeIcon icon={faCommentDots} style={{ width: 14, height: 14 }} />
        </button>

        {/* Preset dropdown */}
        {showPresets && !disabled && (
          <div className="absolute right-0 bottom-[45px] w-[180px] bg-[#1A1A1A] border-2 border-[#333] shadow-lg">
            <div className="px-2 py-1 text-xs text-[#666] border-b border-[#333]">
              模拟反馈（演示）
            </div>
            {DEMO_FEEDBACKS.map((preset, idx) => (
              <button
                key={idx}
                onClick={() => handlePresetClick(preset)}
                className="w-full px-3 py-2 text-sm text-[#888] hover:text-[#00FFB3] hover:bg-[#0D0D0D] transition-colors text-left"
              >
                {preset}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}