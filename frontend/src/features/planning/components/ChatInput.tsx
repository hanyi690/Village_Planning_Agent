'use client';

/**
 * ChatInput - 简化输入框组件
 *
 * 固定底部输入框，约60px高度
 * 无消息列表，仅保留输入框和发送按钮
 * 新增"模拟反馈"快捷按钮（演示专用）
 * 新增文件上传按钮
 *
 * Gemini aesthetic: rounded corners, glass effect, emerald gradient buttons
 */

import React, { useState, useCallback } from 'react';
import { faPaperPlane, faCommentDots, faPaperclip } from '@fortawesome/free-solid-svg-icons';
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

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      // For now, just notify the user about the uploaded file
      // Backend API call would be: await planningApi.uploadFile(files[0]);
      onSend(`[已上传文件: ${files[0].name}]`);
    }
    // Reset input
    e.target.value = '';
  }, [onSend]);

  return (
    <div className="h-full flex items-center gap-2 px-4">
      {/* Hidden file input */}
      <input
        type="file"
        multiple
        accept=".geojson,.json,.shp,.kml,.kmz,.tif,.tiff,.pdf,.txt,.md,.doc,.docx"
        onChange={handleFileSelect}
        className="hidden"
        id="file-upload"
        disabled={disabled}
      />

      {/* Main input */}
      <div className="flex-1 flex items-center gap-2">
        {/* File upload button */}
        <label
          htmlFor="file-upload"
          className={`w-10 h-10 flex items-center justify-center rounded-full cursor-pointer ${
            disabled
              ? 'opacity-50 cursor-not-allowed'
              : 'hover:bg-slate-100'
          } transition-colors`}
        >
          <FontAwesomeIcon
            icon={faPaperclip}
            className={`text-slate-400 ${disabled ? '' : 'hover:text-slate-600'}`}
            style={{ width: 14, height: 14 }}
          />
        </label>

        <input
          type="text"
          value={inputValue}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={disabled ? '等待规划开始...' : '输入反馈或问题...'}
          className="flex-1 h-[40px] px-3 bg-slate-50 border border-slate-300 rounded-xl text-slate-700 placeholder-slate-400 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 focus:outline-none transition-colors disabled:opacity-50"
        />

        {/* Send button */}
        <button
          onClick={handleSend}
          disabled={disabled || !inputValue.trim()}
          className="h-[40px] px-4 bg-gradient-to-r from-emerald-500 to-teal-500 rounded-xl text-white hover:from-emerald-600 hover:to-teal-600 disabled:opacity-50 disabled:from-slate-300 disabled:to-slate-400 transition-all"
        >
          <FontAwesomeIcon icon={faPaperPlane} style={{ width: 14, height: 14 }} />
        </button>
      </div>

      {/* Demo preset button */}
      <div className="relative">
        <button
          onClick={() => setShowPresets((prev) => !prev)}
          disabled={disabled}
          className="h-[40px] px-3 rounded-xl bg-white border border-slate-200 text-slate-500 hover:text-emerald-500 hover:border-emerald-200 disabled:opacity-50 transition-colors shadow-sm"
          title="模拟反馈（演示专用）"
        >
          <FontAwesomeIcon icon={faCommentDots} style={{ width: 14, height: 14 }} />
        </button>

        {/* Preset dropdown */}
        {showPresets && !disabled && (
          <div className="absolute right-0 bottom-[45px] w-[180px] bg-white rounded-lg border border-slate-200 shadow-lg">
            <div className="px-2 py-1 text-xs text-slate-400 border-b border-slate-200 rounded-t-lg">
              模拟反馈（演示）
            </div>
            {DEMO_FEEDBACKS.map((preset, idx) => (
              <button
                key={idx}
                onClick={() => handlePresetClick(preset)}
                className="w-full px-3 py-2 text-sm text-slate-600 hover:text-emerald-600 hover:bg-emerald-50 transition-colors text-left last:rounded-b-lg"
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