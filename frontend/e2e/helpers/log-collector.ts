/**
 * Log Collector & Watchdog for E2E tests.
 *
 * Watchdog: Polls backend status API every 30s to detect:
 *   - Progress stagnation (3+ polls with no change)
 *   - Execution errors (execution_error field)
 *   - Phase/status transitions
 *
 * LogCollector: Tracks pipeline stages from SSE events.
 */

import { BACKEND_URL } from '../fixtures/village-data';

// ── Types ────────────────────────────────────────────────────────────

export interface StatusSnapshot {
  timestamp: number;
  status: string;
  phase: string;
  current_layer: number;
  progress: number;
  execution_error?: string;
}

export interface StatusTransition {
  from: string;
  to: string;
  timestamp: number;
  elapsedMs: number;
}

export interface PipelineStage {
  name: string;
  timestamp: number;
  source: 'sse' | 'status';
  detail?: string;
}

export interface PipelineSummary {
  totalDurationMs: number;
  stages: { name: string; startMs: number; detail?: string }[];
  transitions: StatusTransition[];
  stagnationWarnings: string[];
  errors: string[];
}

export interface LogSummary {
  pipelineStages: string[];
  errors: string[];
  stagnationWarnings: string[];
  transitions: StatusTransition[];
}

export interface WatchdogOptions {
  pollIntervalMs?: number;
  stagnationThreshold?: number;
  maxTimeoutMs?: number;
}

// ── Watchdog ─────────────────────────────────────────────────────────

const TOOL_STAGE_MAP: Record<string, string> = {
  parse_planning_text: 'PARSE意图解析',
  build_knowledge_graph: 'KG构建',
  query_knowledge_graph: 'KG查询',
  detect_conflicts: '冲突检测',
  allocate_zones: '分区分配',
  generate_layout: '布局生成',
  validate_layout: '布局验证',
  measure_divergence: '偏离度测量',
  fetch_gis_data: 'GIS数据获取',
  calculate_gis_coverage: '覆盖率计算',
  analyze_accessibility: '可达性分析',
  search_poi: 'POI搜索',
};

