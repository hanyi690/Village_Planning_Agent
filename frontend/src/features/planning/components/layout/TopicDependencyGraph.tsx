'use client';

import { useMemo, useState } from 'react';
import type {
  PlanningDependencyEdge,
  PlanningDependencyGraphResponse,
  PlanningDependencyNode,
} from '../../api/types';
import { LAYER_VALUE_MAP, NAV_KEYS } from '../../constants';

type GraphFilter = 'all' | 'selected' | 'pending';

interface TopicDependencyGraphProps {
  graph: PlanningDependencyGraphResponse | null;
  graphStatus?: 'loading' | 'error';
  reports: Partial<Record<'layer1' | 'layer2' | 'layer3', Record<string, string>>>;
  dimensionProgress: Record<string, { status?: string }>;
  executingDimensions: Set<string>;
  selectedNavigationKey: string;
  onSelectDimension: (navigationKey: string) => void;
}

const NODE_WIDTH = 238;
const NODE_HEIGHT = 34;
const COLUMN_X: Record<1 | 2 | 3, number> = { 1: 28, 2: 346, 3: 664 };
const ROW_GAP = 10;

function nodeNavigationKey(node: PlanningDependencyNode): string {
  return NAV_KEYS.dim(`${node.layer}_${node.key}`);
}

function isSelectedNode(node: PlanningDependencyNode, selectedNavigationKey: string): boolean {
  return nodeNavigationKey(node) === selectedNavigationKey;
}

function shortLabel(label: string): string {
  return label.length > 15 ? `${label.slice(0, 15)}…` : label;
}

