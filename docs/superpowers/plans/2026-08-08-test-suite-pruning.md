# E2E-only test suite

The repository now keeps only end-to-end coverage.

- Backend E2E tests live under `backend/tests/e2e`.
- Frontend Playwright tests live under `frontend/e2e`.
- Backend pytest defaults to `e2e and not slow`; the real-LLM E2E is explicit and marked `slow`.
- Unit, contract, architecture, service, road, and non-E2E integration tests were removed.
- Shared fixtures required by the retained E2E paths remain under `backend/tests/fixtures`.
