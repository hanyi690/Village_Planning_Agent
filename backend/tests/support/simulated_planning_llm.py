"""Explicit simulated provider for end-to-end planning graph tests.

This module is test-only.  It implements the same three provider contracts
used by production:

* L1: ``L1DimensionOutput`` (report body + observations)
* L2: streamed report text
* L3/source semantics: typed structured responses

It deliberately does not patch stage nodes, create BSMs, or manufacture
geometry.  Spatial identity still has to be obtained from the real bundle,
KG, EvidenceGraph and GROUND/SELECT/EXECUTE pipeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from langchain_core.messages import AIMessageChunk


@dataclass
class SimulatedPlanningProvider:
    """Deterministic, quota-free provider with auditable call counters."""

    fact_id: Callable[[], str | Awaitable[str]] | None = None
    fact_id_by_kind: Callable[[str], str | Awaitable[str]] | None = None
    calls: dict[str, int] = field(default_factory=dict)
    semantic_source_id: str = ''
    semantic_source_marker: str = ''
    facility_mode: bool = False
    combined_mode: bool = False
    semantic_source_ids: dict[str, str] = field(default_factory=dict)

    def _count(self, key: str) -> None:
        self.calls[key] = self.calls.get(key, 0) + 1

    def l1_output(self, dimension_key: str) -> Any:
        from app.domain.assessment.observation_draft import L1DimensionOutput

        self._count(f'L1:{dimension_key}')
        observations: list[dict[str, str]] = []
        if dimension_key == 'traffic':
            observations.append({
                'entity_type': '道路',
                'name': '村道',
                'location': '金田村',
                'relation': '连接金田村现状居民点',
                'description': '现状村道，需要形成可执行的道路建设或提升成果。',
                'scale': '1条',
            })
        if self.facility_mode and dimension_key == 'public_services':
            observations.append({
                'entity_type': '现状设施',
                'name': '祠堂',
                'location': '社前村',
                'relation': '位于社前村',
                'description': '社前村现状祠堂，可作为公共文化服务设施定位依据。',
                'scale': '1处',
            })
        return L1DimensionOutput(
            report_body=(
                f'【{dimension_key}现状】\n'
                f'金田村{dimension_key}现状分析基于当前报告和已加载空间数据形成。\n'
                '【事实】金田村现状规划资料已加载并形成可追溯事实记录。\n'
                '【证据边界】\n'
                '未由结构化观测确认的空间对象不作为后续定位依据。'
            ),
            observations=observations,
        )

    def l2_text(self, dimension_key: str) -> str:
        self._count(f'L2:{dimension_key}')
        if dimension_key == 'planning_positioning':
            return (
                '# 规划定位\n'
                '金田村形成以现状村庄服务和交通改善为重点的规划定位。\n'
                '村庄分类：整治提升类\n'
                '【规划策略】\n'
                '- 优先完善村庄道路和公共服务联系\n'
            )
        return (
            f'# {dimension_key}规划思路\n'
            '【总体目标】\n'
            '形成证据可追溯、空间可落地、实施边界清晰的规划方案。\n'
            '【规划策略】\n'
            '- 优先使用现状证据支持规划决策\n'
        )

    async def l3_payload(self, dimension_key: str) -> Any:
        from app.domain.program.claim_draft import L3DimensionOutput, PlanningClaimDraft

        self._count(f'L3:{dimension_key}')
        claims: list[Any] = []
        if dimension_key == 'traffic_planning':
            ref = await self._fact_id('road')
            claims.append(PlanningClaimDraft(
                claim_id='sim-road-widen',
                dimension_key=dimension_key,
                statement='金田村现状村道拓宽为规划道路并形成交通运输用地成果。',
                suggested_category='road',
                suggested_output_kind='line',
                asset_kind='road',
                suggested_interventions=['村道拓宽'],
                intervention_action='widen',
                location_hints=['金田村', '村道'],
                evidence_refs=['simulated:l1:traffic'],
                source_fact_refs=[ref] if ref else [],
                road_parameters={
                    'action': 'widen',
                    'road_level': '村道',
                    'length': {'value': 120, 'unit': 'm'},
                    'roadbed_width': {'value': 6, 'unit': 'm'},
                    'pavement_width': {'value': 4, 'unit': 'm'},
                },
            ))
        if self.facility_mode and dimension_key == 'public_service':
            ref = await self._fact_id('facility')
            claims.append(PlanningClaimDraft(
                claim_id='sim-facility-hall',
                dimension_key=dimension_key,
                statement='在社前村现状祠堂语义锚点附近配置公共文化服务设施点。',
                suggested_category='facility',
                suggested_output_kind='point',
                asset_kind='facility',
                suggested_interventions=['公共文化服务设施点'],
                intervention_action='new',
                location_hints=['社前村', '祠堂'],
                evidence_refs=['simulated:l1:public_services'],
                source_fact_refs=[ref] if ref else [],
                facility_parameters={
                    'facility_type': '公共文化服务设施',
                    'action': 'new',
                    'service_radius': {'value': 30, 'unit': 'm'},
                },
            ))
        return L3DimensionOutput(
            report_body=(
                f'【{dimension_key}详细规划】\n'
                '依据已审计 L1 空间事实和 L2 规划背景形成实施安排；具体空间身份由后续空间链路确定。'
            ),
            claims=claims,
        )

    async def structured_output(self, response_model: type[Any], messages: list[dict[str, Any]], **_: Any) -> Any:
        name = getattr(response_model, '__name__', '')
        if name == 'L1DimensionOutput':
            prompt = '\n'.join(str(item.get('content') or '') for item in messages)
            dimension_key = self._dimension_from_prompt(prompt)
            return self.l1_output(dimension_key)
        if name == 'L3DimensionOutput':
            prompt = '\n'.join(str(item.get('content') or '') for item in messages)
            dimension_key = self._dimension_from_prompt(prompt)
            return await self.l3_payload(dimension_key)
        if name == 'SourceFeatureSemanticProposalBatch':
            from app.contracts.evidence.source_semantic_contracts import (
                SourceFeatureSemanticProposal,
                SourceFeatureSemanticProposalBatch,
            )

            payload = json.loads(str(messages[-1].get('content') or '{}'))
            proposals = []
            fact_ref_by_kind = {
                'point': await self._fact_id('facility'),
                'line': await self._fact_id('road'),
            }
            allowed_geometry_kinds = (
                {'Point', 'MultiPoint', 'LineString', 'MultiLineString'}
                if self.combined_mode
                else (
                    {'Point', 'MultiPoint'}
                    if self.facility_mode
                    else {'LineString', 'MultiLineString'}
                )
            )
            eligible = [
                item
                for item in payload.get('source_items') or []
                if str(item.get('geometry_kind') or '') in allowed_geometry_kinds
            ]
            selection_fact_ref = (
                fact_ref_by_kind['point']
                if self.facility_mode
                else fact_ref_by_kind['line']
            )
            if self.combined_mode:
                eligible_by_kind = {
                    'point': [
                        item for item in eligible
                        if str(item.get('geometry_kind') or '') in {'Point', 'MultiPoint'}
                    ],
                    'line': [
                        item for item in eligible
                        if str(item.get('geometry_kind') or '') in {'LineString', 'MultiLineString'}
                    ],
                }
                for kind, kind_items in eligible_by_kind.items():
                    if (
                        self.semantic_source_ids.get(kind)
                        or not kind_items
                        or not fact_ref_by_kind[kind]
                    ):
                        continue
                    selected = None
                    if kind == 'point':
                        selected = next(
                            (
                                item for item in kind_items
                                if str(item.get('raw_label') or '').strip() in {'祠', '祠堂'}
                            ),
                            None,
                        )
                    if selected is None and self.semantic_source_marker:
                        selected = next(
                            (
                                item for item in kind_items
                                if self.semantic_source_marker in str(
                                    item.get('source_feature_id') or ''
                                )
                            ),
                            None,
                        )
                    if selected is None and not self.semantic_source_marker:
                        selected = kind_items[0]
                    if selected is not None:
                        self.semantic_source_ids[kind] = str(
                            selected.get('source_feature_id') or ''
                        )
            elif not self.semantic_source_id and eligible and selection_fact_ref:
                selected = None
                if self.facility_mode:
                    selected = next(
                        (
                            item for item in eligible
                            if str(item.get('raw_label') or '').strip() in {'祠', '祠堂'}
                        ),
                        None,
                    )
                if selected is None and self.semantic_source_marker:
                    selected = next(
                        (
                            item for item in eligible
                            if self.semantic_source_marker in str(
                                item.get('source_feature_id') or ''
                            )
                        ),
                        None,
                    )
                if selected is None and not self.semantic_source_marker:
                    selected = eligible[0]
                if selected is not None:
                    self.semantic_source_id = str(selected.get('source_feature_id') or '')
            for item in payload.get('source_items') or []:
                source_id = str(item.get('source_feature_id') or '')
                geometry_kind = str(item.get('geometry_kind') or '')
                kind = (
                    'point'
                    if geometry_kind in {'Point', 'MultiPoint'}
                    else 'line'
                )
                selected_source_id = (
                    self.semantic_source_ids.get(kind, '')
                    if self.combined_mode
                    else self.semantic_source_id
                )
                if (
                    geometry_kind not in allowed_geometry_kinds
                    or not fact_ref_by_kind[kind]
                    or source_id != selected_source_id
                ):
                    proposals.append(SourceFeatureSemanticProposal(source_feature_id=source_id))
                    continue
                fact_ref = fact_ref_by_kind[kind]
                proposals.append(SourceFeatureSemanticProposal(
                    source_feature_id=source_id,
                    candidate_ref=f'l1:{fact_ref}:entity',
                    supporting_fact_refs=[fact_ref],
                ))
            return SourceFeatureSemanticProposalBatch(proposals=proposals)
        raise AssertionError(f'unhandled simulated structured contract: {name}')

    async def _fact_id(self, kind: str = '') -> str:
        callback = self.fact_id_by_kind
        if callback is not None:
            value = callback(kind)
        elif self.fact_id is not None:
            value = self.fact_id()
        else:
            self.calls['fact_ref:empty'] = self.calls.get('fact_ref:empty', 0) + 1
            return ''
        if hasattr(value, '__await__'):
            value = await value
        result = str(value or '')
        key = 'fact_ref:present' if result else 'fact_ref:empty'
        self.calls[key] = self.calls.get(key, 0) + 1
        return result

    @staticmethod
    def _dimension_from_prompt(prompt: str) -> str:
        marker = '【dimension_key='
        start = prompt.find(marker)
        if start < 0:
            raise AssertionError('simulated prompt is missing its dimension contract marker')
        value = prompt[start + len(marker):]
        return value.split('】', 1)[0].strip()

    async def astream(self, prompt: str):
        dimension_key = self._dimension_from_prompt(prompt)
        text = self.l2_text(dimension_key)
        for chunk in (text[index:index + 80] for index in range(0, len(text), 80)):
            yield AIMessageChunk(content=chunk)


__all__ = ['SimulatedPlanningProvider']