export function TopicDependencyGraph({
  graph,
  graphStatus = 'loading',
  reports,
  dimensionProgress,
  executingDimensions,
  selectedNavigationKey,
  onSelectDimension,
}: TopicDependencyGraphProps) {
  const [filter, setFilter] = useState<GraphFilter>('all');

  const statusByKey = useMemo(() => {
    const result = new Map<string, 'completed' | 'running' | 'pending'>();
    for (const node of graph?.dimensions || []) {
      const progressKey = `${node.layer}_${node.key}`;
      const completed = Boolean(reports[`layer${node.layer}`]?.[node.key])
        || dimensionProgress[progressKey]?.status === 'completed';
      result.set(
        node.key,
        completed
          ? 'completed'
          : executingDimensions.has(progressKey)
            ? 'running'
            : 'pending',
      );
    }
    return result;
  }, [dimensionProgress, executingDimensions, graph, reports]);

  const selectedNode = graph?.dimensions.find((node) => isSelectedNode(node, selectedNavigationKey));

  const connectedKeys = useMemo(() => {
    if (!graph || !selectedNode) return new Set<string>();
    const result = new Set<string>([selectedNode.key]);
    const queue = [selectedNode.key];
    while (queue.length > 0) {
      const current = queue.shift();
      if (!current) continue;
      for (const edge of graph.edges) {
        if (edge.source !== current && edge.target !== current) continue;
        const next = edge.source === current ? edge.target : edge.source;
        if (!result.has(next)) {
          result.add(next);
          queue.push(next);
        }
      }
    }
    return result;
  }, [graph, selectedNode]);

  const visibleNodes = useMemo(() => {
    if (!graph) return [];
    return graph.dimensions.filter((node) => {
      if (filter === 'selected') return connectedKeys.has(node.key);
      if (filter === 'pending') return statusByKey.get(node.key) !== 'completed';
      return true;
    });
  }, [connectedKeys, filter, graph, statusByKey]);

  const visibleKeys = useMemo(() => new Set(visibleNodes.map((node) => node.key)), [visibleNodes]);

  const positions = useMemo(() => {
    const result = new Map<string, { x: number; y: number }>();
    for (const layer of [1, 2, 3] as const) {
      const nodes = visibleNodes.filter((node) => node.layer === layer);
      nodes.forEach((node, index) => {
        result.set(node.key, { x: COLUMN_X[layer], y: 36 + index * (NODE_HEIGHT + ROW_GAP) });
      });
    }
    return result;
  }, [visibleNodes]);

  const graphHeight = Math.max(
    300,
    ...([1, 2, 3] as const).map((layer) => visibleNodes.filter((node) => node.layer === layer).length * (NODE_HEIGHT + ROW_GAP) + 54),
  );

  const visibleEdges = useMemo(
    () => (graph?.edges || []).filter((edge) => visibleKeys.has(edge.source) && visibleKeys.has(edge.target)),
    [graph, visibleKeys],
  );

  const completedCount = [...statusByKey.values()].filter((status) => status === 'completed').length;
  const runningCount = [...statusByKey.values()].filter((status) => status === 'running').length;

  if (!graph) {
    return (
      <div className="rounded-xl border border-dashed border-[#dcebe4] bg-[#fbfdfc] px-4 py-8 text-center text-[12px] text-[#78968b]">
        {graphStatus === 'error' ? '后端专题依赖配置暂时无法读取，目录视图仍可使用。' : '正在读取后端声明的专题依赖配置…'}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#dcebe4] bg-[#f7fcf9] px-3 py-2.5">
        <div>
          <div className="text-[12px] font-semibold text-[#244c40]">专题依赖图</div>
          <div className="mt-0.5 text-[10px] text-[#78968b]">依据后端 {graph.source.split('/').pop()}；节点状态来自当前会话</div>
        </div>
        <div className="flex items-center gap-1.5 text-[10px] tabular-nums text-[#6d8c80]">
          <span className="rounded-full bg-[#dff2e9] px-2 py-1 text-[#2d7e61]">已完成 {completedCount}/{graph.dimensions.length}</span>
          {runningCount > 0 && <span className="rounded-full bg-[#fff3df] px-2 py-1 text-[#9a7428]">执行中 {runningCount}</span>}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {([
          ['all', '全图'],
          ['selected', selectedNode ? '当前依赖' : '当前依赖（先选专题）'],
          ['pending', '未完成'],
        ] as Array<[GraphFilter, string]>).map(([key, label]) => (
          <button
            key={key}
            type="button"
            disabled={key === 'selected' && !selectedNode}
            onClick={() => setFilter(key)}
            className={`rounded-lg px-2.5 py-1.5 text-[11px] transition ${filter === key ? 'bg-[#dff2e9] font-semibold text-[#2d7e61]' : 'bg-white text-[#78968b] hover:bg-[#f3faf7]'} disabled:cursor-not-allowed disabled:opacity-50`}
          >
            {label}
          </button>
        ))}
        <span className="ml-auto text-[10px] text-[#9ab2a8]">点击节点跳转专题</span>
      </div>

      <div className="overflow-x-auto rounded-xl border border-[#dcebe4] bg-[#fbfdfc] p-2">
        <svg viewBox={`0 0 930 ${graphHeight}`} className="min-w-[760px]" role="img" aria-label="专题规划依赖图">
          <defs>
            <marker id="topic-dependency-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
              <path d="M0,0 L7,3.5 L0,7 z" fill="#a9c9ba" />
            </marker>
          </defs>
          {[1, 2, 3].map((layer) => (
            <text key={layer} x={COLUMN_X[layer as 1 | 2 | 3]} y="20" fill="#719889" fontSize="11" fontWeight="600">
              L{layer} · {LAYER_VALUE_MAP[layer]}
            </text>
          ))}

          {visibleEdges.map((edge: PlanningDependencyEdge) => {
            const source = positions.get(edge.source);
            const target = positions.get(edge.target);
            if (!source || !target) return null;
            const sourceNode = graph.dimensions.find((node) => node.key === edge.source);
            const targetNode = graph.dimensions.find((node) => node.key === edge.target);
            const active = isSelectedNode(sourceNode!, selectedNavigationKey) || isSelectedNode(targetNode!, selectedNavigationKey);
            const sourceX = source.x + NODE_WIDTH;
            const targetX = target.x;
            const midX = (sourceX + targetX) / 2;
            return (
              <path
                key={`${edge.source}-${edge.target}-${edge.kind}`}
                d={`M ${sourceX} ${source.y + NODE_HEIGHT / 2} C ${midX} ${source.y + NODE_HEIGHT / 2}, ${midX} ${target.y + NODE_HEIGHT / 2}, ${targetX} ${target.y + NODE_HEIGHT / 2}`}
                fill="none"
                stroke={active ? '#43aa82' : '#b9d5c8'}
                strokeWidth={active ? 1.8 : 1}
                strokeDasharray={edge.kind === 'same_layer' ? undefined : '4 3'}
                opacity={filter === 'selected' || active ? 0.95 : 0.55}
                markerEnd="url(#topic-dependency-arrow)"
              />
            );
          })}

          {visibleNodes.map((node) => {
            const position = positions.get(node.key);
            if (!position) return null;
            const status = statusByKey.get(node.key) || 'pending';
            const selected = isSelectedNode(node, selectedNavigationKey);
            const fill = status === 'completed' ? '#e8f5ef' : status === 'running' ? '#fff3df' : '#f4f8f6';
            const stroke = selected ? '#2d8c6d' : status === 'completed' ? '#8dceb1' : status === 'running' ? '#e5b968' : '#d2e3db';
            return (
              <g
                key={node.key}
                role="button"
                tabIndex={0}
                aria-label={`${node.name}，${status === 'completed' ? '已完成' : status === 'running' ? '执行中' : '待执行'}`}
                className="cursor-pointer outline-none"
                onClick={() => onSelectDimension(nodeNavigationKey(node))}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') onSelectDimension(nodeNavigationKey(node));
                }}
              >
                <title>{`${node.name} · Wave ${node.wave} · 依赖 ${node.depends_on.length} 项`}</title>
                <rect x={position.x} y={position.y} width={NODE_WIDTH} height={NODE_HEIGHT} rx="9" fill={fill} stroke={stroke} strokeWidth={selected ? 2 : 1} />
                <circle cx={position.x + 15} cy={position.y + 17} r="4" fill={status === 'completed' ? '#3fb288' : status === 'running' ? '#e5a53e' : '#b5cfc1'} />
                <text x={position.x + 27} y={position.y + 15} fill="#315f50" fontSize="10" fontWeight="600">{shortLabel(node.name)}</text>
                <text x={position.x + 27} y={position.y + 27} fill="#86a59a" fontSize="8">Wave {node.wave} · 依赖 {node.depends_on.length}</text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="flex flex-wrap items-center gap-3 px-1 text-[10px] text-[#78968b]">
        <span className="inline-flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-[#3fb288]" />已完成</span>
        <span className="inline-flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-[#e5a53e]" />执行中</span>
        <span className="inline-flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-[#b5cfc1]" />待执行</span>
        <span className="ml-auto">实线：同层依赖 · 虚线：跨层 / 跨阶段依赖</span>
      </div>
    </div>
  );
}
