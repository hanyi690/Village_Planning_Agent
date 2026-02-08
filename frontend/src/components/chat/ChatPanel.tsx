'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useUnifiedPlanningContext } from '@/contexts/UnifiedPlanningContext';
import { Message, ActionButton, FileMessage, ReviewInteractionMessage, isReviewInteractionMessage } from '@/types/message';
import { isProgressMessage } from '@/types/message';
import { planningApi, fileApi } from '@/lib/api';
import SegmentedControl from '@/components/ui/SegmentedControl';
import { useTaskSSE } from '@/hooks/useTaskSSE';
import MessageList from './MessageList';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faEdit, faLayerGroup } from '@fortawesome/free-solid-svg-icons';

interface ChatPanelProps {
  className?: string;
}

// Constants
const DISABLE_INPUT_STATUSES = new Set(['planning', 'paused', 'revising'] as const);
const MIN_FILE_CONTENT_LENGTH = 50;
const FILE_ACCEPT = '.docx,.pdf,.txt,.md';
const LAYER_OPTIONS = ['现状分析', '规划思路', '详细规划'];
const LAYER_LABEL_MAP: Record<string, number> = {
  '现状分析': 1,
  '规划思路': 2,
  '详细规划': 3,
};
const LAYER_VALUE_MAP: Record<number, string> = {
  1: '现状分析',
  2: '规划思路',
  3: '详细规划',
};

// Helper functions
function generateMessageId(): string {
  return `msg-${Date.now()}`;
}

function createMessage<T extends Message>(partial: Partial<T>): T {
  return {
    id: generateMessageId(),
    timestamp: new Date(),
    ...partial,
  } as T;
}

type PlanningStatus = 'idle' | 'collecting' | 'planning' | 'paused' | 'reviewing' | 'revising' | 'completed' | 'failed';

function isInputDisabled(status: PlanningStatus): boolean {
  return DISABLE_INPUT_STATUSES.has(status as any);
}

function getLayerId(layer: number): 'layer_1_analysis' | 'layer_2_concept' | 'layer_3_detailed' | null {
  const layerMap: Record<number, 'layer_1_analysis' | 'layer_2_concept' | 'layer_3_detailed'> = {
    1: 'layer_1_analysis',
    2: 'layer_2_concept',
    3: 'layer_3_detailed',
  };
  return layerMap[layer] || null;
}

/**
 * ChatPanel - Unified chat interface integrating messaging and progress display
 */
