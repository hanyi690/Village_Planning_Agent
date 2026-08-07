# P0-4: CI Backend with Health Gate and Logs

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix CI so Playwright E2E tests have both frontend (port 3000) and backend (port 8000) running with a hard health-gate that fails the step on timeout, backend logs saved as CI artifact, and the real `/health` endpoint used for readiness.

**Architecture:** Add Python setup + backend startup to the `frontend-tests` job. Use `curl --fail http://localhost:8000/health` as the readiness gate (endpoint exists at `main.py:282`). Save backend logs as CI artifact on failure. Increase Playwright `webServer` timeout.

**Tech Stack:** GitHub Actions, Python 3.11, uvicorn, FastAPI, Playwright

## Global Constraints

- CI runs on `ubuntu-latest`
- Backend entry: `app.main:app`, dependencies: `../requirements-dev.txt`
- `/health` endpoint exists at `backend/app/main.py:282`
- LF line endings
- Commit only when explicitly asked, at task boundaries

---

### Task 1: Add Python, backend startup, and health gate to CI

**Files:**
- Modify: `.github/workflows/gis-engine-ci.yml` (frontend-tests job)

- [ ] **Step 1: Add Python setup and backend start with health gate**

Insert before "Run Playwright E2E tests" step:

```yaml
      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
          cache-dependency-path: requirements-dev.txt

      - name: Install backend dependencies
        run: pip install -r ../requirements-dev.txt

      - name: Start backend server
        working-directory: backend
        run: |
          uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/backend.log 2>&1 &
          echo "Backend PID: $!"
          for i in $(seq 1 30); do
            if curl --fail http://localhost:8000/health > /dev/null 2>&1; then
              echo "Backend is ready (health check passed)"
              exit 0
            fi
            echo "Waiting for backend... ($i/30)"
            sleep 2
          done
          echo "Backend failed to start within 60s"
          cat /tmp/backend.log
          exit 1
        env:
          PYTHONPATH: .

      - name: Upload backend logs on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: backend-logs
          path: /tmp/backend.log
          retention-days: 7
```

Key differences from the previous plan:
- Uses `/health` (real endpoint at main.py:282), not `/docs`
- `exit 1` after 30 retries - step FAILS, doesn't silently continue
- Backend logs saved as artifact AND printed on failure
- `curl --fail` returns non-zero on HTTP errors

- [ ] **Step 2: Increase Playwright webServer timeout**

In `frontend/playwright.config.ts:32`, change `timeout: 30000` to `timeout: 60000`.

- [ ] **Step 3: Validate YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/gis-engine-ci.yml'))"`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/gis-engine-ci.yml frontend/playwright.config.ts
git commit -m "ci: start backend with /health gate, save logs, fail on timeout"
```
