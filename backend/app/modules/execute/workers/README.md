# EXECUTE workers

Workers are deterministic materializers for one approved execution task. Each
worker accepts the typed `ExecutionPlan` task payload, reads only the current
bundle/spatial runtime ports, and returns a typed result with source and task
lineage. `facility.py`, `road.py`, `zone.py`, `axis.py`, `action.py`, and
`project.py` are worker implementations; they do not decide approval, routing,
candidate ranking, or final delivery status.

The parent `modules/execute/application.py` schedules tasks and reconciles
worker results. A worker may return a partial or blocked result, but it must
never invent geometry, promote a rejected candidate, or bypass the approval
boundary. Geometry and derived fields must point to an authoritative bundle or
an explicit deterministic operation.
