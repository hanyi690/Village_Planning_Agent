# P2 Fix Round 2A

Baseline: `164496a9`

## Scope

Three targeted fixes only; unrelated user dirty files were preserved.

## Fixes

- SELECT now binds the same `MasterCertificate` payload to both `SolverCertificate.master_certificate` and the nested `BackendCertificatePayload.master_certificate`. A non-feasible master result (`bounded_infeasible` or `deferred`) clears formal scenario IDs and downgrades retained rows to provisional `partial` scenarios so the typed `ScenarioSet` remains constructible.
- `build_approved_execution_input`, `ApprovedExecutionInput.assert_matches`, and the EXECUTE approval boundary accept only the formal solver status `feasible`; `bounded` is no longer executable-equivalent.
- `network_readiness` fails closed for legacy objects. Callable routing/connectivity methods are insufficient: typed source binding, CRS, version, digest, source refs, nodes, and edge topology are required before readiness can be `ready`.

## Verification

Command:

```text
python -m pytest backend/tests/contracts/test_scenario_set_contracts.py backend/tests/core/test_p2_closure_contracts.py backend/tests/core/test_execute_approval_boundary.py -q --override-ini addopts=''
```

Result: `31 passed`.

Additional checks:

- `python -m compileall -q backend/app backend/tests` — passed.
- `git diff --check` — passed.

Added regression coverage for both non-feasible master statuses and for callable-only/complete-but-legacy network probes.
