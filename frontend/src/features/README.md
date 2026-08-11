# `src/features`

Feature-oriented frontend modules. Each feature owns its API adapters, state, components, hooks, and local types; shared UI primitives and application wiring stay outside the feature boundary.

Current feature modules are `planning` (the production planning workflow) and `gis-test` (development GIS validation). New workflow behavior should be added to the owning feature instead of extending a global store without a domain contract.
