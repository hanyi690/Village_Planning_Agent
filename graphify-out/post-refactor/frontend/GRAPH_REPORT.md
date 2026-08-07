# Graph Report - C:\Users\24957\AppData\Local\Temp\opencode\gfx-frontend  (2026-08-08)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 731 nodes · 1851 edges · 27 communities (23 shown, 4 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 16 edges (avg confidence: 0.69)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ecc7e2d0`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25

## God Nodes (most connected - your core abstractions)
1. `usePlanningStore` - 84 edges
2. `PlanningState` - 21 edges
3. `Message` - 20 edges
4. `GISLayerConfig` - 19 edges
5. `usePlanningActions()` - 18 edges
6. `PlanningActions` - 15 edges
7. `planningApi` - 14 edges
8. `getDimensionName()` - 13 edges
9. `LayerCompletedMessage` - 13 edges
10. `getDimensionsByLayer()` - 12 edges

## Surprising Connections (you probably didn't know these)
- `DebugPanelProps` --references--> `GISLayerConfig`  [EXTRACTED]
  app/test-gis/components/DebugPanel.tsx → types/message/message-types.ts
- `GisTestSuiteState` --references--> `GISLayerConfig`  [EXTRACTED]
  app/test-gis/hooks/useGisTestSuite.ts → types/message/message-types.ts
- `useGisTestSuite()` --calls--> `useGisLayers()`  [EXTRACTED]
  app/test-gis/hooks/useGisTestSuite.ts → features/planning/hooks/useSelectors.ts
- `TestLayerState` --references--> `GISLayerConfig`  [EXTRACTED]
  app/test-gis/hooks/useTestLayers.ts → types/message/message-types.ts
- `TestGISPageContent()` --calls--> `usePlanningStore`  [EXTRACTED]
  app/test-gis/page.tsx → features/planning/store/planningStore.ts

## Import Cycles
- 4-file cycle: `features/planning/hooks/index.ts -> features/planning/hooks/useApprovalActions.ts -> features/planning/store/index.ts -> features/planning/store/planning-context.tsx -> features/planning/hooks/index.ts`

## Communities (27 total, 4 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (72): FileViewerWrapper(), GisResultCard(), Dashboard(), AppHeader(), AppHeaderProps, FocusArea, getStatusColor(), LayerNav() (+64 more)

