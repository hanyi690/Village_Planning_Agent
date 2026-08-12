import { apiRequest } from '@/features/planning/api/client';

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

export const evaluationApi = {
  listProjects: () =>
    apiRequest<{ projects: ProjectInfo[] }>('/api/projects'),

  listSessions: (projectName: string) =>
    apiRequest<{ sessions: SessionInfo[] }>(`/api/projects/${encodeURIComponent(projectName)}/sessions`),

  run: (sessionId: string, signal?: AbortSignal) =>
    apiRequest<EvaluationRunResponse>(`/api/evaluation/sessions/${sessionId}/run`, {
      method: 'POST',
      signal,
    }),

  getResults: (sessionId: string) =>
    apiRequest<EvaluationResult>(`/api/evaluation/sessions/${sessionId}/results`),

  getStatus: (sessionId: string) =>
    apiRequest<EvaluationStatusResponse>(`/api/evaluation/sessions/${sessionId}/status`),

  runCascade: (sessionId: string) =>
    apiRequest<CascadeConsistencyResult>(`/api/evaluation/sessions/${sessionId}/cascade`, {
      method: 'POST',
    }),

  exportMarkdown: (sessionId: string) =>
    apiRequest<{ session_id: string; markdown: string; filename: string }>(
      `/api/evaluation/sessions/${sessionId}/export/markdown`,
    ),
};
