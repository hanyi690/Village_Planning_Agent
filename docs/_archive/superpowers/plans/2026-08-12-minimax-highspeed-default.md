# MiniMax High-Speed LLM Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the project's implicit LLM calls default to the configured MiniMax high-speed model `MiniMax-M2.7-highspeed` across application, deployment, and evaluation-script entry points.

**Architecture:** Keep explicit provider-specific factories available for opt-in OpenAI and ZhipuAI usage. Centralize the implicit MiniMax model fallback in the existing settings/factory boundary, make the explicit MiniMax helper honor `MINIMAX_MODEL`, and route the standalone NLI evaluation script through the same provider-aware factory instead of hard-coding DashScope `qwen-flash`.

**Tech Stack:** Python 3, LangChain `ChatOpenAI`, Instructor/OpenAI-compatible clients, PowerShell-compatible repository tooling, pytest.

## Global Constraints

- The implicit default provider is `minimax`.
- The implicit default model is exactly `MiniMax-M2.7-highspeed`.
- `MINIMAX_MODEL`, `LLM_MODEL`, and task-specific model environment variables remain explicit override points.
- Explicit provider-specific APIs retain their provider-specific model semantics.
- Existing unrelated working-tree changes must remain untouched.

---

### Task 1: Centralize the implicit MiniMax high-speed default

**Files:**
- Modify: `backend/app/core/settings.py`
- Modify: `backend/app/core/llm.py`
- Test: `backend/tests/e2e/test_minimax_provider.py`

**Interfaces:**
- Produces the settings fallback `DEFAULT_LLM_MODEL = "MiniMax-M2.7-highspeed"`.
- `create_llm(provider="minimax", model=None)` continues to resolve through `MINIMAX_MODEL`.
- `get_minimax_llm(model=None)` resolves through `MINIMAX_MODEL`, including environment overrides.

- [ ] **Step 1: Add a regression test for implicit MiniMax selection**

  Extend the provider wiring test to construct `create_llm(provider="minimax", model=None)` and assert its public model attribute is `MiniMax-M2.7-highspeed` when no model override is supplied.

- [ ] **Step 2: Run the focused test and verify the current behavior is covered**

  Run `pytest tests/e2e/test_minimax_provider.py -q` from `backend/`. The existing factory should pass the implicit-default assertion; the test establishes the requested contract before the helper cleanup.

- [ ] **Step 3: Add one shared default constant and use it for all implicit model settings**

  Define `DEFAULT_LLM_MODEL = "MiniMax-M2.7-highspeed"` beside the provider settings and use it for the fallbacks of `MINIMAX_MODEL`, `LLM_MODEL`, `MULTIMODAL_MODEL`, `FLASH_MODEL_NAME`, and `GIS_EXPLORE_MODEL`.

- [ ] **Step 4: Make the explicit MiniMax helper honor its environment override**

  Change `get_minimax_llm` to accept `model: Optional[str] = None`, load `MINIMAX_MODEL`, and pass `model or MINIMAX_MODEL` to `_create_minimax_llm`.

- [ ] **Step 5: Run the focused tests again**

  Run `pytest tests/e2e/test_minimax_provider.py -q` from `backend/` and expect the no-network wiring test to pass. The network preflight may skip when no usable key is present.

### Task 2: Align deployment and operator-facing defaults

**Files:**
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Modify: `.env.example`

**Interfaces:**
- Docker Compose starts with `LLM_PROVIDER=minimax` and `LLM_MODEL=MiniMax-M2.7-highspeed` unless explicitly overridden.
- The documented copy-paste configuration describes MiniMax high-speed as the default and keeps other providers as explicit opt-ins.

- [ ] **Step 1: Update Docker Compose fallbacks**

  Replace the `qwen3.5-plus`/`openai` fallbacks with `MiniMax-M2.7-highspeed`/`minimax`, pass `MINIMAX_API_KEY`, `MINIMAX_API_BASE`, and `MINIMAX_MODEL`, and update the concurrency comment so it no longer describes the default as DashScope qwen.

- [ ] **Step 2: Update README and environment-template defaults**

  Make the primary examples use MiniMax high-speed. Keep the OpenAI/DashScope, DeepSeek, ZhipuAI, and qwen examples only under explicitly commented alternative configuration sections. Set the default multimodal model example to the same requested MiniMax model.

- [ ] **Step 3: Verify no active deployment default still points to qwen/OpenAI**

  Run `rg -n -i "LLM_MODEL=|LLM_PROVIDER=|LLM_MODEL=.*qwen|LLM_PROVIDER=.*openai|MULTIMODAL_MODEL=.*qwen|OCR_MODEL_NAME=.*qwen" docker-compose.yml .env.example README.md` and confirm matches are either the MiniMax defaults or clearly commented opt-in alternatives.

### Task 3: Route the standalone NLI evaluator through the configured default

**Files:**
- Modify: `scripts/experiments/rag/nli_faithfulness.py`

**Interfaces:**
- Coverage and faithfulness evaluation calls use `app.core.llm.create_llm` and therefore inherit `LLM_PROVIDER`/`LLM_MODEL` with MiniMax high-speed as the default.
- Rule-based fallback behavior remains unchanged when the provider is unavailable or returns invalid JSON.

- [ ] **Step 1: Replace direct DashScope invocation with the shared LLM factory**

  Add a small local helper that creates one configured LLM with `max_tokens=2000`, `temperature=0.1`, and `streaming=False`, then invoke it with the existing prompt. Parse the returned `.content` string through the existing JSON extraction logic.

- [ ] **Step 2: Remove hard-coded qwen-flash assumptions from evaluator messages**

  Rename the NLI helper/docstrings and log text to refer to the configured LLM rather than a fixed qwen model, without changing evaluation semantics.

- [ ] **Step 3: Run syntax and import verification**

  Run `python -m py_compile scripts/experiments/rag/nli_faithfulness.py` from the repository root and `python -c "from app.core.llm import create_llm; print('ok')"` from `backend/`.

### Task 4: Final repository-wide verification

**Files:**
- No additional files.

- [ ] **Step 1: Re-scan all active Python/config call sites**

  Run `rg -n -i "qwen-flash|qwen3.5-plus|LLM_MODEL=.*qwen|LLM_PROVIDER=.*openai|MiniMax-M2.7(?!-highspeed)" backend/app scripts docker-compose.yml .env.example README.md` with a tool-supported equivalent if the regex engine does not support lookarounds. Review each remaining match as an explicit opt-in, embedding model, or stale comment.

- [ ] **Step 2: Run focused backend tests**

  Run `pytest tests/e2e/test_minimax_provider.py tests/e2e/test_settings_env_resolution.py -q` from `backend/`.

- [ ] **Step 3: Update the code knowledge graph for changed code/config files**

  Run the repository's incremental graphify update in code-only mode and confirm the generated graph remains readable.

