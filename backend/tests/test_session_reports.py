"""
Tests for session report endpoints:

1. GET /api/sessions/{id}/reports/{dim_key}        — current + ?version=N
2. GET /api/sessions/{id}/reports/{dim_key}/versions — version history list
3. GET /api/projects/{name}/reports/{dim_key}        — cross-session query
"""
from unittest.mock import AsyncMock, patch

import pytest

# Mock paths use the import location in session_routes.py, not definition location.
# session_routes.py uses `from app.database.operations import get_dimension_revisions_async`
# so the patch target is `app.api.session_routes.<name>`.
PATCH_GET_STATE = 'app.api.session_routes.PlanningRuntimeService.aget_state_values'
PATCH_GET_REVISIONS = 'app.api.session_routes.get_dimension_revisions_async'
PATCH_LIST_SESSIONS = 'app.api.session_routes.list_planning_sessions_async'


class TestGetDimensionReport:
    """Existing endpoint: GET /api/sessions/{id}/reports/{dim_key}"""

    def test_current_report_from_layer1(self, client, sample_state):
        with patch(PATCH_GET_STATE, AsyncMock(return_value=sample_state)):
            resp = client.get('/api/sessions/test-session-1/reports/location')
        assert resp.status_code == 200
        data = resp.json()
        assert data['dimension_key'] == 'location'
        assert data['layer'] == 1
        assert '区位分析报告' in data['content']

    def test_current_report_from_layer2(self, client, sample_state):
        with patch(PATCH_GET_STATE, AsyncMock(return_value=sample_state)):
            resp = client.get('/api/sessions/test-session-1/reports/industry')
        assert resp.status_code == 200
        data = resp.json()
        assert data['dimension_key'] == 'industry'
        assert data['layer'] == 2

    def test_report_not_found(self, client, sample_state):
        with patch(PATCH_GET_STATE, AsyncMock(return_value=sample_state)):
            resp = client.get('/api/sessions/test-session-1/reports/nonexistent')
        assert resp.status_code == 404

    def test_session_not_found(self, client):
        with patch(PATCH_GET_STATE, AsyncMock(return_value=None)):
            resp = client.get('/api/sessions/nonexistent/reports/location')
        assert resp.status_code == 404

    def test_specific_version_from_revisions(self, client, sample_revisions):
        with patch(PATCH_GET_REVISIONS, AsyncMock(return_value=sample_revisions)):
            resp = client.get('/api/sessions/test-session-1/reports/location?version=2')
        assert resp.status_code == 200
        data = resp.json()
        assert data['version'] == 2
        assert data['layer'] == 1
        assert 'v2' in data['content']
        assert data['created_at'] == '2026-05-10T11:00:00'

    def test_version_not_found(self, client, sample_revisions):
        with patch(PATCH_GET_REVISIONS, AsyncMock(return_value=sample_revisions)):
            resp = client.get('/api/sessions/test-session-1/reports/location?version=99')
        assert resp.status_code == 404
        assert 'Version 99' in resp.json()['detail']

    def test_latest_version_returned(self, client, sample_revisions):
        with patch(PATCH_GET_REVISIONS, AsyncMock(return_value=sample_revisions)):
            resp = client.get('/api/sessions/test-session-1/reports/location?version=3')
        assert resp.status_code == 200
        data = resp.json()
        assert data['version'] == 3
        assert 'v3' in data['content']


class TestGetDimensionReportVersions:
    """New endpoint: GET /api/sessions/{id}/reports/{dim_key}/versions"""

    def test_version_list_summary(self, client, sample_revisions):
        with patch(PATCH_GET_REVISIONS, AsyncMock(return_value=sample_revisions)):
            resp = client.get('/api/sessions/test-session-1/reports/location/versions')
        assert resp.status_code == 200
        data = resp.json()
        assert data['session_id'] == 'test-session-1'
        assert data['dimension_key'] == 'location'
        assert len(data['versions']) == 3

        v = data['versions'][0]
        assert 'version' in v
        assert 'layer' in v
        assert 'created_at' in v
        assert 'reason' in v
        assert 'content' not in v
        assert v['version'] == 3
        assert v['reason'] == '用户反馈修订'

    def test_empty_versions_404(self, client):
        with patch(PATCH_GET_REVISIONS, AsyncMock(return_value=[])):
            resp = client.get('/api/sessions/test-session-1/reports/location/versions')
        assert resp.status_code == 404


class TestGetProjectDimensionReport:
    """New endpoint: GET /api/projects/{name}/reports/{dim_key}"""

    def test_latest_session_current_report(self, client, sample_state):
        with (
            patch(PATCH_LIST_SESSIONS, AsyncMock(return_value=[{'session_id': 'latest-session'}])),
            patch(PATCH_GET_STATE, AsyncMock(return_value=sample_state)),
        ):
            resp = client.get('/api/projects/金田村/reports/location')
        assert resp.status_code == 200
        data = resp.json()
        assert data['project_name'] == '金田村'
        assert data['session_id'] == 'latest-session'
        assert data['dimension_key'] == 'location'
        assert '区位分析报告' in data['content']

    def test_project_no_sessions(self, client):
        with patch(PATCH_LIST_SESSIONS, AsyncMock(return_value=[])):
            resp = client.get('/api/projects/不存在村/reports/location')
        assert resp.status_code == 404
        assert 'No sessions found' in resp.json()['detail']

    def test_specific_session_current(self, client, sample_state):
        with patch(PATCH_GET_STATE, AsyncMock(return_value=sample_state)):
            resp = client.get(
                '/api/projects/金田村/reports/location?session_id=target-session'
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data['session_id'] == 'target-session'

    def test_specific_session_not_found(self, client):
        with patch(PATCH_GET_STATE, AsyncMock(return_value=None)):
            resp = client.get(
                '/api/projects/金田村/reports/location?session_id=bad-session'
            )
        assert resp.status_code == 404

    def test_specific_session_with_version(self, client, sample_revisions):
        with patch(PATCH_GET_REVISIONS, AsyncMock(return_value=sample_revisions)):
            resp = client.get(
                '/api/projects/金田村/reports/location'
                '?session_id=test-session-1&version=1'
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data['session_id'] == 'test-session-1'
        assert data['version'] == 1
        assert 'v1' in data['content']

    def test_version_requires_session_id(self, client):
        resp = client.get('/api/projects/金田村/reports/location?version=1')
        assert resp.status_code == 400
        assert 'session_id' in resp.json()['detail']

    def test_version_not_found_in_session(self, client, sample_revisions):
        with patch(PATCH_GET_REVISIONS, AsyncMock(return_value=sample_revisions)):
            resp = client.get(
                '/api/projects/金田村/reports/location'
                '?session_id=test-session-1&version=99'
            )
        assert resp.status_code == 404
