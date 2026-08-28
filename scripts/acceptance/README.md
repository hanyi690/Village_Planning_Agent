# Runtime acceptance probes

This directory contains small executable probes for the canonical business
stages. They are intentionally not pytest suites and do not import the
removed historical test tree. A probe starts from a real persisted session or
real local input, exercises the production facade, reloads typed artifacts,
and exits non-zero when an ownership or persistence invariant fails.

Probe output is diagnostic evidence only. A stage is not considered complete
from a probe alone: the migration record must also show a real downstream
consumer and the required failure/recovery behavior.