export class Watchdog {
  private pollIntervalMs: number;
  private stagnationThreshold: number;
  private maxTimeoutMs: number;
  private statusHistory: StatusSnapshot[] = [];
  private errors: string[] = [];
  private stagnationWarnings: string[] = [];
  private pipelineStages: PipelineStage[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;
  private sessionId: string = '';
  private startMs: number = 0;
  private lastProgress: number = -1;
  private stagnationCount: number = 0;
  private stopped: boolean = false;

  constructor(options?: WatchdogOptions) {
    this.pollIntervalMs = options?.pollIntervalMs ?? 30000;
    this.stagnationThreshold = options?.stagnationThreshold ?? 3;
    this.maxTimeoutMs = options?.maxTimeoutMs ?? 2400000; // 40 min
  }

  /** Start monitoring. Polls status API in the background. */
  start(sessionId: string): void {
    this.sessionId = sessionId;
    this.startMs = Date.now();
    this.stopped = false;
    this.statusHistory = [];
    this.errors = [];
    this.stagnationWarnings = [];
    this.pipelineStages = [];
    this.lastProgress = -1;
    this.stagnationCount = 0;

    console.log(`[Watchdog] Started for session ${sessionId} (poll=${this.pollIntervalMs}ms, max=${this.maxTimeoutMs}ms)`);

    // Poll immediately, then on interval
    this._poll();
    this.timer = setInterval(() => this._poll(), this.pollIntervalMs);
  }

  /** Stop monitoring. */
  stop(): void {
    this.stopped = true;
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    console.log(`[Watchdog] Stopped. Duration=${Date.now() - this.startMs}ms, errors=${this.errors.length}, stagnations=${this.stagnationWarnings.length}`);
  }

  /** Record an SSE event as a pipeline stage. */
  recordSseEvent(eventType: string, data?: any): void {
    if (this.stopped) return;

    const timestamp = Date.now();

    // Map SSE event types to pipeline stages
    if (eventType === 'tool_started' && data?.tool_name) {
      const stageName = TOOL_STAGE_MAP[data.tool_name] || data.tool_name;
      this.pipelineStages.push({ name: stageName, timestamp, source: 'sse', detail: data.tool_name });
      console.log(`[Watchdog] Pipeline: ${stageName} (tool: ${data.tool_name})`);
    } else if (eventType === 'gis_layer_update') {
      const layerType = data?.layers?.[0]?.layerType || 'unknown';
      this.pipelineStages.push({ name: `层渲染: ${layerType}`, timestamp, source: 'sse' });
      console.log(`[Watchdog] GIS layer update: ${layerType}`);
    } else if (eventType === 'gis_result') {
      const layerCount = data?.layers?.length ?? 0;
      this.pipelineStages.push({ name: 'GIS完成', timestamp, source: 'sse', detail: `${layerCount} layers` });
      console.log(`[Watchdog] GIS result: ${layerCount} layers`);
    } else if (eventType === 'dimension_complete') {
      const dimKey = data?.dimension_key || 'unknown';
      this.pipelineStages.push({ name: `维度完成: ${dimKey}`, timestamp, source: 'sse' });
    } else if (eventType === 'layer_completed') {
      const layer = data?.layer ?? '?';
      this.pipelineStages.push({ name: `L${layer}完成`, timestamp, source: 'sse' });
      console.log(`[Watchdog] Layer ${layer} completed`);
    }
  }

  /** Any errors detected? */
  hasErrors(): boolean {
    return this.errors.length > 0;
  }

  /** Get error list. */
  getErrors(): string[] {
    return [...this.errors];
  }

  /** Get status transition history. */
  getStatusTransitions(): StatusTransition[] {
    const transitions: StatusTransition[] = [];
    for (let i = 1; i < this.statusHistory.length; i++) {
      const prev = this.statusHistory[i - 1];
      const curr = this.statusHistory[i];
      const key = `${prev.status}:${prev.phase}`;
      const currKey = `${curr.status}:${curr.phase}`;
      if (key !== currKey) {
        transitions.push({
          from: key,
          to: currKey,
          timestamp: curr.timestamp,
          elapsedMs: curr.timestamp - prev.timestamp,
        });
      }
    }
    return transitions;
  }

  /** Get pipeline summary. */
  getPipelineSummary(): PipelineSummary {
    return {
      totalDurationMs: this.stopped ? Date.now() - this.startMs : Date.now() - this.startMs,
      stages: this.pipelineStages.map((s) => ({ name: s.name, startMs: s.timestamp - this.startMs, detail: s.detail })),
      transitions: this.getStatusTransitions(),
      stagnationWarnings: [...this.stagnationWarnings],
      errors: [...this.errors],
    };
  }

  /** Is progress stagnant? */
  isStagnant(): boolean {
    return this.stagnationCount >= this.stagnationThreshold;
  }

  /** Get status history. */
  getStatusHistory(): StatusSnapshot[] {
    return [...this.statusHistory];
  }

  // ── Private ──

  private async _poll(): Promise<void> {
    if (this.stopped) return;

    const elapsed = Date.now() - this.startMs;
    if (elapsed > this.maxTimeoutMs) {
      this.errors.push(`Watchdog timeout: exceeded ${this.maxTimeoutMs}ms`);
      console.error(`[Watchdog] TIMEOUT after ${elapsed}ms`);
      this.stop();
      return;
    }

    try {
      const resp = await fetch(`${BACKEND_URL}/api/sessions/${this.sessionId}/status`);
      if (!resp.ok) {
        console.warn(`[Watchdog] Status API returned ${resp.status}`);
        return;
      }

      const data = await resp.json();
      const snapshot: StatusSnapshot = {
        timestamp: Date.now(),
        status: data.status,
        phase: data.phase,
        current_layer: data.current_layer,
        progress: data.progress,
        execution_error: data.execution_error,
      };

      // Check for execution errors
      if (snapshot.execution_error) {
        this.errors.push(`Execution error: ${snapshot.execution_error}`);
        console.error(`[Watchdog] EXECUTION ERROR: ${snapshot.execution_error}`);
      }

      // Check for progress stagnation
      if (snapshot.progress === this.lastProgress && snapshot.status !== 'completed') {
        this.stagnationCount++;
        if (this.stagnationCount === this.stagnationThreshold) {
          const warn = `Progress stagnant at ${snapshot.progress}% for ${this.stagnationThreshold * this.pollIntervalMs / 1000}s (status=${snapshot.status}, phase=${snapshot.phase})`;
          this.stagnationWarnings.push(warn);
          console.warn(`[Watchdog] STAGNATION: ${warn}`);
        }
      } else {
        this.stagnationCount = 0;
      }
      this.lastProgress = snapshot.progress;

      // Record status transition
      const prev = this.statusHistory[this.statusHistory.length - 1];
      if (!prev || prev.status !== snapshot.status || prev.phase !== snapshot.phase) {
        const prevKey = prev ? `${prev.status}/${prev.phase}` : 'init';
        console.log(`[Watchdog] Transition: ${prevKey} → ${snapshot.status}/${snapshot.phase} (progress=${snapshot.progress}%, layer=${snapshot.current_layer})`);
      }

      this.statusHistory.push(snapshot);

      // Record as pipeline stage if status changed
      if (snapshot.status === 'completed' && (!prev || prev.status !== 'completed')) {
        this.pipelineStages.push({ name: '规划完成', timestamp: snapshot.timestamp, source: 'status' });
        console.log(`[Watchdog] Planning completed (progress=${snapshot.progress}%)`);
      }

      // Auto-stop if completed
      if (snapshot.status === 'completed' && this.stagnationCount === 0) {
        // Don't stop yet — GIS may still be triggered after completion
      }
    } catch (err) {
      console.warn(`[Watchdog] Poll failed: ${(err as Error).message}`);
    }
  }
}

// ── LogCollector ──────────────────────────────────────────────────────

export class LogCollector {
  private stages: PipelineStage[] = [];
  private errors: string[] = [];

