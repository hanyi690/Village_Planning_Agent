# Graph Report - graphify-tmp-staging\frontend  (2026-08-07)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 720 nodes · 1808 edges · 30 communities (26 shown, 4 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 16 edges (avg confidence: 0.69)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7863f666`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- usePlanningStore
- types.ts
- planning/types/index.ts
- test-gis/page.tsx
- types/planning.ts
- constants/index.ts
- utils/message-helpers.ts
- message-types.ts
- planning-context.tsx
- planningStore.ts
- MapView.tsx
- events.ts
- FileViewerSidebar.tsx
- ExportDialog.tsx
- components/index.ts
- TracePanel.tsx
- GISLayerConfig
- dimensions.ts
- useHandlers.ts
- useStreamingText
- config/index.ts
- ThinkingIndicator.tsx
- CascadePanel.tsx
- GisResultCard.tsx
- useStreamingRender.ts
- report-parser.ts
- StandardLayersPanel.tsx
- ChatInput.tsx
- layout.tsx

## God Nodes (most connected - your core abstractions)
1. `usePlanningStore` - 84 edges
2. `Message` - 20 edges
3. `usePlanningActions()` - 18 edges
4. `GISLayerConfig` - 17 edges
5. `PlanningState` - 16 edges
6. `planningApi` - 14 edges
7. `getDimensionName()` - 13 edges
8. `LayerCompletedMessage` - 13 edges
9. `PlanningActions` - 12 edges
10. `DimensionProgressItem` - 12 edges

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

## Communities (30 total, 4 thin omitted)

### Community 0 - "usePlanningStore"
Cohesion: 0.08
Nodes (70): FileViewerWrapper(), GisResultCard(), Dashboard(), AppHeader(), AppHeaderProps, FocusArea, getStatusColor(), LayerNav() (+62 more)

### Community 1 - "types.ts"
Cohesion: 0.07
Nodes (59): apiRequest(), createApiError(), extractErrorMessage(), dataApi, api, ApiError, APIResponse, ArtifactListResponse (+51 more)

### Community 2 - "planning/types/index.ts"
Cohesion: 0.08
Nodes (51): LayerReportMessageProps, MemoizedMessageBubble, MessageBubble(), MessageBubbleProps, MessageContent(), MessageContentProps, renderDimensionReportMessage(), renderProgressMessage() (+43 more)

### Community 3 - "test-gis/page.tsx"
Cohesion: 0.06
Nodes (39): BasemapType, DEFAULT_LAYER_VISIBILITY, LayerVisibility, MapControls(), MapControlsProps, TOOL_GROUPS, ToolConfig, ToolGroup (+31 more)

### Community 4 - "types/planning.ts"
Cohesion: 0.06
Nodes (36): AxisEditorProps, FacilityEditorProps, PlanningSchemeEditorProps, ZoneEditor(), ZoneEditorProps, TestResultPanelProps, JINTIAN_AXES, JINTIAN_CENTER (+28 more)

### Community 5 - "constants/index.ts"
Cohesion: 0.05
Nodes (35): MemoizedToolStatusPanel, SimpleToolStatus, STATUS_COLORS, ToolStatusPanel(), ToolStatusPanelProps, containerVariants, FileTags, FileTagsProps (+27 more)

### Community 6 - "utils/message-helpers.ts"
Cohesion: 0.10
Nodes (27): CheckpointMarker(), CheckpointMarkerProps, GIS_STAGES, GisStageProgress(), STATUS_STYLES, ToolStatusCard(), ToolStatusCardProps, getToolIconFA() (+19 more)

### Community 7 - "message-types.ts"
Cohesion: 0.12
Nodes (32): ActionButton, BaseMessage, ConversationState, DimensionProgressItem, DimensionStatus, KnowledgeReference, Message, MessageRole (+24 more)

### Community 8 - "planning-context.tsx"
Cohesion: 0.10
Nodes (19): RetrievedChunk, PARAM_MAPPING, ParamMapping, PLANNING_DEFAULTS, PlanningDefaults, useSessionRestore(), UseSessionRestoreOptions, PlanningProviderProps (+11 more)

### Community 9 - "planningStore.ts"
Cohesion: 0.11
Nodes (22): planningApi, getLayerPhase(), BatchEvent, UseSSEConnectionOptions, CascadeChain, CompletedDimensions, deriveCompletedDimensions(), deriveUIStateInStore() (+14 more)

### Community 10 - "MapView.tsx"
Cohesion: 0.15
Nodes (18): buildMatchExpression(), DEFAULT_CENTER, extractCoords(), getBoundsFromGeoJSON(), getTiandituUrls(), hasFeatureColors(), LAYER_PRIORITY, MapView() (+10 more)

### Community 11 - "events.ts"
Cohesion: 0.11
Nodes (18): CheckpointData, DimensionCompleteData, DimensionDeltaData, DimensionStartData, DimensionStructuredSummary, ErrorData, GisLayerUpdateEvent, LayerCompletedData (+10 more)

