# Task 5 report: stable real-run structured provider fallback

Date: 2026-08-17

## Scope

Implemented the bounded provider-compatibility fallback in
`backend/app/infrastructure/llm/structured.py` and added offline coverage in
`backend/tests/core/test_structured_output_runner.py`.

`backend/app/infrastructure/llm/planning_claims.py` and
`backend/tests/core/test_planning_claim_provider_adapter.py` were not changed.
No real provider or network call was used, and no commit/reset/checkout was
performed.

## Root cause addressed

MiniMax/DeepSeek can return a complete JSON object in
`last_completion.choices[0].message.content` while returning no `tool_calls`.
Instructor `Mode.TOOLS` then exhausts its bounded attempts with
`InstructorRetryException: No tool calls or function call found` even though
the content is usable structured data.

## Implementation

- Instructor remains the primary execution path.
- Only `InstructorRetryException` can enter the new fallback.
- The fallback reads only the final completion's message content, accepting
  both attribute-style and dictionary-style completion objects.
- A closed `<think>...</think>` block is accepted only as a leading wrapper
  directly followed by the JSON object. A single outer ````json ... ````
  wrapper is accepted only when it encloses the complete JSON object. Wrapper
  text is never removed globally; JSON followed by `<think>`, prose between a
  wrapper and the object, nested fences, and think markers inside JSON strings
  are rejected.
- The JSON decoder uses `parse_constant` to reject non-standard `NaN`,
  `Infinity`, and `-Infinity` values. The remaining content must be one
  complete JSON object with no arbitrary prefix or trailing text. Arrays,
  incomplete JSON, invalid JSON, and wrapped prose are rejected.
- Accepted JSON is passed through the same `response_model.model_validate`;
  Pydantic validation is never bypassed.
- The fallback performs no provider call and adds no retry loop.
- Rejected content logs only a short type/length/marker summary and a reason;
  successful fallback logs only the same summary and bounded top-level keys.
  The full provider response is not written to the regular log.
- Existing bounded `IncompleteOutputException` token expansion remains
  unchanged in behavior.

## Verification

Commands:

```text
python -m pytest backend/tests/core/test_structured_output_runner.py backend/tests/core/test_planning_claim_provider_adapter.py -m "not e2e" -q
python -m pytest backend/tests/core/test_structured_output_runner.py -m "not e2e" -q
```

Results: **16 passed** for the original combined focused run; **23 passed**
for the updated structured-output runner focus.

The new structured runner cases cover:

- plain complete JSON with no tool calls;
- complete JSON preceded by `<think>` content;
- complete JSON inside a markdown fence;
- incomplete JSON;
- arrays and non-standard JSON constants;
- JSON followed by arbitrary text;
- JSON followed by `<think>`, prose interleaving, nested/non-outer fences, and
  think markers inside JSON strings;
- schema-invalid JSON.

The success cases assert that the provider is called exactly once. Failure
cases assert that the original `InstructorRetryException` remains raised, no
extra provider call occurs, and the complete content is absent from captured
warning arguments.

`python -m compileall` was also attempted for the two changed Python modules;
the test module's existing `__pycache__` target returned a Windows
`PermissionError`. The focused pytest run successfully imported and executed
the changed implementation and passed.
