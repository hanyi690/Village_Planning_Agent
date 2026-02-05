'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useConversationContext } from '@/contexts/ConversationContext';
import { Message, ActionButton } from '@/types/message';
import { isUserMessage, isActionMessage, isProgressMessage, isResultMessage, isErrorMessage } from '@/types/message';
import { taskApi, sessionApi } from '@/lib/api';
import FileUpload from './FileUpload';

interface ChatInterfaceProps {
  conversationId: string;
  onTaskStart?: (taskId: string) => void;
  onViewerToggle?: () => void;
}

type CollectionPhase = 'idle' | 'collecting_name' | 'collecting_data' | 'ready_to_start';

export default function ChatInterface({ conversationId, onTaskStart, onViewerToggle }: ChatInterfaceProps) {
  const {
    messages,
    addMessage,
    status,
    setTaskId,
    setProjectName,
    setStatus,
    showViewer,
  } = useConversationContext();

  const [inputText, setInputText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [collectionPhase, setCollectionPhase] = useState<CollectionPhase>('idle');
  const [collectedData, setCollectedData] = useState({
    projectName: '',
    villageData: '',
  });

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll and focus
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Start planning with collected data
  const startPlanning = useCallback(async () => {
    if (!collectedData.projectName || !collectedData.villageData) return;

    try {
      setStatus('planning');
      setCollectionPhase('idle');

      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
        role: 'system',
        type: 'system',
        content: '🚀 正在启动规划任务...',
      });

      // Create task using new unified API
      const task = await taskApi.createTask({
        project_name: collectedData.projectName,
        village_data: collectedData.villageData,
        task_description: '制定村庄总体规划方案',
        constraints: '无特殊约束',
        step_mode: true,
        stream_mode: true,
        input_mode: 'text',
      });

      // Link session to task
      await sessionApi.linkToTask(conversationId, task.task_id);

      setTaskId(task.task_id);
      setProjectName(collectedData.projectName);

      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
        role: 'system',
        type: 'system',
        content: `✅ 规划任务已启动\n\n任务ID: ${task.task_id}\n村庄: ${collectedData.projectName}`,
      });

      onTaskStart?.(task.task_id);
      showViewer();
    } catch (error: any) {
      console.error('[ChatInterface] Failed to start planning:', error);
      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
        role: 'system',
        type: 'error',
        content: `启动规划失败: ${error.message}`,
      });
      setStatus('idle');
    }
  }, [collectedData, conversationId, addMessage, setTaskId, setProjectName, setStatus, onTaskStart, showViewer]);

  // Process user message through state machine
  const processUserMessage = useCallback(async (text: string, hasFile: boolean, fileContent?: string) => {
    setIsTyping(true);
    const userMessage = text.trim();

    if (collectionPhase === 'idle') {
      if (hasFile) {
        setCollectedData(prev => ({ ...prev, villageData: fileContent || '' }));
        setCollectionPhase('collecting_name');
        addMessage({
          id: `msg-${Date.now()}`,
          timestamp: new Date(),
          role: 'assistant',
          type: 'text',
          content: `📄 已收到村庄现状数据文件\n\n请告诉我村庄名称和人口规模（例如：金田村，500人）`,
        });
      } else if (userMessage.length < 50) {
        setCollectedData(prev => ({ ...prev, projectName: userMessage }));
        setCollectionPhase('collecting_data');
        addMessage({
          id: `msg-${Date.now()}`,
          timestamp: new Date(),
          role: 'assistant',
          type: 'text',
          content: `好的，村庄名称是：${userMessage}\n\n请提供村庄现状数据，您可以：\n1. 上传文件\n2. 直接粘贴文本\n3. 简要描述村庄情况`,
        });
      } else {
        setCollectedData(prev => ({ ...prev, villageData: userMessage }));
        setCollectionPhase('collecting_name');
        addMessage({
          id: `msg-${Date.now()}`,
          timestamp: new Date(),
          role: 'assistant',
          type: 'text',
          content: `已收到村庄数据\n\n请告诉我村庄名称`,
        });
      }
    } else if (collectionPhase === 'collecting_name') {
      setCollectedData(prev => ({ ...prev, projectName: userMessage }));
      setProjectName(userMessage);
      setCollectionPhase('ready_to_start');

      if (collectedData.villageData || fileContent) {
        addMessage({
          id: `msg-${Date.now()}`,
          timestamp: new Date(),
          role: 'assistant',
          type: 'action',
          content: `✅ 信息收集完成！\n\n村庄名称: ${userMessage}\n现状数据: 已提供\n\n准备好开始规划了吗？`,
          actions: [
            { id: 'start', label: '开始规划', action: 'approve', variant: 'primary' },
            { id: 'modify', label: '修改信息', action: 'modify', variant: 'secondary' },
          ],
        });
      } else {
        setCollectionPhase('collecting_data');
        addMessage({
          id: `msg-${Date.now()}`,
          timestamp: new Date(),
          role: 'assistant',
          type: 'text',
          content: `好的，村庄名称是：${userMessage}\n\n请提供村庄现状数据`,
        });
      }
    } else if (collectionPhase === 'collecting_data') {
      setCollectedData(prev => ({ ...prev, villageData: hasFile ? (fileContent || '') : userMessage }));
      setCollectionPhase('ready_to_start');

      addMessage({
        id: `msg-${Date.now()}`,
        timestamp: new Date(),
        role: 'assistant',
        type: 'action',
        content: `✅ 信息收集完成！\n\n村庄名称: ${collectedData.projectName}\n现状数据: 已提供\n\n准备好开始规划了吗？`,
        actions: [
          { id: 'start', label: '开始规划', action: 'approve', variant: 'primary' },
          { id: 'modify', label: '修改信息', action: 'modify', variant: 'secondary' },
        ],
      });
    } else if (collectionPhase === 'ready_to_start') {
      if (userMessage.includes('修改') || userMessage.includes('重填')) {
        setCollectionPhase('idle');
        setCollectedData({ projectName: '', villageData: '' });
        addMessage({
          id: `msg-${Date.now()}`,
          timestamp: new Date(),
          role: 'assistant',
          type: 'text',
          content: `好的，让我们重新开始。\n\n请告诉我村庄名称和现状数据。`,
        });
      } else {
        await startPlanning();
      }
    }

    setIsTyping(false);
  }, [collectionPhase, collectedData, addMessage, setProjectName, startPlanning]);

  // Handlers
  const handleFileUpload = useCallback(async (uploadedFile: File, content: string) => {
    addMessage({
      id: `msg-${Date.now()}`,
      timestamp: new Date(),
      role: 'user',
      type: 'file',
      filename: uploadedFile.name,
      fileContent: content,
      fileSize: uploadedFile.size,
    });

    await processUserMessage('', true, content);
  }, [addMessage, processUserMessage]);

  const handleSendMessage = useCallback(async () => {
    if (!inputText.trim()) return;

    const userText = inputText.trim();
    setInputText('');

    addMessage({
      id: `msg-${Date.now()}`,
      timestamp: new Date(),
      role: 'user',
      type: 'text',
      content: userText,
    });

    await processUserMessage(userText, false);
  }, [inputText, addMessage, processUserMessage]);

  const handleAction = useCallback(async (action: ActionButton, message: Message) => {
    if (action.onClick) {
      await action.onClick();
      return;
    }

    switch (action.action) {
      case 'approve':
        if (action.id === 'start' && collectionPhase === 'ready_to_start') {
          addMessage({
            id: `msg-${Date.now()}`,
            timestamp: new Date(),
            role: 'user',
            type: 'text',
            content: '开始规划',
          });
          await startPlanning();
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
        onViewerToggle?.();
        break;

      case 'modify':
        setCollectionPhase('idle');
        setCollectedData({ projectName: '', villageData: '' });
        addMessage({
          id: `msg-${Date.now()}`,
          timestamp: new Date(),
          role: 'user',
          type: 'text',
          content: '重新填写信息',
        });
        addMessage({
          id: `msg-${Date.now()}`,
          timestamp: new Date(),
          role: 'assistant',
          type: 'text',
          content: `好的，让我们重新开始。\n\n请告诉我村庄名称和现状数据。`,
        });
        break;
    }
  }, [collectionPhase, addMessage, startPlanning, onViewerToggle]);

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // Render message
  const renderMessage = (message: Message) => {
    const isUser = isUserMessage(message);

    return (
      <div
        key={message.id}
        className={`message ${isUser ? 'user-message' : 'assistant-message'}`}
        style={{
          display: 'flex',
          justifyContent: isUser ? 'flex-end' : 'flex-start',
          marginBottom: '1rem',
        }}
      >
        <div
          className="message-bubble"
          style={{
            maxWidth: '70%',
            padding: '0.75rem 1rem',
            borderRadius: '1rem',
            backgroundColor: isUser ? 'var(--primary-green)' : '#f0f0f0',
            color: isUser ? 'white' : 'black',
            wordBreak: 'break-word',
          }}
        >
          {!isUser && message.type !== 'progress' && (
            <div style={{ fontSize: '0.75rem', color: '#666', marginBottom: '0.25rem' }}>
              AI 助手
            </div>
          )}

          {message.type === 'text' && <div style={{ whiteSpace: 'pre-wrap' }}>{message.content}</div>}

          {message.type === 'file' && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <i className="fas fa-file-alt"></i>
                <span>{message.filename}</span>
                {message.fileSize && (
                  <span style={{ fontSize: '0.75rem', opacity: isUser ? 0.8 : 0.7 }}>
                    ({(message.fileSize / 1024).toFixed(2)} KB)
                  </span>
                )}
              </div>
            </div>
          )}

          {message.type === 'progress' && isProgressMessage(message) && (
            <div>
              <div>{message.content}</div>
              <div className="progress mt-2" style={{ height: '0.5rem' }}>
                <div
                  className="progress-bar progress-bar-striped progress-bar-animated"
                  role="progressbar"
                  style={{ width: `${message.progress}%` }}
                  aria-valuenow={message.progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                />
              </div>
              {message.currentLayer && (
                <div style={{ fontSize: '0.75rem', marginTop: '0.25rem', opacity: 0.8 }}>
                  当前: {message.currentLayer}
                </div>
              )}
            </div>
          )}

          {message.type === 'action' && isActionMessage(message) && (
            <div>
              <div style={{ marginBottom: '0.5rem' }}>{message.content}</div>
              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                {message.actions.map((action) => (
                  <button
                    key={action.id}
                    className={`btn btn-${action.variant || 'secondary'} btn-sm`}
                    onClick={() => handleAction(action, message)}
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {message.type === 'result' && isResultMessage(message) && (
            <div>
              <div style={{ marginBottom: '0.5rem' }}>{message.content}</div>
              <div style={{ fontSize: '0.875rem', marginBottom: '0.5rem' }}>
                村庄: {message.villageName}
              </div>
              <button
                className="btn btn-primary btn-sm"
                onClick={() => {
                  if (message.resultUrl) {
                    window.location.href = message.resultUrl;
                  }
                }}
              >
                <i className="fas fa-eye me-2"></i>
                查看结果
              </button>
            </div>
          )}

          {message.type === 'error' && isErrorMessage(message) && (
            <div style={{ color: isUser ? 'white' : '#dc3545' }}>
              <i className="fas fa-exclamation-circle me-2"></i>
              {message.content}
            </div>
          )}

          {message.type === 'system' && (
            <div style={{
              fontSize: '0.875rem',
              opacity: 0.9,
              backgroundColor: 'rgba(255,255,255,0.3)',
              padding: '0.5rem',
              borderRadius: '0.5rem',
            }}>
              {message.content}
            </div>
          )}

          <div style={{
            fontSize: '0.625rem',
            opacity: isUser ? 0.8 : 0.6,
            marginTop: '0.25rem',
            textAlign: 'right',
          }}>
            {new Date(message.timestamp).toLocaleTimeString()}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="chat-interface" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Messages area */}
      <div
        className="messages-container"
        style={{ flex: 1, overflowY: 'auto', padding: '1rem', backgroundColor: '#f8f9fa' }}
      >
        {/* Welcome message */}
        {messages.length === 0 && (
          <div className="message assistant-message">
            <div
              className="message-bubble"
              style={{ maxWidth: '70%', padding: '0.75rem 1rem', borderRadius: '1rem', backgroundColor: '#f0f0f0' }}
            >
              <div style={{ marginBottom: '0.5rem' }}>
                <i className="fas fa-robot me-2"></i>
                AI 助手
              </div>
              <div>
                👋 欢迎使用村庄规划智能体！
                <br /><br />
                我可以帮您:
                <ul style={{ marginTop: '0.5rem', paddingLeft: '1.5rem' }}>
                  <li>创建村庄规划方案</li>
                  <li>分析村庄现状数据</li>
                  <li>生成规划思路和详细方案</li>
                  <li>根据反馈修改规划</li>
                </ul>
                <br />
                请上传村庄现状数据文件，或直接告诉我村庄名称和信息。
              </div>
            </div>
          </div>
        )}

        {messages.map(renderMessage)}

        {isTyping && (
          <div className="message assistant-message">
            <div
              className="message-bubble"
              style={{ maxWidth: '70%', padding: '0.75rem 1rem', borderRadius: '1rem', backgroundColor: '#f0f0f0' }}
            >
              <div className="typing-indicator">
                <i className="fas fa-spinner fa-spin me-2"></i>
                正在思考...
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div style={{ padding: '1rem', borderTop: '1px solid #dee2e6', backgroundColor: 'white' }}>
        {status !== 'planning' && (
          <div className="mb-2">
            <FileUpload onUpload={handleFileUpload} loading={isTyping} />
          </div>
        )}

        <div className="input-group">
          <textarea
            ref={inputRef}
            className="form-control"
            placeholder={
              status === 'planning'
                ? '规划进行中...'
                : collectionPhase === 'ready_to_start'
                ? '点击"开始规划"或输入更多信息'
                : '输入消息... (Enter 发送, Shift+Enter 换行)'
            }
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyPress={handleKeyPress}
            disabled={status === 'planning' || isTyping}
            rows={2}
            style={{ resize: 'none', borderRadius: '1rem' }}
          />
          <button
            className="btn btn-primary"
            onClick={handleSendMessage}
            disabled={status === 'planning' || isTyping || !inputText.trim()}
            style={{ marginLeft: '0.5rem', borderRadius: '1rem', padding: '0.5rem 1.5rem' }}
          >
            <i className="fas fa-paper-plane"></i>
          </button>
        </div>

        {onViewerToggle && collectedData.projectName && (
          <button
            className="btn btn-outline-secondary btn-sm mt-2"
            onClick={onViewerToggle}
            style={{ width: '100%' }}
          >
            <i className="fas fa-columns me-2"></i>
            切换查看器
          </button>
        )}
      </div>
    </div>
  );
}
