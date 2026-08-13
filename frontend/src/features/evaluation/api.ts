
export interface CitationDetail {
  text: string;
  type: string;
  exists_in_kb: boolean;
  source_doc_name: string;
  accuracy_score: number;
  is_supportive: boolean;
  support_type: string;
}

export interface EvaluationDiagnostics {
  rag_library_available: boolean;
  rag_document_count: number;
  rag_library_paths: string[];
  dimensions_with_rag_chunks: number;
  faithfulness_applicable: boolean;
  citation_applicable: boolean;
  scoring_mode: string;
  generation_mode: string;
  offline_template_dimensions: number;
  llm_dimensions: number;
  warnings: string[];
}

export interface DimensionEvaluation {
  dimension_key: string;
  dimension_name: string;
  layer: number;
  text_length: number;
  faithfulness_score: number | null;
  faithfulness_applicable: boolean;
  total_claims: number;
  supported_claims: number;
  content_depth_score: number;
  content_depth_reasoning: string;
  citation_total: number;
  citation_existence_rate: number | null;
  citation_accuracy_rate: number | null;
  citation_supportive_rate: number | null;
  citation_applicable: boolean;
  overall_score: number;
  scoring_mode: string;
  hallucination_points: string[];
  hallucination_citations: CitationDetail[];
  citations: CitationDetail[];
  rag_enabled: boolean;
  rag_chunk_count: number;
  generation_mode: string;
}

export interface OverallSummary {
  faithfulness_avg: number | null;
  content_depth_avg: number;
  citation_existence_avg: number | null;
  citation_accuracy_avg: number | null;
  overall_score: number;
  scoring_mode: string;
  dimensions_evaluated: number;
  total_citations: number;
  hallucination_citations: number;
  total_claims: number;
  supported_claims: number;
  unsupported_claims: number;
  faithfulness_applicable_dimensions: number;
  citation_applicable_dimensions: number;
}

export interface EvaluationResult {
  session_id: string;
  project_name: string;
  evaluated_at: string;
  overall: OverallSummary;
  diagnostics: EvaluationDiagnostics;
  dimensions: DimensionEvaluation[];
  cascade?: CascadeConsistencyResult | null;
}

export interface CascadeDimensionScore {
  dimension_key: string;
  dimension_name: string;
  pair_type: string;
  target_dimension: string;
  score: number;
  detail: string;
}

export interface CascadeConsistencyResult {
  session_id: string;
  overall_score: number;
  pair_scores: CascadeDimensionScore[];
  revision_scores: CascadeDimensionScore[];
  warnings: string[];
}

export interface EvaluationRunResponse {
  session_id: string;
  status: string;
  message: string;
  result?: EvaluationResult;
}

export interface EvaluationStatusResponse {
  session_id: string;
  has_result: boolean;
  evaluated_at?: string;
  overall_score?: number;
  scoring_mode?: string;
}

export interface ProjectInfo {
  project_name: string;
  session_count?: number;
}

export interface SessionInfo {
  session_id: string;
  project_name?: string;
  status?: string;
  created_at?: string;
}

// v1 对齐：/api/projects 与 /api/evaluation/* 均未在后端 v1 提供。
// 列表类方法返回空结果（页面显示"暂无会话"），其余方法抛错标注已下线。
export const evaluationApi = {
  listProjects: async (): Promise<{ projects: ProjectInfo[] }> => {
    // 后端 v1 未提供项目列表；QA 页暂无可选会话。
    return { projects: [] };
  },

  listSessions: async (_projectName: string): Promise<{ sessions: SessionInfo[] }> => {
    return { sessions: [] };
  },

  run: async (_sessionId: string, _signal?: AbortSignal): Promise<EvaluationRunResponse> => {
    throw new Error('[v1] 质量评估端点已下线（/api/evaluation/sessions/{id}/run）');
  },

  getResults: async (_sessionId: string): Promise<EvaluationResult> => {
    throw new Error('[v1] 质量评估端点已下线（/api/evaluation/sessions/{id}/results）');
  },

  getStatus: async (_sessionId: string): Promise<EvaluationStatusResponse> => {
    throw new Error('[v1] 质量评估端点已下线（/api/evaluation/sessions/{id}/status）');
  },

  runCascade: async (_sessionId: string): Promise<CascadeConsistencyResult> => {
    throw new Error('[v1] 质量评估端点已下线（/api/evaluation/sessions/{id}/cascade）');
  },

  exportMarkdown: async (_sessionId: string): Promise<{ session_id: string; markdown: string; filename: string }> => {
    throw new Error('[v1] 质量评估端点已下线（/api/evaluation/sessions/{id}/export/markdown）');
  },
};
