import type {
  DimensionStatus,
  LayerCompletedMessage,
  DimensionReportMessage,
  KnowledgeSource,
} from '../../types';
import type {
  GisResultMessage,
  ToolStatusMessage,
  GISLayerConfig,
} from '@/types/message/message-types';
import type { PipelineTrace, PlanningState, StoreEvent } from '../planningStore';
import type { HumanReviewItem } from '../../api/types';
import { NAV_KEYS } from '../../constants';
import {
  createBaseMessage,
  buildLayerReportId,
  buildRevisionReportId,
  buildDimensionProgressKey,
  formatDimensionReportsAsContent,
  calculateReportSummary,
} from '../../utils/message-helpers';
import {
  DIMENSION_NAMES,
  getDimensionsByLayer,
  getDimensionLayer,
} from '../../config/dimensions';
import { deriveUIStateInStore, type Reports } from './derivedState';

export function handleSSEEventInStore(
  state: PlanningState,
  event: StoreEvent,
): void {
  const eventType = event.type;
  const data = (event.data as Record<string, unknown>) || {};

  const seq = (data.seq as number) || 0;
  if (seq > 0) {
    if (seq <= state.lastProcessedSeq) {
      return;
    }
    state.lastProcessedSeq = seq;
  }

  switch (eventType) {
    case 'connected': {
      state.status = 'planning';
      const connData = data as { task_id?: string };
      if (connData.task_id && !state.sessionId) {
        state.sessionId = connData.task_id;
      }
      break;
    }

    case 'completed': {
      state.status = 'completed';
      break;
    }

    case 'dimension_error': {
      const errData = data as {
        dimension_key?: string;
        dimension_name?: string;
        error?: string;
        error_type?: string;
        layer?: number;
      };
      const layer = errData.layer || 1;
      const key = `${layer}_${errData.dimension_key || ''}`;

      state.dimensionProgress[key] = {
        dimensionKey: errData.dimension_key || '',
        dimensionName: errData.dimension_name || '',
        layer,
        status: 'failed' as DimensionStatus,
        wordCount: 0,
        error: errData.error || 'Unknown error',
      };

      state.executingDimensions = state.executingDimensions.filter(
        (k) => k !== key,
      );
      break;
    }

    case 'dimension_start': {
      const dimData = data as {
        dimension_key?: string;
        dimension_name?: string;
        layer?: number;
        is_revision?: boolean;
      };
      const layer = dimData.layer || 1;
      const dimensionKey = dimData.dimension_key || '';
      const key = buildDimensionProgressKey(layer, dimensionKey);

      state.executingDimensions.push(key);

      state.dimensionProgress[key] = {
        dimensionKey,
        dimensionName: dimData.dimension_name || '',
        layer,
        status: 'streaming' as DimensionStatus,
        wordCount: 0,
        isRevision: dimData.is_revision || false,
      };

      if (dimData.is_revision && dimensionKey) {
        const layerKey = `layer${layer}` as keyof Reports;
        state.reports[layerKey][dimensionKey] = '';
        delete state.streamingContent[key];

        const revisionReportId = buildRevisionReportId(layer, dimensionKey);
        const existingMessage = state.messages.find(
          (m) => m.id === revisionReportId && m.type === 'dimension_report',
        );
        if (!existingMessage) {
          const baseMsg = createBaseMessage('assistant');
          const newMessage: DimensionReportMessage = {
            ...baseMsg,
            id: revisionReportId,
            type: 'dimension_report',
            layer: layer,
            dimensionKey,
            dimensionName: dimData.dimension_name || '',
            content: '',
            streamingState: 'streaming',
            wordCount: 0,
            isRevision: true,
          };
          state.messages.push(newMessage);
        }
      }
      break;
    }

    case 'dimension_delta': {
      const dimData = data as {
        dimension_key?: string;
        dimension_name?: string;
        delta?: string;
        accumulated?: string;
        layer?: number;
        is_revision?: boolean;
      };
      const layer = dimData.layer || 1;
      const dimensionKey = dimData.dimension_key || '';
      const key = buildDimensionProgressKey(layer, dimensionKey);

      if (dimData.is_revision && dimensionKey && dimData.accumulated) {
        const revisionReportId = buildRevisionReportId(layer, dimensionKey);
        const msgIdx = state.messages.findIndex(
          (m) => m.id === revisionReportId && m.type === 'dimension_report',
        );
        if (msgIdx >= 0) {
          const msg = state.messages[msgIdx] as DimensionReportMessage;
          msg.content = dimData.accumulated;
          msg.wordCount = dimData.accumulated.length;
        }
        const existing = state.dimensionProgress[key];
        if (existing) {
          existing.wordCount = dimData.accumulated.length;
        }
      }

      const layerKey = `layer${layer}` as keyof Reports;
      if (dimensionKey && dimData.accumulated) {
        state.reports[layerKey][dimensionKey] = dimData.accumulated;
      }

      const layerReportId = buildLayerReportId(layer);
      const layerMsgIdx = state.messages.findIndex(
        (m) => m.id === layerReportId && m.type === 'layer_completed',
      );

      if (layerMsgIdx >= 0 && dimensionKey && dimData.accumulated) {
        const layerMsg = state.messages[layerMsgIdx] as LayerCompletedMessage;
        if (!layerMsg.dimensionReports) {
          layerMsg.dimensionReports = {};
        }
        layerMsg.dimensionReports[dimensionKey] = dimData.accumulated;
      }

      if (dimData.accumulated) {
        const existing = state.dimensionProgress[key];
        if (existing) {
          existing.wordCount = dimData.accumulated.length;
        } else {
          state.dimensionProgress[key] = {
            dimensionKey,
            dimensionName: dimData.dimension_name || dimensionKey,
            layer,
            status: 'streaming' as DimensionStatus,
            wordCount: dimData.accumulated.length,
          };
          if (!state.executingDimensions.includes(key)) {
            state.executingDimensions.push(key);
          }
        }
      }
      break;
    }

    case 'dimension_complete': {
      const dimData = data as {
        dimension_key?: string;
        dimension_name?: string;
        full_content?: string;
        word_count?: number;
        layer?: number;
        is_revision?: boolean;
        knowledge_sources?: KnowledgeSource[];
        structured_summary?: {
          dimension_key?: string;
          layer?: number;
          word_count?: number;
          key_points?: string[];
          text_summary?: string;
          metrics?: Record<string, unknown>;
        };
      };
      const layer = dimData.layer || 1;
      const dimensionKey = dimData.dimension_key || '';
      const key = buildDimensionProgressKey(layer, dimensionKey);

      const lk = `layer${layer}` as keyof Reports;
      const content =
        dimData.full_content || state.reports[lk]?.[dimensionKey] || '';

      state.dimensionProgress[key] = {
        dimensionKey,
        dimensionName: dimData.dimension_name || '',
        layer,
        status: 'completed' as DimensionStatus,
        wordCount: dimData.word_count || content.length,
        completedAt: new Date().toISOString(),
        isRevision: dimData.is_revision || false,
      };

      state.executingDimensions = state.executingDimensions.filter(
        (k) => k !== key,
      );

      if (dimData.is_revision && dimensionKey) {
        const revKey = `${layer}_${dimensionKey}`;
        if (!state.revisionCompletedKeys.includes(revKey)) {
          state.revisionCompletedKeys.push(revKey);
        }
        const revisionReportId = buildRevisionReportId(layer, dimensionKey);
        const msgIdx = state.messages.findIndex(
          (m) => m.id === revisionReportId && m.type === 'dimension_report',
        );
        if (msgIdx >= 0) {
          const msg = state.messages[msgIdx] as DimensionReportMessage;
          msg.content = content;
          msg.wordCount = content.length;
          msg.streamingState = 'completed';
        }
      }

      const layerKey = `layer${layer}` as keyof Reports;
      state.reports[layerKey][dimensionKey] = content;

      const layerReportId = buildLayerReportId(layer);
      const layerMsgIdx = state.messages.findIndex(
        (m) => m.id === layerReportId && m.type === 'layer_completed',
      );

      if (layerMsgIdx >= 0) {
        const layerMsg = state.messages[layerMsgIdx] as LayerCompletedMessage;
        if (!layerMsg.dimensionReports) {
          layerMsg.dimensionReports = {};
        }
        layerMsg.dimensionReports[dimensionKey] = content;

        layerMsg.fullReportContent = formatDimensionReportsAsContent(
          layerMsg.dimensionReports,
        );
        const summary = calculateReportSummary(
          layerMsg.dimensionReports,
          layerMsg.dimensionSummaries,
        );
        layerMsg.summary.word_count = summary.word_count;
        layerMsg.summary.dimension_count = summary.dimension_count;

        if (dimData.structured_summary?.key_points?.length) {
          if (!layerMsg.dimensionSummaries) {
            layerMsg.dimensionSummaries = {};
          }
          const summary = {
            ...dimData.structured_summary,
            dimension_key:
              dimData.structured_summary.dimension_key || dimensionKey,
          };
          layerMsg.dimensionSummaries[dimensionKey] = summary;
          layerMsg.summary.key_points = Object.values(
            layerMsg.dimensionSummaries,
          )
            .flatMap((s) => s.key_points || [])
            .slice(0, 10);
        }

        if (dimData.knowledge_sources && dimData.knowledge_sources.length > 0) {
          if (!layerMsg.dimensionKnowledgeSources) {
            layerMsg.dimensionKnowledgeSources = {};
          }
          layerMsg.dimensionKnowledgeSources[dimensionKey] =
            dimData.knowledge_sources;
        }
      }

      const expectedPhase = `layer${layer}`;
      if (state.phase !== expectedPhase) {
        state.phase = expectedPhase;
      }

      deriveUIStateInStore(state);

      const completedCountForLayer =
        state.completedDimensions[layerKey]?.length || 0;
      const expectedCount =
        state.layerDimensionCount[layer] || getDimensionsByLayer(layer).length;

      if (
        completedCountForLayer >= expectedCount &&
        expectedCount > 0 &&
        state.status !== 'paused'
      ) {
        state.previous_layer = layer;
        state.status = 'paused';
        deriveUIStateInStore(state);
      }
      break;
    }

    case 'layer_started': {
      const layerData = data as {
        layer?: number;
        layer_number?: number;
        dimension_count?: number;
      };
      const layerNum = layerData.layer || layerData.layer_number || 1;

      state.phase = `layer${layerNum}`;

      if (
        layerData.dimension_count &&
        state.layerDimensionCount[layerNum] !== layerData.dimension_count
      ) {
        state.layerDimensionCount[layerNum] = layerData.dimension_count;
      }

      state.dimensionProgress = Object.fromEntries(
        Object.entries(state.dimensionProgress).filter(
          ([key]) => !key.startsWith(`${layerNum}_`),
        ),
      );
      state.executingDimensions = state.executingDimensions.filter(
        (k) => !k.startsWith(`${layerNum}_`),
      );

      const layerReportId = buildLayerReportId(layerNum);
      const existingMessage = state.messages.find(
        (m) => m.id === layerReportId && m.type === 'layer_completed',
      );

      if (!existingMessage) {
        const baseMsg = createBaseMessage('assistant');
        const newMessage: LayerCompletedMessage = {
          ...baseMsg,
          id: layerReportId,
          type: 'layer_completed',
          layer: layerNum,
          content: '',
          summary: {
            word_count: 0,
            key_points: [],
            dimension_count: 0,
          },
          fullReportContent: '',
          dimensionReports: {},
          actions: [],
        };
        state.messages.push(newMessage);
      }

      if (state.selectedNavigationKey !== NAV_KEYS.OVERVIEW) {
        state.selectedNavigationKey = NAV_KEYS.OVERVIEW;
      }

      deriveUIStateInStore(state);
      break;
    }

    case 'layer_completed': {
      const layerData = data as {
        layer?: number;
        phase?: string;
        dimension_reports?: Record<string, string>;
        dimension_knowledge_sources?: Record<string, KnowledgeSource[]>;
        previous_layer?: number;
        task_id?: string;
      };

      if (layerData.task_id && !state.sessionId) {
        state.sessionId = layerData.task_id;
      }

      const layerNum = layerData.layer || 1;
      const layerKey = `layer${layerNum}` as keyof Reports;

      if (
        layerData.dimension_reports &&
        Object.keys(layerData.dimension_reports).length > 0
      ) {
        Object.assign(state.reports[layerKey], layerData.dimension_reports);
      }

      state.phase = layerData.phase || state.phase;
      state.previous_layer = layerData.previous_layer ?? state.previous_layer;
      state.status = 'paused';

      if (
        state.step_mode &&
        state.selectedNavigationKey !== NAV_KEYS.OVERVIEW
      ) {
        state.selectedNavigationKey = NAV_KEYS.OVERVIEW;
      }

      const layerReportId = buildLayerReportId(layerNum);
      const layerMsgIdx = state.messages.findIndex(
        (m) => m.id === layerReportId && m.type === 'layer_completed',
      );

      if (layerMsgIdx >= 0 && layerData.dimension_reports) {
        const layerMsg = state.messages[layerMsgIdx] as LayerCompletedMessage;
        if (!layerMsg.dimensionReports) {
          layerMsg.dimensionReports = {};
        }
        Object.assign(layerMsg.dimensionReports, layerData.dimension_reports);

        layerMsg.fullReportContent = formatDimensionReportsAsContent(
          layerMsg.dimensionReports,
        );
        const summary = calculateReportSummary(
          layerMsg.dimensionReports,
          layerMsg.dimensionSummaries,
        );
        layerMsg.summary.word_count = summary.word_count;
        layerMsg.summary.dimension_count = summary.dimension_count;
        if (summary.key_points.length > 0) {
          layerMsg.summary.key_points = summary.key_points;
        }

        if (layerData.dimension_knowledge_sources) {
          layerMsg.dimensionKnowledgeSources =
            layerMsg.dimensionKnowledgeSources ?? {};
          Object.assign(
            layerMsg.dimensionKnowledgeSources,
            layerData.dimension_knowledge_sources,
          );
        }
      }

      if (layerData.dimension_reports) {
        for (const dimKey of Object.keys(layerData.dimension_reports)) {
          const progressKey = buildDimensionProgressKey(layerNum, dimKey);
          state.dimensionProgress[progressKey] = {
            dimensionKey: dimKey,
            dimensionName: DIMENSION_NAMES[dimKey] || dimKey,
            layer: layerNum,
            status: 'completed' as DimensionStatus,
            wordCount: (layerData.dimension_reports[dimKey] || '').length,
            completedAt: new Date().toISOString(),
          };
        }
        state.executingDimensions = state.executingDimensions.filter(
          (k) => !k.startsWith(`${layerNum}_`),
        );
      }

      deriveUIStateInStore(state);
      break;
    }

    case 'layer_paused': {
      const pauseData = data as {
        layer?: number;
        phase?: string;
        layer_name?: string;
      };
      state.interruptInfo = pauseData;
      state.status = 'paused';
      deriveUIStateInStore(state);
      break;
    }

    case 'execution_resumed': {
      state.interruptInfo = undefined;
      state.status = 'planning';
      state.humanReviewEventId = null;
      state.pausedStage = null;
      state.humanReviewItems = [];
      state.isResolvingReview = false;
      state.humanReviewError = null;
      deriveUIStateInStore(state);
      break;
    }

    case 'tool_call': {
      const toolData = data as {
        tool_name?: string;
        tool_display_name?: string;
        description?: string;
        estimated_time?: number;
        stage?: string;
      };
      const toolName = toolData.tool_name || '';
      if (!toolName) return;

      state.toolStatuses[toolName] = {
        toolName,
        status: 'running',
        stage: toolData.stage,
        message: toolData.description,
      };

      state.processPanelTab = 'messages';
      state.isRightPanelExpanded = true;
      break;
    }

    case 'tool_progress': {
      const toolData = data as {
        tool_name?: string;
        stage?: string;
        progress?: number;
        message?: string;
      };
      const toolName = toolData.tool_name || '';
      if (!toolName) return;

      const existing = state.toolStatuses[toolName];
      if (!existing) return;

      existing.stage = toolData.stage || existing.stage;
      existing.progress = toolData.progress;
      existing.message = toolData.message;
      break;
    }

    case 'tool_result': {
      const toolData = data as {
        tool_name?: string;
        status?: string;
        summary?: string;
      };
      const toolName = toolData.tool_name || '';
      if (!toolName) return;

      const existing = state.toolStatuses[toolName];
      if (!existing) return;

      existing.status = toolData.status === 'error' ? 'error' : 'success';
      existing.summary = toolData.summary;
      break;
    }

    case 'tool_started': {
      const toolData = data as {
        tool_name?: string;
        tool_display_name?: string;
        description?: string;
        estimated_time?: number;
        status?: string;
        started_at?: string;
      };
      const toolName = toolData.tool_name || '';
      if (!toolName) return;

      const baseMsg = createBaseMessage('assistant');
      const newMessage: ToolStatusMessage = {
        ...baseMsg,
        id: `tool_${toolName}_${Date.now()}`,
        type: 'tool_status',
        toolName,
        toolDisplayName: toolData.tool_display_name || toolName,
        description: toolData.description || '',
        status: 'running',
        estimatedTime: toolData.estimated_time,
        startedAt: toolData.started_at,
      };
      state.messages.push(newMessage);

      state.toolStatuses[toolName] = {
        toolName,
        status: 'running',
        message: toolData.description,
      };
      break;
    }

    case 'tool_status': {
      const toolData = data as {
        tool_name?: string;
        status?: string;
        progress?: number;
        stage?: string;
        stage_message?: string;
        summary?: string;
        error?: string;
        completed_at?: string;
      };
      const toolName = toolData.tool_name || '';
      if (!toolName) return;

      const msgIdx = state.messages.findIndex(
        (m) =>
          m.type === 'tool_status' &&
          (m as ToolStatusMessage).toolName === toolName,
      );

      if (msgIdx >= 0) {
        const msg = state.messages[msgIdx] as ToolStatusMessage;
        msg.status =
          (toolData.status as ToolStatusMessage['status']) || msg.status;
        if (toolData.progress !== undefined) msg.progress = toolData.progress;
        if (toolData.stage) msg.stage = toolData.stage;
        if (toolData.stage_message) msg.stageMessage = toolData.stage_message;
        if (toolData.summary) msg.summary = toolData.summary;
        if (toolData.error) msg.error = toolData.error;
        if (toolData.completed_at) msg.completedAt = toolData.completed_at;
      }

      const existing = state.toolStatuses[toolName];
      if (existing) {
        existing.status =
          toolData.status === 'error'
            ? 'error'
            : toolData.status === 'success'
              ? 'success'
              : 'running';
        if (toolData.progress !== undefined)
          existing.progress = toolData.progress;
        if (toolData.stage) existing.stage = toolData.stage;
        if (toolData.stage_message) existing.message = toolData.stage_message;
        if (toolData.summary) existing.summary = toolData.summary;
      }
      break;
    }

    case 'gis_result': {
      const gisData = data as {
        dimensionKey?: string;
        dimensionName?: string;
        summary?: string;
        layers?: unknown[];
        mapOptions?: { center?: [number, number]; zoom?: number };
        analysisData?: {
          overallScore?: number;
          suitabilityLevel?: string;
          sensitivityClass?: string;
          recommendations?: string[];
        };
        pipeline_trace?: PipelineTrace;
      };
      const dimensionKey = gisData.dimensionKey || '';
      if (!dimensionKey) return;

      const baseMsg = createBaseMessage('assistant');
      const newMessage: GisResultMessage = {
        ...baseMsg,
        id: `gis_${dimensionKey}_${Date.now()}`,
        type: 'gis_result',
        dimensionKey,
        dimensionName: gisData.dimensionName || dimensionKey,
        summary: gisData.summary || '',
        layers: (gisData.layers as GisResultMessage['layers']) || [],
        mapOptions:
          gisData.mapOptions?.center && gisData.mapOptions?.zoom
            ? {
                center: gisData.mapOptions.center,
                zoom: gisData.mapOptions.zoom,
              }
            : undefined,
        analysisData: gisData.analysisData,
      };
      state.messages.push(newMessage);

      if (gisData.pipeline_trace) {
        state.pipelineTrace = gisData.pipeline_trace;
      }

      if (gisData.layers && Array.isArray(gisData.layers)) {
        const layerConfigs = gisData.layers.filter(Boolean) as GISLayerConfig[];
        if (layerConfigs.length > 0) {
          state.gisLayers[`result_${dimensionKey}`] = layerConfigs;
        }
      }

      const hadNoGisData = Object.keys(state.gisLayers).length === 0;
      if (hadNoGisData) {
        state.isRightPanelExpanded = true;
        state.processPanelTab = 'map';
      }
      state.gisGenerating = false;
      state.gisTriggerPending = false;
      break;
    }

    case 'ai_response_complete': {
      const aiData = data as { content?: string };
      const aiMessage = {
        id: `ai_${Date.now()}`,
        timestamp: new Date(),
        role: 'assistant' as const,
        type: 'text' as const,
        content: aiData.content || '',
      };
      state.messages.push(aiMessage);
      break;
    }

    case 'pause': {
      const pauseData = data as {
        current_layer?: number;
        checkpoint_id?: string;
        previous_layer?: number;
        message?: string;
        task_id?: string;
      };

      if (pauseData.task_id && !state.sessionId) {
        state.sessionId = pauseData.task_id;
      }

      state.previous_layer =
        pauseData.current_layer ||
        pauseData.previous_layer ||
        state.previous_layer;
      state.lastPauseLayer = pauseData.current_layer || pauseData.previous_layer || state.lastPauseLayer;
      state.status = 'paused';

      if (
        state.step_mode &&
        state.selectedNavigationKey !== NAV_KEYS.OVERVIEW
      ) {
        state.selectedNavigationKey = NAV_KEYS.OVERVIEW;
      }

      const layer = pauseData.current_layer || pauseData.previous_layer || 0;
      if (pauseData.checkpoint_id && layer > 0) {
        const existingCp = state.checkpoints.find((cp) => cp.layer === layer);
        if (!existingCp) {
          state.checkpoints.push({
            checkpoint_id: pauseData.checkpoint_id,
            layer: layer,
            timestamp: new Date().toISOString(),
            description: `Layer ${layer} checkpoint`,
            type: 'key',
            phase: state.phase,
          });
        }
      }

      deriveUIStateInStore(state);
      break;
    }

    case 'resumed': {
      state.interruptInfo = undefined;
      state.previous_layer = 0;
      state.status = 'planning';
      deriveUIStateInStore(state);
      break;
    }

    case 'revision_completed': {
      const revData = data as {
        layer?: number;
        revised_dimensions?: string[];
        previous_layer?: number;
      };

      state.previous_layer = revData.previous_layer || revData.layer || 0;
      state.status = 'paused';

      deriveUIStateInStore(state);
      break;
    }

    case 'checkpoint_saved': {
      const cpData = data as {
        checkpoint_id?: string;
        layer?: number;
        checkpoint_type?: string;
        phase?: string;
        description?: string;
        is_revision?: boolean;
        revised_dimensions?: string[];
      };

      const layer = cpData.layer || 0;
      const cpType: 'key' | 'regular' =
        cpData.checkpoint_type === 'key' ? 'key' : 'regular';

      const existingIndex = state.checkpoints.findIndex(
        (cp) => cp.layer === layer,
      );
      const newCheckpoint = {
        checkpoint_id: cpData.checkpoint_id || '',
        layer: layer,
        timestamp: new Date().toISOString(),
        description: cpData.description || `Checkpoint at layer ${layer}`,
        type: cpType,
        phase: cpData.phase,
        isRevision: cpData.is_revision || false,
        revisedDimensions: cpData.revised_dimensions,
      };

      if (existingIndex >= 0) {
        state.checkpoints[existingIndex] = {
          ...state.checkpoints[existingIndex],
          ...newCheckpoint,
        };
      } else if (cpData.checkpoint_id && layer > 0) {
        state.checkpoints.push(newCheckpoint);
      }
      break;
    }

    case 'rag_query': {
      const ragData = data as {
        dimension_key?: string;
        query?: string;
        layer?: number;
      };
      const dimKey = ragData.dimension_key || '';
      if (dimKey && ragData.query) {
        const fullKey = `${ragData.layer || 1}_${dimKey}`;
        state.dimensionRagSources[fullKey] = {
          query: ragData.query,
          documents: state.dimensionRagSources[fullKey]?.documents || [],
        };
      }
      break;
    }

    case 'rag_result': {
      const ragData = data as {
        dimension_key?: string;
        query?: string;
        query_generation_method?: string;
        retrieval_latency_ms?: number;
        total_results?: number;
        documents?: Array<{
          title?: string;
          snippet?: string;
          source?: string;
          score?: number;
          matched_query?: string;
          query?: string;
          chunk_id?: string;
        }>;
        layer?: number;
      };
      const dimKey = ragData.dimension_key || '';
      if (dimKey) {
        const fullKey = `${ragData.layer || 1}_${dimKey}`;
        const documents = (ragData.documents || []).map((doc) => ({
          title: doc.title || doc.source || '未知',
          snippet: doc.snippet || '',
          source: doc.source,
          score: doc.score,
          chunk_id: doc.chunk_id,
          matched_query: doc.matched_query || doc.query || '',
        }));
        state.dimensionRagSources[fullKey] = {
          query: ragData.query || '',
          documents,
        };
      }
      break;
    }

    case 'cascade_impact': {
      const cascadeData = data as {
        trigger_dim?: string;
        impacted_dimensions?: string[];
      };
      if (cascadeData.trigger_dim && cascadeData.impacted_dimensions) {
        state.cascadeChain = {
          trigger: cascadeData.trigger_dim,
          impacted: cascadeData.impacted_dimensions,
        };
        state.revisionCompletedKeys = [];
      }
      break;
    }

    case 'cascade_complete': {
      const ccData = data as { revised_dimensions?: string[] };
      state.cascadeChain = null;
      state.revisionCompletedKeys = [];
      if (state.status === 'revising') {
        state.status = 'paused';
      }
      if (ccData.revised_dimensions && ccData.revised_dimensions.length > 0) {
        const firstDim = ccData.revised_dimensions[0];
        const dimLayer = getDimensionLayer(firstDim);
        if (dimLayer) {
          state.selectedNavigationKey = NAV_KEYS.dim(`${dimLayer}_${firstDim}`);
        }
      }
      deriveUIStateInStore(state);
      break;
    }

    case 'state_sync': {
      const syncData = data as Record<string, unknown>;
      if (syncData.phase) state.phase = syncData.phase as string;
      if (syncData.current_wave)
        state.currentWave = syncData.current_wave as number;
      if (syncData.completed_dimensions) {
        const completedData = syncData.completed_dimensions as Record<
          string,
          string[]
        >;
        if (completedData.layer1)
          state.completedDimensions.layer1 = completedData.layer1;
        if (completedData.layer2)
          state.completedDimensions.layer2 = completedData.layer2;
        if (completedData.layer3)
          state.completedDimensions.layer3 = completedData.layer3;
      }
      if (syncData.interrupt_info !== undefined) {
        const interruptInfo = syncData.interrupt_info as PlanningState['interruptInfo'];
        state.interruptInfo = interruptInfo;
        state.humanReviewEventId = interruptInfo?.event_id || null;
        state.pausedStage = interruptInfo?.paused_stage || null;
        state.humanReviewItems = interruptInfo?.items || [];
      }
      if (syncData.previous_layer !== undefined)
        state.previous_layer = syncData.previous_layer as number;
      deriveUIStateInStore(state);
      break;
    }

    case 'gis_layer_update': {
      const gisUpdateData = data as {
        layer?: number;
        dimensionKey?: string;
        layers?: unknown[];
      };
      const key = `${gisUpdateData.layer}_${gisUpdateData.dimensionKey}`;
      if (gisUpdateData.layers) {
        state.gisLayers[key] = gisUpdateData.layers as GISLayerConfig[];
        const layers = gisUpdateData.layers as GISLayerConfig[];
        const detected = new Set(state.uploadedGisDataTypes);
        for (const l of layers) {
          if (l.layerType === 'boundary') detected.add('boundary');
          else if (l.layerType === 'function_zone') detected.add('landuse_current');
        }
        state.uploadedGisDataTypes = [...detected];
      }
      const hadNoGisData = Object.keys(state.gisLayers).length === 0;
      if (hadNoGisData) {
        state.isRightPanelExpanded = true;
        state.processPanelTab = 'map';
      }
      if (!state.gisGenerating) state.gisGenerating = true;
      state.gisTriggerPending = false;
      break;
    }

    case 'rag_config_updated': {
      const ragData = data as {
        rag_layer_config?: Record<number, boolean>;
      };
      if (ragData.rag_layer_config) {
        state.ragLayerConfig = ragData.rag_layer_config;
      }
      break;
    }

    case 'step_mode_updated': {
      const stepData = data as {
        step_mode?: boolean;
      };
      if (stepData.step_mode !== undefined) {
        state.step_mode = stepData.step_mode;
      }
      break;
    }

    case 'human_review_paused': {
      const hitlData = data as {
        event_id?: string;
        channel?: string;
        items?: HumanReviewItem[];
        paused_stage?: string;
        reason?: string;
        item_count?: number;
      };
      if (!state.humanReviewEventId) {
        state.interruptInfo = {
          event_id: hitlData.event_id,
          channel: hitlData.channel || 'post_l3_review',
          reason: hitlData.reason || 'human_review_required',
          paused_stage: hitlData.paused_stage,
          items: hitlData.items || [],
        };
        state.humanReviewEventId = hitlData.event_id || null;
        state.pausedStage = hitlData.paused_stage || null;
        state.humanReviewItems = hitlData.items || state.humanReviewItems;
        state.humanReviewError = null;
        state.status = 'paused';
        deriveUIStateInStore(state);
      }
      break;
    }
  }
}
