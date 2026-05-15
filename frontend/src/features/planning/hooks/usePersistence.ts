/**
 * Message Persistence Hook
 *
 * Automatically saves new messages to the backend.
 * Extracted from PlanningProvider for better separation of concerns.
 *
 * Features:
 * - Auto-save new messages to backend
 * - Skip messages marked as _pendingStorage
 * - Batch save when sessionId transitions from null to a value
 * - Track saved message IDs to prevent duplicates
 */

import { useEffect, useRef } from 'react';
import { usePlanningStore } from '../store/planningStore';
import type { Message, DimensionReportMessage, LayerCompletedMessage } from '../types';

interface UseMessagePersistenceOptions {
  enabled?: boolean;
}

export function useMessagePersistence({ enabled = true }: UseMessagePersistenceOptions = {}): void {
  // Refs for tracking saved messages
  const savedMessageIdsRef = useRef<Set<string>>(new Set());
  const prevSessionIdRef = useRef<string | null>(null);
  // 暂存 sessionId 为空时的消息
  const pendingMessagesRef = useRef<Message[]>([]);
  // 版本跟踪：用于检测 layer_completed 消息是否需要更新保存
  const messageVersionsRef = useRef<Map<string, { dimensionCount: number; wordCount: number }>>(new Map());

  // Store state
  const sessionId = usePlanningStore((state) => state.sessionId);
  const messages = usePlanningStore((state) => state.messages);
  const dimensionProgress = usePlanningStore((state) => state.dimensionProgress);

  // Check if a message should be updated (for layer_completed and dimension_report)
  function shouldMessageBeUpdated(msg: Message): boolean {
    // Handle dimension_report messages
    if (msg.type === 'dimension_report') {
      const dimMsg = msg as DimensionReportMessage;
      // Only save when streamingState becomes completed
      return dimMsg.streamingState === 'completed';
    }

    // Handle layer_completed messages
    if (msg.type !== 'layer_completed') return false;
    const layerMsg = msg as LayerCompletedMessage;

    // 先检查内容完整性（前置过滤）
    const hasReports = layerMsg.dimensionReports && Object.keys(layerMsg.dimensionReports).length > 0;
    const hasContent = layerMsg.fullReportContent && layerMsg.fullReportContent.length >= 50;
    if (!hasReports || !hasContent) return false;

    // Use layer + id as version tracking key to distinguish different layers
    const versionKey = `${msg.id}_layer${layerMsg.layer}`;
    const currentVersion = messageVersionsRef.current.get(versionKey);

    if (!currentVersion) return true;
    if (msg._pendingStorage) return false;

    const newDimensionCount = layerMsg.summary?.dimension_count || 0;
    const newWordCount = layerMsg.summary?.word_count || 0;

    // Update if dimension count increased or word count increased significantly
    return newDimensionCount > currentVersion.dimensionCount || newWordCount > currentVersion.wordCount + 500;
  }

  // Save a single message to backend
  const saveSingleMessage = async (msg: Message, _currentSessionId: string) => {
    // Check if message needs update (for layer_completed messages)
    const needsUpdate = shouldMessageBeUpdated(msg);

    // Skip if already saved and doesn't need update
    if (savedMessageIdsRef.current.has(msg.id) && !needsUpdate) {
      return;
    }

    // Skip layer placeholder messages during SSE streaming
    if (msg._pendingStorage) {
      return;
    }

    // For layer_completed messages, verify data completeness before saving
    if (msg.type === 'layer_completed') {
      const layerMsg = msg as LayerCompletedMessage;

      // Log for debugging
      const reportCount = layerMsg.dimensionReports ? Object.keys(layerMsg.dimensionReports).length : 0;
      const contentLength = layerMsg.fullReportContent?.length || 0;
      console.log(
        `[Persistence] layer_completed check: id=${msg.id}, layer=${layerMsg.layer}, reports=${reportCount}, content=${contentLength}`
      );

      // Lower threshold: allow 50+ chars for saving (was 100)
      if (!layerMsg.dimensionReports || Object.keys(layerMsg.dimensionReports).length === 0) {
        console.warn(`[Persistence] Skipping layer_completed (no dimensionReports): ${msg.id}`);
        return;
      }
      if (!layerMsg.fullReportContent || layerMsg.fullReportContent.length < 50) {
        console.warn(
          `[Persistence] Skipping layer_completed (content too short): ${msg.id}, length=${layerMsg.fullReportContent?.length ?? 0}`
        );
        return;
      }
    }

    try {
      savedMessageIdsRef.current.add(msg.id);

      // Update version tracking for layer_completed messages
      if (msg.type === 'layer_completed') {
        const layerMsg = msg as LayerCompletedMessage;
        // Use layer + id as version tracking key
        const versionKey = `${msg.id}_layer${layerMsg.layer}`;
        messageVersionsRef.current.set(versionKey, {
          dimensionCount: layerMsg.summary?.dimension_count || 0,
          wordCount: layerMsg.summary?.word_count || 0,
        });
      }
    } catch (error) {
      console.error(`[useMessagePersistence] Failed to save message ${msg.id}:`, error);
    }
  };

  useEffect(() => {
    if (!enabled) return;

    // Debug: 记录 layer_completed 消息状态
    const layerCompletedMsgs = messages.filter((m) => m.type === 'layer_completed');
    if (layerCompletedMsgs.length > 0) {
      console.log(
        '[Persistence] useEffect triggered:',
        layerCompletedMsgs.map((m) => ({
          id: m.id,
          layer: (m as LayerCompletedMessage).layer,
          reportCount: Object.keys((m as LayerCompletedMessage).dimensionReports || {}).length,
          contentLength: (m as LayerCompletedMessage).fullReportContent?.length || 0,
        }))
      );
    }

    // 检测 sessionId 状态转换（不在初始化时设置 prev，确保 sessionIdJustSet 能正确检测）
    const sessionIdJustSet = sessionId && !prevSessionIdRef.current;
    prevSessionIdRef.current = sessionId;

    // 没有 sessionId 时，暂存所有新消息，等待 sessionId 有值后批量保存
    if (!sessionId) {
      const unsaved = messages.filter(
        (msg) => !savedMessageIdsRef.current.has(msg.id) && !msg._pendingStorage
      );
      if (unsaved.length > 0) {
        pendingMessagesRef.current.push(...unsaved);
      }
      return;
    }

    // 有 sessionId 时，准备要保存的消息列表
    const messagesToSave: Message[] = [];

    // sessionIdJustSet 时，批量保存暂存消息 + 当前消息
    if (sessionIdJustSet) {
      // 1. 先保存暂存的消息
      if (pendingMessagesRef.current.length > 0) {
        messagesToSave.push(...pendingMessagesRef.current);
        pendingMessagesRef.current = [];
      }

      // 2. 批量保存当前所有未保存消息
      const unsavedCurrent = messages.filter(
        (msg) => !savedMessageIdsRef.current.has(msg.id) && !msg._pendingStorage
      );
      messagesToSave.push(...unsavedCurrent);
    } else {
      // 常规保存：只保存最后一条消息
      const lastMessage = messages[messages.length - 1];
      if (
        lastMessage &&
        !savedMessageIdsRef.current.has(lastMessage.id) &&
        !lastMessage._pendingStorage
      ) {
        messagesToSave.push(lastMessage);
      }
    }

    // Check layer_completed and dimension_report messages for potential updates (single pass)
    const updatableTypes = ['layer_completed', 'dimension_report'];
    for (const msg of messages) {
      if (updatableTypes.includes(msg.type) && !msg._pendingStorage && shouldMessageBeUpdated(msg)) {
        messagesToSave.push(msg);
      }
    }

    // 执行保存
    for (const msg of messagesToSave) {
      saveSingleMessage(msg, sessionId);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- saveSingleMessage 只依赖 refs (稳定) 和传入参数，无需加入依赖
  }, [messages, sessionId, enabled, dimensionProgress]);
}

export default useMessagePersistence;
