'use client';

// ============================================
// ChatInputArea - 底部输入区域组件
// ============================================

import { motion } from 'framer-motion';
import { FILE_ACCEPT } from '@/lib/constants';

interface ChatInputAreaProps {
  inputText: string;
  setInputText: (text: string) => void;
  inputDisabled: boolean;
  isTyping: boolean;
  isUploadingFile: boolean;
  hasPendingReview: boolean;
  pendingReviewLayer: number | null;
  status: string;
  stepMode: boolean;
  setStepMode: (mode: boolean) => void;
  progressPanelVisible: boolean;
  setProgressPanelVisible: (visible: boolean) => void;
  onFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onSendMessage: () => void;
}

/**
 * ChatInputArea - 底部浮动输入区域
 * 包含文件上传、步进模式切换、进度面板切换、文本输入和发送按钮
 */
export default function ChatInputArea({
  inputText,
  setInputText,
  inputDisabled,
  isTyping,
  isUploadingFile,
  hasPendingReview,
  pendingReviewLayer,
  status,
  stepMode,
  setStepMode,
  progressPanelVisible,
  setProgressPanelVisible,
  onFileSelect,
  onSendMessage,
}: ChatInputAreaProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={`relative flex items-end gap-2 p-2 bg-white rounded-3xl shadow-lg border transition-all duration-300 ${
        hasPendingReview
          ? 'border-amber-200 shadow-amber-100/50'
          : 'border-gray-100 hover:border-gray-200'
      }`}
    >
      {/* Hidden file input */}
      <input
        type="file"
        multiple
        accept={FILE_ACCEPT}
        onChange={onFileSelect}
        disabled={inputDisabled || isTyping || isUploadingFile}
        className="hidden"
        id="file-upload"
      />

      {/* File upload button */}
      <motion.label
        htmlFor="file-upload"
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        className={`flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-full cursor-pointer transition-colors ${
          inputDisabled || isTyping || isUploadingFile
            ? 'text-gray-300 cursor-not-allowed'
            : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'
        }`}
      >
        <i className={`fas ${isUploadingFile ? 'fa-spinner fa-spin' : 'fa-paperclip'}`} />
      </motion.label>

      {/* Step Mode Toggle */}
      <div className="flex items-center p-0.5 bg-gray-100 rounded-full flex-shrink-0">
        <motion.button
          type="button"
          onClick={() => setStepMode(false)}
          whileHover={!stepMode ? {} : { scale: 1.02 }}
          whileTap={!stepMode ? {} : { scale: 0.98 }}
          className={`px-2.5 py-1 text-xs font-medium rounded-full transition-all duration-200 ${
            !stepMode ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          连续
        </motion.button>
        <motion.button
          type="button"
          onClick={() => setStepMode(true)}
          whileHover={stepMode ? {} : { scale: 1.02 }}
          whileTap={stepMode ? {} : { scale: 0.98 }}
          className={`px-2.5 py-1 text-xs font-medium rounded-full transition-all duration-200 ${
            stepMode ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          分步
        </motion.button>
      </div>

      {/* Progress Panel Toggle */}
      <motion.button
        type="button"
        onClick={() => setProgressPanelVisible(!progressPanelVisible)}
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
        className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full transition-all duration-200 flex-shrink-0 ${
          progressPanelVisible
            ? 'bg-blue-100 text-blue-700 ring-1 ring-blue-300'
            : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
        }`}
        title={progressPanelVisible ? '隐藏进度面板' : '显示进度面板'}
      >
        <span>📊</span>
        <span>{progressPanelVisible ? '隐藏进度' : '进度'}</span>
      </motion.button>

      {/* Text input */}
      <textarea
        value={inputText}
        onChange={(e) => setInputText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (inputText.trim() && !isTyping) onSendMessage();
          }
        }}
        disabled={inputDisabled || isTyping}
        placeholder={
          hasPendingReview && pendingReviewLayer
            ? '请输入修改意见，或输入"批准"继续...'
            : status === 'planning' || status === 'collecting'
              ? '规划进行中...'
              : '输入消息...'
        }
        rows={1}
        className="flex-1 min-h-[40px] max-h-32 px-2 py-2 text-gray-900 placeholder-gray-400 bg-transparent border-0 resize-none focus:outline-none focus:ring-0 text-sm leading-relaxed"
        style={{
          height: 'auto',
          overflow: inputText.split('\n').length > 2 ? 'auto' : 'hidden',
        }}
      />

      {/* Send button */}
      <motion.button
        onClick={onSendMessage}
        disabled={inputDisabled || isTyping || !inputText.trim() || isUploadingFile}
        whileHover={inputText.trim() ? { scale: 1.05 } : {}}
        whileTap={inputText.trim() ? { scale: 0.95 } : {}}
        className={`flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-full transition-all duration-300 ${
          inputText.trim() && !inputDisabled
            ? 'text-white shadow-lg'
            : 'text-gray-300 bg-gray-100 cursor-not-allowed'
        }`}
        style={
          inputText.trim() && !inputDisabled
            ? {
                background: 'linear-gradient(135deg, #10b981 0%, #14b8a6 50%, #0891b2 100%)',
                boxShadow: '0 4px 15px rgba(16, 185, 129, 0.4)',
              }
            : {}
        }
      >
        {isUploadingFile ? (
          <i className="fas fa-spinner fa-spin text-sm" />
        ) : isTyping ? (
          <i className="fas fa-spinner fa-spin text-sm" />
        ) : (
          <i className="fas fa-arrow-up text-sm" />
        )}
      </motion.button>
    </motion.div>
  );
}