### Community 1 - "Community 1"
Cohesion: 0.07
Nodes (56): LayerReportMessageProps, MemoizedMessageBubble, MessageBubble(), MessageBubbleProps, MessageContent(), MessageContentProps, renderDimensionReportMessage(), renderProgressMessage() (+48 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (42): RetrievedChunk, CheckpointMarker(), CheckpointMarkerProps, DIMENSION_NAMES, PARAM_MAPPING, ParamMapping, PLANNING_DEFAULTS, PlanningDefaults (+34 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (41): DebugPanelProps, enhancePOIData(), inferFacilityType(), TestLayerState, ChatInputProps, DEMO_FEEDBACKS, LayerTogglePanel(), LayerTogglePanelProps (+33 more)

### Community 4 - "Community 4"
Cohesion: 0.06
Nodes (36): AxisEditorProps, FacilityEditorProps, PlanningSchemeEditorProps, ZoneEditor(), ZoneEditorProps, TestResultPanelProps, JINTIAN_AXES, JINTIAN_CENTER (+28 more)

### Community 5 - "Community 5"
Cohesion: 0.06
Nodes (38): BasemapType, DEFAULT_LAYER_VISIBILITY, LayerVisibility, MapControls(), MapControlsProps, TOOL_GROUPS, ToolConfig, ToolGroup (+30 more)

### Community 6 - "Community 6"
Cohesion: 0.10
Nodes (42): api, ArtifactListResponse, ArtifactRef, ArtifactRefResponse, ArtifactResponse, ArtifactType, BackendEmbeddedImage, BackendFileUploadResponse (+34 more)

### Community 7 - "Community 7"
Cohesion: 0.08
Nodes (34): CascadePanel(), CascadePanelProps, computeLayout(), LayoutResult, LayoutType, truncateLabel(), CompletedLayers, LayerProgressHistory (+26 more)

### Community 8 - "Community 8"
Cohesion: 0.12
Nodes (32): ActionButton, BaseMessage, ConversationState, DimensionProgressItem, DimensionStatus, KnowledgeReference, Message, MessageRole (+24 more)

### Community 9 - "Community 9"
Cohesion: 0.08
Nodes (17): FileViewerSidebar(), FileViewerSidebarProps, activeMaps, GisResultCardProps, KnowledgeSliceCardProps, SIZE_CONFIG, STATE_CONFIG, ThinkingIndicatorProps (+9 more)

### Community 10 - "Community 10"
Cohesion: 0.13
Nodes (21): VillageInfo, VillageSession, VillageInputData, LayerPhase, NavigationKey, Reports, createGisActions(), StoreSet (+13 more)

### Community 11 - "Community 11"
Cohesion: 0.11
Nodes (14): AgentPhaseValue, DISABLE_INPUT_STATUSES, IMAGE_EXTENSIONS, isInputDisabled(), LAYER_ID_MAP, LAYER_LABEL_MAP, LAYER_OPTIONS, LAYER_OPTIONS_ARRAY (+6 more)

### Community 12 - "Community 12"
Cohesion: 0.11
Nodes (18): CheckpointData, DimensionCompleteData, DimensionDeltaData, DimensionStartData, DimensionStructuredSummary, ErrorData, GisLayerUpdateEvent, LayerCompletedData (+10 more)

### Community 13 - "Community 13"
Cohesion: 0.14
Nodes (11): ExportDialog, ExportDialogProps, ExportMode, FORMAT_OPTIONS, LAYER_OPTIONS, LayerFormat, LayerOption, MODE_OPTIONS (+3 more)

### Community 14 - "Community 14"
Cohesion: 0.13
Nodes (6): ConflictTrace, KGTrace, MIPTrace, ParseTrace, PipelineTrace, ValidationLoopTrace

### Community 15 - "Community 15"
Cohesion: 0.21
Nodes (9): apiRequest(), createApiError(), extractErrorMessage(), dataApi, ApiError, APIResponse, CrossSessionReport, DimensionVersion (+1 more)

### Community 16 - "Community 16"
Cohesion: 0.22
Nodes (9): planningApi, KnowledgeSourceItem, PlanningTextDocument, PlanningTextVersion, RAGRetrievalLog, PlanningTextViewer, PlanningTextViewerProps, LayerReportData (+1 more)

### Community 17 - "Community 17"
Cohesion: 0.22
Nodes (8): StreamingText(), StreamingTextProps, StreamingTextWithControls(), useStreamingText(), UseStreamingTextOptions, UseStreamingTextReturn, mockCancelRaf, mockRaf

### Community 18 - "Community 18"
Cohesion: 0.18
Nodes (10): containerVariants, FileTags, FileTagsProps, FileType, InputField, InputFieldProps, itemVariants, UploadedFileInfo (+2 more)

### Community 19 - "Community 19"
Cohesion: 0.39
Nodes (7): AgentPhase, getLayerPhase(), CompletedDimensions, deriveCompletedDimensions(), deriveUIStateInStore(), phaseToLayer(), shallowEqualCompletedDimensions()

### Community 20 - "Community 20"
Cohesion: 0.33
Nodes (6): MemoizedToolStatusPanel, SimpleToolStatus, STATUS_COLORS, ToolStatusPanel(), ToolStatusPanelProps, getToolIconEmoji()

### Community 21 - "Community 21"
Cohesion: 0.40
Nodes (4): DimensionBuffer, StreamingRenderOptions, useStreamingRender(), UseStreamingRenderReturn

## Knowledge Gaps
- **159 isolated node(s):** `mockFetch`, `mockRaf`, `mockCancelRaf`, `metadata`, `LayerVisibility` (+154 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `usePlanningStore` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 5`, `Community 9`, `Community 10`, `Community 16`?**
  _High betweenness centrality (0.115) - this node is a cross-community bridge._
- **Why does `GISLayerConfig` connect `Community 3` to `Community 0`, `Community 2`, `Community 5`, `Community 8`, `Community 9`, `Community 10`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Why does `planningApi` connect `Community 16` to `Community 0`, `Community 2`, `Community 3`, `Community 6`, `Community 10`, `Community 13`?**
  _High betweenness centrality (0.018) - this node is a cross-community bridge._
- **What connects `mockFetch`, `mockRaf`, `mockCancelRaf` to the rest of the system?**
  _159 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.07368421052631578 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.07002012072434607 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.06293706293706294 - nodes in this community are weakly interconnected._