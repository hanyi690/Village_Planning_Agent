// ============================================
// useFileUpload Hook - 文件上传逻辑
// ============================================

import { useState, useCallback } from 'react';
import { fileApi } from '@/lib/api';
import { createBaseMessage, createSystemMessage, createErrorMessage } from '@/lib/utils';
import type { FileMessage, Message } from '@/types';

interface UseFileUploadOptions {
  addMessage: (message: Message) => void;
  setUploadedFileContent: (content: string | null) => void;
}

interface UseFileUploadReturn {
  isUploadingFile: boolean;
  handleFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => Promise<void>;
}

/**
 * 文件上传 Hook
 * 处理文件选择、上传和内容提取
 */
export function useFileUpload({
  addMessage,
  setUploadedFileContent,
}: UseFileUploadOptions): UseFileUploadReturn {
  const [isUploadingFile, setIsUploadingFile] = useState(false);

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    try {
      setIsUploadingFile(true);

      // 支持多文件上传
      const uploadPromises = Array.from(files).map(async (file) => {
        const response = await fileApi.uploadFile(file);
        return { file, response };
      });

      const results = await Promise.all(uploadPromises);

      // 合并所有文件内容
      const allContents: string[] = [];

      for (const { file, response } of results) {
        allContents.push(response.content);

        addMessage({
          ...createBaseMessage('user'),
          type: 'file',
          filename: file.name,
          fileContent: response.content,
          fileSize: file.size,
          encoding: response.encoding,
        } as FileMessage);

        const encodingInfo = response.encoding ? `\n编码: ${response.encoding}` : '';
        addMessage(createSystemMessage(
          `✅ 文件 "${file.name}" 已上传${encodingInfo}\n内容长度: ${response.content.length} 字符`
        ));
      }

      // 存储合并后的内容
      const combinedContent = allContents.join('\n\n---\n\n');
      setUploadedFileContent(combinedContent);

      if (results.length > 1) {
        addMessage(createSystemMessage(
          `✅ 已上传 ${results.length} 个文件，总内容长度: ${combinedContent.length} 字符\n点击 "开始规划" 按钮启动任务`
        ));
      } else {
        addMessage(createSystemMessage(
          `点击 "开始规划" 按钮启动任务`
        ));
      }

      e.target.value = '';
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '未知错误';
      addMessage(createErrorMessage(`❌ 文件上传失败: ${errorMessage}`));
    } finally {
      setIsUploadingFile(false);
    }
  }, [addMessage, setUploadedFileContent]);

  return {
    isUploadingFile,
    handleFileSelect,
  };
}