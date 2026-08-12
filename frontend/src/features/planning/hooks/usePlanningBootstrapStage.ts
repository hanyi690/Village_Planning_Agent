import { useMemo } from 'react';

import { DIMENSIONS_BY_LAYER, getDimensionName } from '../config/dimensions';
import { usePlanningStore } from '../store';

export type PlanningBootstrapStage =
  | 'submitting'
  | 'creating-session'
  | 'connecting'
  | 'starting-analysis'
  | 'ready';

export interface PlanningBootstrapStep {
  id: PlanningBootstrapStage;
  label: string;
  detail: string;
  done: boolean;
  active: boolean;
}

const STAGE_ORDER: PlanningBootstrapStage[] = [
  'submitting',
  'creating-session',
  'connecting',
  'starting-analysis',
  'ready',
];

function stageIndex(stage: PlanningBootstrapStage): number {
  return STAGE_ORDER.indexOf(stage);
}

export function usePlanningBootstrapStage(isStartingExternally = false) {
  const sessionId = usePlanningStore((state) => state.sessionId);
  const status = usePlanningStore((state) => state.status);
  const phase = usePlanningStore((state) => state.phase);
  const executingDimensions = usePlanningStore((state) => state.executingDimensions);
  const dimensionProgress = usePlanningStore((state) => state.dimensionProgress);
  const reports = usePlanningStore((state) => state.reports);

  return useMemo(() => {
    const completedCount = [1, 2, 3].reduce((sum, layer) => {
      const layerReports = reports[`layer${layer}` as 'layer1' | 'layer2' | 'layer3'] ?? {};
      return sum + Object.keys(layerReports).length;
    }, 0);

    const hasDimensionActivity = executingDimensions.length > 0
      || completedCount > 0
      || Object.values(dimensionProgress).some((item) => item.status === 'streaming' || item.status === 'completed');

    let stage: PlanningBootstrapStage = 'ready';

    if (isStartingExternally || (!sessionId && status === 'collecting')) {
      stage = 'submitting';
    } else if (sessionId && (status === 'collecting' || status === 'idle')) {
      stage = 'creating-session';
    } else if (
      sessionId
      && (status === 'planning' || status === 'revising' || status === 'collecting')
      && !hasDimensionActivity
    ) {
      stage = phase?.startsWith('layer') ? 'starting-analysis' : 'connecting';
    }

    const currentIndex = stageIndex(stage);
    const steps: PlanningBootstrapStep[] = [
      {
        id: 'submitting',
        label: '提交规划任务',
        detail: '正在校验项目信息并发送至后端…',
        done: currentIndex > stageIndex('submitting'),
        active: stage === 'submitting',
      },
      {
        id: 'creating-session',
        label: '创建规划会话',
        detail: '正在初始化会话、绑定村庄与 GIS 数据…',
        done: currentIndex > stageIndex('creating-session'),
        active: stage === 'creating-session',
      },
      {
        id: 'connecting',
        label: '连接分析引擎',
        detail: '正在建立实时连接并同步任务状态…',
        done: currentIndex > stageIndex('connecting'),
        active: stage === 'connecting',
      },
      {
        id: 'starting-analysis',
        label: '启动分层分析',
        detail: `正在准备 L1 现状分析 · 首个专题「${getDimensionName(DIMENSIONS_BY_LAYER[1][0])}」…`,
        done: stage === 'ready',
        active: stage === 'starting-analysis',
      },
    ];

    const headline = stage === 'submitting'
      ? '正在提交规划任务'
      : stage === 'creating-session'
        ? '正在创建规划会话'
        : stage === 'connecting'
          ? '正在连接分析引擎'
          : stage === 'starting-analysis'
            ? '正在启动分层分析'
            : '';

    return {
      stage,
      isBootstrapping: stage !== 'ready',
      headline,
      steps,
    };
  }, [
    dimensionProgress,
    executingDimensions.length,
    isStartingExternally,
    phase,
    reports,
    sessionId,
    status,
  ]);
}