export default function ChatPanel({ className = '' }: ChatPanelProps) {
  const {
    messages,
    addMessage,
    updateLastMessage,
    status,
    taskId,
    setStatus,
    villageFormData,
    showReviewPanel,
    setShowReviewPanel,
    checkpoints,
    setCheckpoints,
    currentLayer,
    setCurrentLayer,
    startPlanning,
    loadLayerContent,
    showViewer,
    pendingReviewMessage,
    setPendingReviewMessage,
  } = useUnifiedPlanningContext();

  const [inputText, setInputText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [isUploadingFile, setIsUploadingFile] = useState(false);
  const [isPlanning, setIsPlanning] = useState(false);
  const [uploadedFileContent, setUploadedFileContent] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // SSE event handling - MOVED HERE before callbacks that use reconnectSSE
  const { isConnected, error: sseError, reconnect: reconnectSSE } = useTaskSSE(taskId, {
    onStatusUpdate: (data) => {
      const lastProgressMsg = messages.findLast(m => m.type === 'progress');

      if (lastProgressMsg) {
        updateLastMessage({
          content: data.message || '正在执行...',
          progress: data.progress || 0,
          currentLayer: data.current_layer,
        });
      } else {
        addMessage({
          id: `msg-${Date.now()}`,
          timestamp: new Date(),
          role: 'assistant',
          type: 'progress',
          content: data.message || '正在执行...',
          progress: data.progress || 0,
          currentLayer: data.current_layer,
          taskId: taskId || undefined,
        });
      }
    },

    onLayerCompleted: async (data) => {
      const layer = data.layer_number;
      const reportContent = data.report_content;
      const dimensionReports = data.dimension_reports;

      console.log('[ChatPanel] Layer completed:', { layer, hasReportContent: !!reportContent, hasDimensionReports: !!dimensionReports });

      // Import parser
      const { parseLayerReport, getReportStats } = await import('@/lib/layerReportParser');

      // Parse dimensions from report
      const dimensions = reportContent ? parseLayerReport(reportContent) : [];
      const stats = reportContent ? getReportStats(reportContent) : null;

      // Map layer number to layer ID
      const layerIdMap: Record<number, 'layer_1_analysis' | 'layer_2_concept' | 'layer_3_detailed'> = {
        1: 'layer_1_analysis',
        2: 'layer_2_concept',
        3: 'layer_3_detailed',
      };

      const layerId = layerIdMap[layer];

      if (!layerId) {
        console.error('[ChatPanel] Invalid layer number:', layer);
        return;
      }

      // Add completion message with parsed dimension info
      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
        role: 'assistant',
        type: 'layer_completed',
        layer,
        content: `✅ Layer ${layer} 已完成`,
        summary: {
          word_count: stats?.wordCount || reportContent?.length || 0,
          key_points: [],
          dimension_count: stats?.dimensionCount || dimensions.length,
          dimension_names: stats?.dimensionNames || dimensions.map(d => d.name),
        },
        fullReportContent: reportContent,
        dimensionReports: dimensionReports,
        actions: [
          { id: 'open_review', label: '查看详情', action: 'view', variant: 'primary' },
          { id: 'approve_quick', label: '快速批准', action: 'approve', variant: 'success' }
        ],
      });

      setCurrentLayer(layer);
      setStatus('paused');

      // Directly use SSE data for immediate display
      if (reportContent || dimensionReports) {
        console.log('[ChatPanel] Using SSE data for immediate display, layer:', layerId);

        // Check if content was truncated
        const isTruncated = reportContent?.includes('[报告内容过长，已截断');

        console.log('[ChatPanel] Content displayed immediately from SSE', isTruncated ? '(truncated)' : '');
        console.log('[ChatPanel] Parsed dimensions:', dimensions.length, 'dimensions found');

        // Show warning if content was truncated
        if (isTruncated) {
          addMessage({
            id: `msg-${Date.now()}`,
            timestamp: new Date(),
            role: 'system',
            type: 'system',
            level: 'warning',
            content: `⚠️ 报告内容较大，SSE传输已截断。完整内容请点击"查看详情"后刷新。`,
          });
        }
      } else {
        // Fallback: Load from API if SSE data is missing
        console.warn('[ChatPanel] SSE event missing report content, falling back to API');
        try {
          await loadLayerContent(layerId);
        } catch (error) {
          console.error('[ChatPanel] Failed to load layer content:', error);
          addMessage({
            id: `msg-${Date.now()}`,
            timestamp: new Date(),
            role: 'system',
            type: 'error',
            content: `⚠️ 加载 Layer ${layer} 内容失败，请手动刷新`,
          });
        }
      }

      // Add review interaction message instead of opening panel
      setTimeout(() => {
        addMessage({
          id: `msg-${Date.now()}`,
          timestamp: new Date(),
          role: 'assistant',
          type: 'review_interaction',
          layer,
          content: `✅ Layer ${layer} 已完成，请审查后决定下一步操作`,
          reviewState: 'pending',
          availableActions: ['approve', 'reject', 'rollback'],
          enableDimensionSelection: true,
          enableRollback: true,
          feedbackPlaceholder: '请描述需要修改的内容（选填）',
          quickFeedbackOptions: [
            '内容结构需要优化，请重新组织',
            '部分内容不够详细，需要补充',
            '存在错误或不准确的信息',
          ],
        } as ReviewInteractionMessage);

        // Load checkpoints for rollback functionality
        loadCheckpoints();
      }, 500);
    },

    onPause: (data) => {
      console.log('[ChatPanel] Task paused:', data);
      setStatus('paused');
      // Add review interaction message when paused
      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
        role: 'assistant',
        type: 'review_interaction',
        layer: currentLayer || 1,
        content: '规划已暂停，请审查后决定下一步操作',
        reviewState: 'pending',
        availableActions: ['approve', 'reject', 'rollback'],
        enableDimensionSelection: true,
        enableRollback: true,
        feedbackPlaceholder: '请描述需要修改的内容（选填）',
        quickFeedbackOptions: [
          '内容结构需要优化，请重新组织',
          '部分内容不够详细，需要补充',
          '存在错误或不准确的信息',
        ],
      } as ReviewInteractionMessage);
      loadCheckpoints();
    },

    onComplete: (data) => {
      console.log('[ChatPanel] Task completed:', data);
      setStatus('completed');

      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
        role: 'assistant',
        type: 'result',
        content: `🎉 规划任务已完成！\n\n村庄：${villageFormData?.projectName || '村庄'}`,
        villageName: villageFormData?.projectName || '村庄',
        sessionId: taskId || '',
        layers: ['Layer 1', 'Layer 2', 'Layer 3'],
        resultUrl: `/village/${taskId}`,
      });
    },

    onError: (error) => {
      console.error('[ChatPanel] Task error:', error);
      setStatus('failed');

      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
        role: 'system',
        type: 'error',
        content: `❌ 执行失败: ${error}`,
        recoverable: true,
      });
    },
  });

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Determine if input should be disabled
  const inputDisabled = isInputDisabled(status);

  // Check for pending review state
  const hasPendingReview = messages.some(m =>
    isReviewInteractionMessage(m) && m.reviewState === 'pending'
  );

  // Auto-update pendingReviewMessage when messages change
  useEffect(() => {
    const pendingMsg = messages.findLast(m =>
      isReviewInteractionMessage(m) && m.reviewState === 'pending'
    ) as ReviewInteractionMessage | undefined;

    if (pendingMsg && !pendingReviewMessage) {
      setPendingReviewMessage(pendingMsg);
    } else if (!pendingMsg && pendingReviewMessage) {
      setPendingReviewMessage(null);
    }
  }, [messages, pendingReviewMessage, setPendingReviewMessage]);

  // Debug logging to monitor disabled state
  useEffect(() => {
    console.log('[ChatPanel] Input state changed:', {
      inputDisabled,
      isTyping,
      isUploadingFile,
      status,
      hasPendingReview,
      pendingReviewMessage: pendingReviewMessage?.layer,
      inputDisabledReason: inputDisabled ? `Status: ${status}` : 'None',
    });
  }, [inputDisabled, isTyping, isUploadingFile, status, hasPendingReview, pendingReviewMessage]);

  // Review handlers
  const handleReviewApprove = useCallback(async () => {
    if (!taskId) return;

    try {
      const response = await planningApi.approveReview(taskId);

      addMessage(createMessage({
        role: 'system',
        type: 'system',
        content: '✅ 已批准，继续执行下一层...',
      }));

      setShowReviewPanel(false);
      setStatus('planning');

      // Reconnect SSE to receive subsequent events
      if (response.resumed) {
        console.log('[ChatPanel] Approve successful, reconnecting SSE...');
        reconnectSSE?.();
      }
    } catch (error: any) {
      addMessage(createMessage({
        role: 'system',
        type: 'error',
        content: `批准失败: ${error.message || '未知错误'}`,
      }));
    }
  }, [taskId, addMessage, setStatus, setShowReviewPanel, reconnectSSE]);

  const handleReviewReject = useCallback(async (feedback: string, dimensions?: string[]) => {
    if (!taskId) return;

    try {
      addMessage(createMessage({
        role: 'user',
        type: 'text',
        content: `📝 修改请求：${feedback}`,
      }));

      addMessage(createMessage({
        role: 'system',
        type: 'system',
        content: '🔄 正在根据反馈修复规划内容...',
      }));

      await planningApi.rejectReview(taskId, feedback, dimensions);

      setShowReviewPanel(false);
      setStatus('revising');
    } catch (error: any) {
      addMessage(createMessage({
        role: 'system',
        type: 'error',
        content: `驳回失败: ${error.message || '未知错误'}`,
      }));
    }
  }, [taskId, addMessage, setStatus, setShowReviewPanel]);

  const handleRollback = useCallback(async (checkpointId: string) => {
    if (!taskId) return;

    if (!confirm('确定要回退吗？之后的内容将被删除。')) return;

    try {
      await planningApi.rollbackCheckpoint(taskId, checkpointId);

      addMessage(createMessage({
        role: 'system',
        type: 'system',
        content: `↩️ 已回退到检查点: ${checkpointId}`,
      }));

      setShowReviewPanel(false);
    } catch (error: any) {
      addMessage(createMessage({
        role: 'system',
        type: 'error',
        content: `回退失败: ${error.message || '未知错误'}`,
      }));
    }
  }, [taskId, addMessage, setShowReviewPanel]);

  const loadCheckpoints = useCallback(async () => {
    if (!taskId) return;

    try {
      const statusData = await planningApi.getTaskStatus(taskId);
      const checkpointsList = statusData.checkpoints || [];
      setCheckpoints(checkpointsList);
    } catch (error: any) {
      console.error('Failed to load checkpoints:', error);
    }
  }, [taskId, setCheckpoints]);

  // Handler: Start planning from form submission
  const handleStartPlanning = useCallback(async () => {
    if (!villageFormData) return;

    try {
      setIsPlanning(true);

      // Use uploaded file content or generate default
      const villageData = uploadedFileContent || `
# 村庄现状数据（示例）

## 基本信息
- 村庄名称：${villageFormData.projectName}
- 地理位置：中国某省某市某县
- 人口规模：约1000人
- 土地面积：约5000亩

## 产业现状
- 主要产业：农业、手工业
- 经济水平：中等偏下
`;

      await startPlanning({
        projectName: villageFormData.projectName,
        villageData: villageData,
        taskDescription: villageFormData.taskDescription || '制定村庄总体规划方案',
        constraints: villageFormData.constraints || '无特殊约束',
        enableReview: true,
        stepMode: true,
      });
    } catch (error: any) {
      console.error('[ChatPanel] Failed to start planning:', error);
      addMessage(createMessage({
        role: 'system',
        type: 'error',
        content: `启动规划失败: ${error.message || '未知错误'}`,
      }));
    } finally {
      setIsPlanning(false);
    }
  }, [villageFormData, uploadedFileContent, startPlanning, addMessage]);

  // Note: Form submission is now handled by UnifiedContentSwitcher
  // ChatPanel only handles the planning session after it has started

  // Review interaction handlers for embedded message UI
  const handleReviewInteractionApprove = useCallback(async (message: ReviewInteractionMessage) => {
    if (!taskId) return;

    try {
      const response = await planningApi.approveReview(taskId);

      // Update the review message state
      addMessage({
        ...message,
        reviewState: 'approved',
        submittedAt: new Date(),
        submittedBy: 'user',
        submissionType: 'approve',
      } as ReviewInteractionMessage);

      // Add system confirmation message
      addMessage(createMessage({
        role: 'system',
        type: 'system',
        content: '✅ 已批准，继续执行下一层...',
      }));

      setShowReviewPanel(false);
      setStatus('planning');

      // 重新创建 SSE 连接以接收后续事件
      if (response.resumed) {
        // 触发 SSE 重连
        reconnectSSE?.();
      }
    } catch (error: any) {
      addMessage(createMessage({
        role: 'system',
        type: 'error',
        content: `批准失败: ${error.message || '未知错误'}`,
      }));
    }
  }, [taskId, addMessage, setStatus, setShowReviewPanel, reconnectSSE]);

  const handleReviewInteractionReject = useCallback(async (
    message: ReviewInteractionMessage,
    feedback: string,
    dimensions?: string[]
  ) => {
    if (!taskId) return;

    try {
      // Update the review message state
      addMessage({
        ...message,
        reviewState: 'rejected',
        submittedAt: new Date(),
        submittedBy: 'user',
        submissionType: 'reject',
        submissionFeedback: feedback,
        submissionDimensions: dimensions,
      } as ReviewInteractionMessage);

      addMessage(createMessage({
        role: 'system',
        type: 'system',
        content: '🔄 正在根据反馈修复规划内容...',
      }));

      await planningApi.rejectReview(taskId, feedback, dimensions);
      setStatus('revising');
    } catch (error: any) {
      addMessage(createMessage({
        role: 'system',
        type: 'error',
        content: `驳回失败: ${error.message || '未知错误'}`,
      }));
    }
  }, [taskId, addMessage, setStatus]);

  const handleReviewInteractionRollback = useCallback(async (
    message: ReviewInteractionMessage,
    checkpointId: string
  ) => {
    if (!taskId) return;

    try {
      // Update the review message state
      addMessage({
        ...message,
        reviewState: 'rolled_back',
        submittedAt: new Date(),
        submittedBy: 'user',
        submissionType: 'rollback',
      } as ReviewInteractionMessage);

      await planningApi.rollbackCheckpoint(taskId, checkpointId);

      addMessage(createMessage({
        role: 'system',
        type: 'system',
        content: `↩️ 已回退到检查点: ${checkpointId}`,
      }));
    } catch (error: any) {
      addMessage(createMessage({
        role: 'system',
        type: 'error',
        content: `回退失败: ${error.message || '未知错误'}`,
      }));
    }
  }, [taskId, addMessage]);

  // Send message handler - now supports review feedback
  const handleSendMessage = useCallback(async () => {
    if (!inputText.trim()) return;

    const userText = inputText.trim();
    setInputText('');

    // Check if in review state
    if (hasPendingReview && pendingReviewMessage) {
      // Handle as review feedback
      if (userText === '批准' || userText.toLowerCase() === 'approve') {
        // User approved
        await handleReviewInteractionApprove(pendingReviewMessage);
      } else {
        // User rejected, input becomes feedback
        await handleReviewInteractionReject(pendingReviewMessage, userText);
      }
      return;
    }

    // Normal chat message
    addMessage({
      id: `msg-${Date.now()}`,
      timestamp: new Date(),
      role: 'user',
      type: 'text',
      content: userText,
    });

    setIsTyping(true);

    // TODO: Process message with AI
    // For now, just echo back
    setTimeout(() => {
      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
        role: 'assistant',
        type: 'text',
        content: `收到: ${userText}`,
      });
      setIsTyping(false);
    }, 500);
  }, [inputText, addMessage, hasPendingReview, pendingReviewMessage,
      handleReviewInteractionApprove, handleReviewInteractionReject]);

  // File selection handler
  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    console.log('[ChatPanel] handleFileSelect called');
    console.log('[ChatPanel] Event target:', e.target);
    console.log('[ChatPanel] Files:', e.target.files);
    console.log('[ChatPanel] Disabled state:', {
      inputDisabled,
      isTyping,
      isUploadingFile,
    });

    const file = e.target.files?.[0];
    console.log('[ChatPanel] Selected file:', file);

    if (!file) {
      console.log('[ChatPanel] No file selected, returning');
      return;
    }

    console.log('[ChatPanel] Starting file upload:', {
      name: file.name,
      size: file.size,
      type: file.type,
    });

    try {
      setIsUploadingFile(true);
      console.log('[ChatPanel] isUploadingFile set to true');

      const response = await fileApi.uploadFile(file);
      console.log('[ChatPanel] Upload response:', response);

      // Store file content for later use when starting planning
      setUploadedFileContent(response.content);

      addMessage(createMessage<FileMessage>({
        role: 'user',
        type: 'file',
        filename: file.name,
        fileContent: response.content,
        fileSize: file.size,
        encoding: response.encoding,
      }));

      const encodingInfo = response.encoding ? `\n编码: ${response.encoding}` : '';
      addMessage(createMessage({
        role: 'assistant',
        type: 'system',
        content: `✅ 文件 "${file.name}" 已上传，点击 "开始规划" 按钮启动任务\n${encodingInfo}\n内容长度: ${response.content.length} 字符`,
      }));

      e.target.value = '';

    } catch (error: any) {
      console.error('[ChatPanel] Upload error:', error);
      addMessage(createMessage({
        role: 'system',
        type: 'error',
        content: `❌ 文件上传失败: ${error.message || '未知错误'}`,
      }));
    } finally {
      setIsUploadingFile(false);
      console.log('[ChatPanel] isUploadingFile set to false');
    }
  };

  // Action handler
  const handleAction = useCallback(async (action: ActionButton, message: Message) => {
    if (action.onClick) {
      await action.onClick();
      return;
    }

    switch (action.action) {
      case 'approve':
        // Handle start planning button from file upload
        if (action.id === 'start_planning' && villageFormData) {
            // Flow from ChatPanel file upload
            console.log('[ChatPanel] 开始规划触发');
            console.log('[ChatPanel] villageFormData 状态:', villageFormData);
            console.log('[ChatPanel] 当前消息数量:', messages.length);

            // Extract content from uploaded files
            const fileMessages = messages.filter((msg: Message) => msg.type === 'file');
            console.log('[ChatPanel] 找到的文件消息数量:', fileMessages.length);
            console.log('[ChatPanel] 所有消息类型:', messages.map(m => ({ type: m.type, role: m.role })));

            let villageData: string;

            // Use uploaded file content if available, otherwise use default data
            if (fileMessages.length > 0) {
              const uploadedContent = fileMessages
                .map((msg: Message) => (msg as FileMessage).fileContent)
                .join('\n\n---\n\n');

              console.log('[ChatPanel] 提取的文件内容长度:', uploadedContent.length);
              console.log('[ChatPanel] 文件内容预览:', uploadedContent.substring(0, 200));

              // Validate file content length
              if (uploadedContent.length < MIN_FILE_CONTENT_LENGTH) {
                console.error('[ChatPanel] 文件内容过短');

                addMessage({
                  id: `msg-${Date.now()}`,
                  timestamp: new Date(),
                  role: 'system',
                  type: 'system',
                  level: 'error',
                  content: '⚠️ 上传的文件内容过短！\n\n' +
                           '要求：至少需要 50 个字符\n' +
                           '当前：' + uploadedContent.length + ' 个字符\n\n' +
                           '请确保文件包含完整的村庄现状数据。',
                });
                return;
              }

              villageData = uploadedContent;
            } else {
              // No file uploaded, use default village data
              villageData = `
# 村庄现状数据（示例）

## 基本信息
- 村庄名称：${villageFormData.projectName}
- 地理位置：中国某省某市某县
- 人口规模：约1000人
- 土地面积：约5000亩

## 产业现状
- 主要产业：农业、手工业
- 经济水平：中等偏下
`;
            }

            try {
              await startPlanning({
                projectName: villageFormData.projectName || '未命名村庄',
                villageData: villageData,
                taskDescription: villageFormData.taskDescription || '制定村庄总体规划方案',
                constraints: villageFormData.constraints || '无特殊约束',
                enableReview: true,
                stepMode: true,
              });
              console.log('[ChatPanel] 规划启动成功');
            } catch (error: any) {
              console.error('[ChatPanel] 规划启动失败:', error);
              addMessage({
                id: `msg-${Date.now()}`,
                timestamp: new Date(),
                role: 'system',
                type: 'system',
                level: 'error',
                content: `❌ 规划启动失败: ${error.message || '未知错误'}`,
              });
            }
        }
        else if (action.id === 'approve_quick') {
          await handleReviewApprove();
        } else {
          addMessage({
            id: `msg-${Date.now()}`,
            timestamp: new Date(),
            role: 'user',
            type: 'text',
            content: '批准继续',
          });
        }
        break;

      case 'reject':
        addMessage({
          id: `msg-${Date.now()}`,
          timestamp: new Date(),
          role: 'user',
          type: 'text',
          content: '请求修改',
        });
        break;

      case 'view':
        // View actions handled by component-specific handlers
        break;
    }
  }, [messages, villageFormData, startPlanning, handleReviewApprove, addMessage]);

  // Handler: 查看完整报告（移除侧边栏功能，保留日志）
  const handleOpenInSidebar = useCallback((layer: number) => {
    const layerId = getLayerId(layer);
    if (layerId) {
      console.log('[ChatPanel] Open layer report in viewer:', layerId);
      showViewer();
    }
  }, [showViewer]);

  return (
    <div className={`flex flex-col h-full bg-gray-50 ${className}`}>
      {/* Top: Progress bar and indicators - Card-style design */}
      {(status === 'collecting' || status === 'planning' || status === 'paused' || status === 'revising') && (
        <div className="flex-shrink-0 border-b border-gray-200 bg-white p-4 shadow-sm">
          {/* Progress bar - Card-style design */}
          {messages.filter(m => m.type === 'progress').length > 0 && (
            <div className="mb-3 bg-gray-50 rounded-xl p-4 shadow-sm border border-gray-200 animate-[fadeIn_0.3s_ease-in-out]">
              {messages.filter(m => m.type === 'progress').map(msg => (
                isProgressMessage(msg) && (
                  <div key={msg.id}>
                    <div className="flex justify-between items-center mb-2">
                      <span className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                        <span className="w-2 h-2 bg-green-600 rounded-full animate-pulse"></span>
                        {msg.content}
                      </span>
                      <span className="text-sm font-bold text-green-600">{msg.progress}%</span>
                    </div>
                    <div className="w-full bg-green-100 rounded-full h-2.5 overflow-hidden shadow-inner">
                      <div
                        className="bg-green-600 h-2.5 rounded-full transition-all duration-300 shadow-sm"
                        style={{ width: `${msg.progress}%` }}
                      />
                    </div>
                    {msg.currentLayer && (
                      <div className="text-xs text-gray-600 mt-2 font-medium flex items-center gap-1">
                        <FontAwesomeIcon icon={faLayerGroup} className="icon-xs text-green-600" />
                        当前层级: {msg.currentLayer}
                      </div>
                    )}
                  </div>
                )
              ))}
            </div>
          )}

          {/* Status badge - Colored + Icon + Shadow */}
          <div className="flex items-center gap-2">
            <span className={`status-badge ${
              status === 'collecting' || status === 'planning' ? 'status-badge-info' :
              status === 'paused' ? 'status-badge-warning' :
              status === 'revising' ? 'status-badge-warning' :
              status === 'completed' ? 'status-badge-success' :
              status === 'failed' ? 'status-badge-error' :
              'bg-gray-100 text-gray-700'
            }`}>
              <span className="text-base">
                {status === 'collecting' || status === 'planning' ? '🔄' :
                 status === 'paused' ? '⏸️' :
                 status === 'revising' ? '🔧' :
                 status === 'completed' ? '✅' :
                 status === 'failed' ? '❌' : '💬'}
              </span>
              {status === 'collecting' || status === 'planning' ? '执行中' :
               status === 'paused' ? '等待审查' :
               status === 'revising' ? '修复中' :
               status === 'completed' ? '已完成' :
               status === 'failed' ? '失败' : '就绪'}
            </span>

            {currentLayer && (
              <span className="status-badge status-badge-success">
                <FontAwesomeIcon icon={faLayerGroup} className="icon-xs" />
                Layer {currentLayer}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Middle: Message list - Centered container + max width */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="max-w-4xl mx-auto">
          {/* Layer Segmented Control - shown during planning/paused */}
          {(status === 'planning' || status === 'paused') && (
            <SegmentedControl
              options={LAYER_OPTIONS}
              value={currentLayer ? LAYER_VALUE_MAP[currentLayer] : LAYER_OPTIONS[0]}
              onChange={(layer) => setCurrentLayer(LAYER_LABEL_MAP[layer])}
              className="mb-4"
            />
          )}

          {/* Show "Start Planning" button when form is submitted but planning hasn't started */}
          {status === 'collecting' && villageFormData && !taskId && (
            <div className="mb-4 p-4 bg-success bg-opacity-10 rounded-3">
              <div className="d-flex align-items-center justify-content-between">
                <div>
                  <h6 className="mb-1">📋 规划任务已准备</h6>
                  <p className="small text-muted mb-0">
                    村庄：{villageFormData.projectName}
                  </p>
                </div>
                <button
                  className="btn btn-success"
                  onClick={handleStartPlanning}
                  disabled={isPlanning}
                >
                  {isPlanning ? (
                    <>
                      <span className="spinner-border spinner-border-sm me-2"></span>
                      启动中...
                    </>
                  ) : (
                    <>
                      <span className="me-2">🚀</span>
                      开始规划
                    </>
                  )}
                </button>
              </div>
            </div>
          )}

          <MessageList
            messages={messages}
            isTyping={isTyping}
            onAction={handleAction}
            onOpenInSidebar={handleOpenInSidebar}
            onViewLayerDetails={(layer) => {
              const layerId = getLayerId(layer);
              if (layerId) {
                console.log('[ChatPanel] View layer details:', layerId);
                showViewer();
              }
            }}
            onToggleAllDimensions={(layer, expand) => {
              // This would expand/collapse all dimensions in the viewer
              console.log('[ChatPanel] Toggle all dimensions for layer', layer, expand);
              // TODO: Implement expand/collapse all in LayerReportViewer
            }}
            onReviewApprove={handleReviewInteractionApprove}
            onReviewReject={handleReviewInteractionReject}
            onReviewRollback={handleReviewInteractionRollback}
            reviewDisabled={status === 'revising'}
          />
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Bottom: Input area */}
      <div className="border-t bg-white p-4">
        <div className="max-w-3xl mx-auto">
          {/* Review mode indicator */}
          {hasPendingReview && pendingReviewMessage && (
            <div className="mb-2 px-3 py-1.5 bg-orange-50 border border-orange-200 rounded-lg flex items-center gap-2">
              <FontAwesomeIcon icon={faEdit} className="text-orange-500" />
              <span className="text-sm text-orange-700 font-medium">
                审查模式：输入修改意见后按 Enter 发送驳回，或输入 "批准" 继续
              </span>
            </div>
          )}

          {/* 合并式输入框：包含文件上传和文本输入 */}
          <div className="flex items-center gap-2">
            {/* 文件上传按钮（原生） */}
            <input
              type="file"
              accept={FILE_ACCEPT}
              onChange={(e) => {
                console.log('[ChatPanel File Input] onChange triggered');
                console.log('[ChatPanel File Input] Event:', e);
                console.log('[ChatPanel File Input] Files:', e.target.files);
                handleFileSelect(e);
              }}
              onClick={() => {
                console.log('[ChatPanel File Input] onClick triggered');
              }}
              onFocus={() => {
                console.log('[ChatPanel File Input] onFocus triggered');
              }}
              disabled={inputDisabled || isTyping || isUploadingFile}
              className="form-control form-control-sm"
              style={{ width: 'auto' }}
            />

            {/* 文本输入框 */}
            <textarea
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  if (inputText.trim() && !isTyping) handleSendMessage();
                }
              }}
              disabled={inputDisabled || isTyping}
              placeholder={
                hasPendingReview && pendingReviewMessage
                  ? `请输入对 Layer ${pendingReviewMessage.layer} 的修改意见... (Enter 发送驳回，留空输入 "批准" 继续)`
                  : status === 'planning' || status === 'collecting'
                    ? '规划进行中...'
                    : '输入消息... (Enter 发送, Shift+Enter 换行)'
              }
              className={`form-control flex-1 ${
                hasPendingReview ? 'border-orange-400 border-2 shadow-orange-100' : ''
              }`}
              rows={1}
            />

            {/* 发送按钮 */}
            <button
              onClick={handleSendMessage}
              disabled={inputDisabled || isTyping || !inputText.trim() || isUploadingFile}
              className="btn btn-success"
            >
              {isUploadingFile ? '上传中...' : isTyping ? '发送中...' : '发送'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
