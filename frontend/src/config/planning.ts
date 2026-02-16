/**
 * 规划系统配置常量
 * 统一管理前端和后端的规划参数默认值
 */

// ==========================================
// 规划参数默认值
// ==========================================

export const PLANNING_DEFAULTS = {
  // 执行模式
  stepMode: true,
  streamMode: true,
  enableReview: false,

  // 默认文本
  defaultTask: '制定村庄总体规划方案',
  defaultConstraints: '无特殊约束',
} as const;

// ==========================================
// 参数映射（前端 → 后端）
// ==========================================

export const PARAM_MAPPING = {
  stepMode: 'step_mode',
  streamMode: 'stream_mode',
  enableReview: 'enable_review',
  taskDescription: 'task_description',
  constraints: 'constraints',
} as const;

// ==========================================
// TypeScript 类型定义
// ==========================================

export type PlanningDefaults = typeof PLANNING_DEFAULTS;
export type ParamMapping = typeof PARAM_MAPPING;

// ==========================================
// 配置获取函数
// ==========================================

/**
 * 获取规划参数默认值
 */
export const getPlanningDefaults = (): PlanningDefaults => {
  return PLANNING_DEFAULTS;
};

/**
 * 获取参数映射
 */
export const getParamMapping = (): ParamMapping => {
  return PARAM_MAPPING;
};

/**
 * 将前端参数转换为后端参数
 */
export const convertToBackendParams = (params: {
  stepMode?: boolean;
  streamMode?: boolean;
  enableReview?: boolean;
  taskDescription?: string;
  constraints?: string;
}): Record<string, any> => {
  const result: Record<string, any> = {};

  if (params.stepMode !== undefined) {
    result[PARAM_MAPPING.stepMode] = params.stepMode;
  }
  if (params.streamMode !== undefined) {
    result[PARAM_MAPPING.streamMode] = params.streamMode;
  }
  if (params.enableReview !== undefined) {
    result[PARAM_MAPPING.enableReview] = params.enableReview;
  }
  if (params.taskDescription !== undefined) {
    result[PARAM_MAPPING.taskDescription] = params.taskDescription;
  }
  if (params.constraints !== undefined) {
    result[PARAM_MAPPING.constraints] = params.constraints;
  }

  return result;
};