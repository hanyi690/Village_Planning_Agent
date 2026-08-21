import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import EvidenceQueryPanel from '@/features/planning/components/EvidenceQueryPanel';
import { planningApi } from '@/features/planning/api';
import type { EvidenceQueryResponse } from '@/features/planning/api/types';

jest.mock('@/features/planning/api', () => ({
  planningApi: {
    queryEvidence: jest.fn(),
  },
}));

const queryEvidence = planningApi.queryEvidence as jest.MockedFunction<typeof planningApi.queryEvidence>;

const multipleCandidateResponse = {
  schema_version: '1.0',
  session_id: 'session-evidence-ui',
  request: '社前村祠堂的BSM',
  evidence_bundle: {
    request: '社前村祠堂的BSM',
    facts: [{
      statement: '社前村存在祠堂设施候选。',
      confidence: 0.9,
      source_refs: ['report:planning-1'],
      spatial_refs: ['feature-1'],
      fact_type: 'l1_fact',
      fields: {},
      feature_bsm: '00000000000000000001',
      related_parcel_bsms: ['parcel-1'],
      evidence_span: '原始报告：社前村祠堂位于居民点附近。',
      source_locator: 'report:planning-1',
      support_relation: 'quotation',
      support_relations: [],
      related_fact_refs: [],
      status: 'verified',
      evidence_role: 'location_binding',
      source_kind: 'report',
      spatial_granularity: 'feature',
      planning_use: 'grounding',
    }],
    sources: [{
      source_type: 'bundle',
      reference: 'bundle:snapshot:test',
      evidence_role: 'spatial_identity',
      authority: 'geometry_authoritative',
      availability: 'available',
      confidence: 1,
      supports: ['location_binding'],
      snapshot_ref: 'bundle:snapshot:test',
      retrieved_at: '',
    }, {
      source_type: 'report',
      reference: 'report:planning-1',
      evidence_role: 'location_binding',
      authority: 'advisory',
      availability: 'available',
      confidence: 0.9,
      supports: ['semantic_context'],
      snapshot_ref: 'report:snapshot:test',
      retrieved_at: '',
    }],
    confidence: 0.7,
    unresolved: [],
    conflicts: [],
    provenance: null,
  },
  spatial_cognition: null,
  evidence_packet: {
    request: '社前村祠堂的BSM',
    query_fingerprint: 'query',
    bundle_snapshot_digest: 'bundle',
    kg_version: '1',
    l1_snapshot_ref: 'l1',
    l1_scope_refs: [],
    candidate_refs: [
      {
        identity: {
          bundle_feature_bsm: '00000000000000000001',
          canonical_name: '祠堂',
          entity_type: 'facility',
          role: 'facility',
          aliases: [],
          admin_code_12: '000000000000',
          sequence_code_8: '00000001',
          source_feature_id: 'feature-1',
          source_layer: 'annotations_current',
          source_bsm: '00000000000000000001',
          bsm_kind: 'source',
          geometry_digest: '',
          bundle_snapshot_digest: 'bundle',
        },
        geometry_ref: 'bundle://feature/00000000000000000001',
        geometry_authority: 'bundle',
        entity_refs: [],
        relation_refs: [],
        provenance_refs: [],
        l1_fact_refs: [],
        related_parcel_bsms: ['parcel-1'],
        source_authority_score: 1,
        semantic_match_score: 0.6,
        spatial_support_score: 0.8,
        external_support_score: 0,
        retrieval_score: 0.7,
        selection_confidence: null,
      },
      {
        identity: {
          bundle_feature_bsm: '00000000000000000002',
          canonical_name: '祠堂',
          entity_type: 'facility',
          role: 'facility',
          aliases: [],
          admin_code_12: '000000000000',
          sequence_code_8: '00000002',
          source_feature_id: 'feature-2',
          source_layer: 'annotations_current',
          source_bsm: '00000000000000000002',
          bsm_kind: 'source',
          geometry_digest: '',
          bundle_snapshot_digest: 'bundle',
        },
        geometry_ref: 'bundle://feature/00000000000000000002',
        geometry_authority: 'bundle',
        entity_refs: [],
        relation_refs: [],
        provenance_refs: [],
        l1_fact_refs: [],
        related_parcel_bsms: ['parcel-2'],
        source_authority_score: 1,
        semantic_match_score: 0.55,
        spatial_support_score: 0.75,
        external_support_score: 0,
        retrieval_score: 0.65,
        selection_confidence: null,
      },
    ],
    relation_evidence: [],
    source_spans: ['原始报告：社前村祠堂位于居民点附近。'],
    external_refs: [],
    ambiguity_status: 'multiple',
    sufficiency: 'sufficient',
    missing_evidence: [],
    query_trace: [
      { step: 'retriever', retriever: 'bundle', status: 'returned', fact_count: 2, source_count: 1 },
      { step: 'retriever', retriever: 'report', status: 'empty', fact_count: 0, source_count: 0 },
    ],
  },
} as unknown as EvidenceQueryResponse;

const evidencePacket = multipleCandidateResponse.evidence_packet;
if (evidencePacket?.candidate_refs?.length === 2) {
  evidencePacket.relation_evidence = [{
    relation_id: 'relation:nearby:1',
    subject: evidencePacket.candidate_refs[0],
    predicate: 'http://village-planning.org/ontology#nearby',
    object: evidencePacket.candidate_refs[1],
    metric_value: 18,
    metric_unit: 'm',
    tolerance: null,
    crs: 'EPSG:4326',
    computation_method: 'kg_topology',
    provenance_refs: ['kg:relation:1'],
  }];
}

describe('EvidenceQueryPanel candidate state', () => {
  beforeEach(() => {
    queryEvidence.mockResolvedValue(multipleCandidateResponse);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('marks ambiguous candidates as pending selection instead of located', async () => {
    render(<EvidenceQueryPanel sessionId="session-evidence-ui" villageName="金田村" />);

    fireEvent.click(screen.getByRole('button', { name: '查询' }));

    await waitFor(() => {
      expect(screen.getAllByText('待选择')).toHaveLength(2);
    });
    expect(queryEvidence.mock.calls[0]?.[1]).not.toHaveProperty('entity_scope');
    expect(screen.getByText(/结果：\s*多候选/)).toBeInTheDocument();
    expect(screen.getByText(/项目级相关证据明细（事实 1 · 文本背景 1 · KG\/拓扑关系 1）/)).toBeInTheDocument();
    expect(screen.getByText(/bundle：returned · facts=2 · sources=1/)).toBeInTheDocument();
    expect(screen.getByText(/report：empty · facts=0 · sources=0/)).toBeInTheDocument();
    expect(screen.getByText('社前村存在祠堂设施候选。')).toBeInTheDocument();
    expect(screen.getByText('原始报告：社前村祠堂位于居民点附近。')).toBeInTheDocument();
    expect(screen.getByText('原文证据：原始报告：社前村祠堂位于居民点附近。')).toBeInTheDocument();
    expect(screen.getByText(/kg_topology/)).toBeInTheDocument();
    expect(screen.queryByText('已定位')).not.toBeInTheDocument();
    expect(screen.queryByText('定位')).not.toBeInTheDocument();
  });
});