  /** Add a pipeline stage. */
  addStage(name: string, source: 'sse' | 'status', detail?: string): void {
    this.stages.push({ name, timestamp: Date.now(), source, detail });
    console.log(`[LogCollector] Stage: ${name}${detail ? ` (${detail})` : ''}`);
  }

  /** Add an error. */
  addError(message: string): void {
    this.errors.push(message);
    console.error(`[LogCollector] Error: ${message}`);
  }

  /** Get all pipeline stages. */
  getPipelineStages(): string[] {
    return this.stages.map((s) => s.name);
  }

  /** Any errors? */
  hasErrors(): boolean {
    return this.errors.length > 0;
  }

  /** Get log summary. */
  getSummary(): LogSummary {
    return {
      pipelineStages: this.stages.map((s) => s.name),
      errors: [...this.errors],
      stagnationWarnings: [],
      transitions: [],
    };
  }

  /** Get raw stages. */
  getStages(): PipelineStage[] {
    return [...this.stages];
  }
}

// ── Result Saver ──────────────────────────────────────────────────────

import * as fs from 'fs/promises';
import * as path from 'path';

const E2E_OUTPUT_BASE = 'F:/project/Village_Planning_Agent/docs/gis/output/e2e';

export interface TestResultsToSave {
  gisLayerConfigs?: any[];
  pipelineReport?: any;
  watchdogSummary?: PipelineSummary;
  sseEvents?: any[];
  statusHistory?: StatusSnapshot[];
  layers?: Record<string, any>;
}

/** Save all test results to the output directory. */
export async function saveTestResults(sessionId: string, results: TestResultsToSave): Promise<string> {
  const outputDir = path.join(E2E_OUTPUT_BASE, sessionId);
  const layersDir = path.join(outputDir, 'layers');

  await fs.mkdir(layersDir, { recursive: true });

  const writes: Promise<void>[] = [];

  if (results.gisLayerConfigs) {
    writes.push(
      fs.writeFile(path.join(outputDir, 'gis_layer_configs.json'), JSON.stringify(results.gisLayerConfigs, null, 2), 'utf-8'),
    );
  }

  if (results.pipelineReport) {
    writes.push(
      fs.writeFile(path.join(outputDir, 'pipeline_report.json'), JSON.stringify(results.pipelineReport, null, 2), 'utf-8'),
    );
  }

  if (results.watchdogSummary) {
    writes.push(
      fs.writeFile(path.join(outputDir, 'watchdog_summary.json'), JSON.stringify(results.watchdogSummary, null, 2), 'utf-8'),
    );
  }

  if (results.sseEvents) {
    writes.push(
      fs.writeFile(path.join(outputDir, 'sse_events.json'), JSON.stringify(results.sseEvents, null, 2), 'utf-8'),
    );
  }

  if (results.statusHistory) {
    writes.push(
      fs.writeFile(path.join(outputDir, 'status_history.json'), JSON.stringify(results.statusHistory, null, 2), 'utf-8'),
    );
  }

  // Save each layer type as separate GeoJSON
  if (results.layers) {
    for (const [layerType, geojson] of Object.entries(results.layers)) {
      writes.push(
        fs.writeFile(path.join(layersDir, `${layerType}.geojson`), JSON.stringify(geojson, null, 2), 'utf-8'),
      );
    }
  }

  await Promise.all(writes);
  console.log(`[saveTestResults] Saved to ${outputDir}`);
  return outputDir;
}