### Community 12 - "FileViewerSidebar.tsx"
Cohesion: 0.16
Nodes (10): FileViewerSidebar(), FileViewerSidebarProps, KnowledgeSliceCardProps, ImagePreviewProps, MarkdownRenderer(), MarkdownRendererProps, preprocessMathInHtml(), DEFAULT_IMAGE_FORMAT (+2 more)

### Community 13 - "ExportDialog.tsx"
Cohesion: 0.14
Nodes (11): ExportDialog, ExportDialogProps, ExportMode, FORMAT_OPTIONS, LAYER_OPTIONS, LayerFormat, LayerOption, MODE_OPTIONS (+3 more)

### Community 14 - "components/index.ts"
Cohesion: 0.21
Nodes (10): LayerTogglePanel(), LayerTogglePanelProps, LegendPanel(), LegendPanelProps, POSITION_STYLES, SingleLayerLegend(), getLegendForLayerType(), LAYER_TYPE_LABELS (+2 more)

### Community 15 - "TracePanel.tsx"
Cohesion: 0.13
Nodes (6): ConflictTrace, KGTrace, MIPTrace, ParseTrace, PipelineTrace, ValidationLoopTrace

### Community 16 - "GISLayerConfig"
Cohesion: 0.19
Nodes (7): DebugPanelProps, enhancePOIData(), inferFacilityType(), TestLayerState, PLANNING_COLORS, GeoJsonFeatureCollection, GISLayerConfig

### Community 17 - "dimensions.ts"
Cohesion: 0.26
Nodes (11): CompletedLayers, LayerProgressHistory, LayerProgressSnapshot, MemoizedProgressPanel, ProgressPanel(), ProgressPanelProps, STATUS_CONFIG, getDimensionConfigsByLayer() (+3 more)

### Community 18 - "useHandlers.ts"
Cohesion: 0.24
Nodes (10): KnowledgeSourceItem, RAGRetrievalLog, DimensionCard(), DimensionCardProps, STATUS_COLORS, getDimensionName(), LayerReportData, usePlanningHandlers() (+2 more)

### Community 19 - "useStreamingText"
Cohesion: 0.22
Nodes (8): StreamingText(), StreamingTextProps, StreamingTextWithControls(), useStreamingText(), UseStreamingTextOptions, UseStreamingTextReturn, mockCancelRaf, mockRaf

### Community 20 - "config/index.ts"
Cohesion: 0.31
Nodes (9): DIMENSION_ICONS, DIMENSION_NAMES, convertToBackendParams(), getParamMapping(), getPlanningDefaults(), PARAM_MAPPING, ParamMapping, PLANNING_DEFAULTS (+1 more)

### Community 21 - "ThinkingIndicator.tsx"
Cohesion: 0.20
Nodes (4): SIZE_CONFIG, STATE_CONFIG, ThinkingIndicatorProps, ThinkingState

### Community 22 - "CascadePanel.tsx"
Cohesion: 0.36
Nodes (7): CascadePanel(), CascadePanelProps, computeLayout(), LayoutResult, LayoutType, truncateLabel(), getDimensionLayer()

### Community 23 - "GisResultCard.tsx"
Cohesion: 0.38
Nodes (3): activeMaps, GisResultCardProps, StageReportPanel()

### Community 24 - "useStreamingRender.ts"
Cohesion: 0.40
Nodes (4): DimensionBuffer, StreamingRenderOptions, useStreamingRender(), UseStreamingRenderReturn

## Knowledge Gaps
- **157 isolated node(s):** `mockFetch`, `mockRaf`, `mockCancelRaf`, `metadata`, `LayerVisibility` (+152 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `usePlanningStore` connect `usePlanningStore` to `planning/types/index.ts`, `test-gis/page.tsx`, `planning-context.tsx`, `planningStore.ts`, `useHandlers.ts`, `GisResultCard.tsx`?**
  _High betweenness centrality (0.118) - this node is a cross-community bridge._
- **Why does `GISLayerConfig` connect `GISLayerConfig` to `usePlanningStore`, `test-gis/page.tsx`, `constants/index.ts`, `message-types.ts`, `planningStore.ts`, `MapView.tsx`, `components/index.ts`, `GisResultCard.tsx`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Why does `planningApi` connect `planningStore.ts` to `usePlanningStore`, `types.ts`, `planning-context.tsx`, `ExportDialog.tsx`, `useHandlers.ts`?**
  _High betweenness centrality (0.018) - this node is a cross-community bridge._
- **What connects `mockFetch`, `mockRaf`, `mockCancelRaf` to the rest of the system?**
  _157 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `usePlanningStore` be split into smaller, more focused modules?**
  _Cohesion score 0.07572637840311142 - nodes in this community are weakly interconnected._
- **Should `types.ts` be split into smaller, more focused modules?**
  _Cohesion score 0.0673903211216644 - nodes in this community are weakly interconnected._
- **Should `planning/types/index.ts` be split into smaller, more focused modules?**
  _Cohesion score 0.07932692307692307 - nodes in this community are weakly interconnected._