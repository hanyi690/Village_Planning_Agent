# L3 / claims boundary

The L3 worker returns one `PlanningClaimSet` per dimension. Claims carry
evidence, affected references, quantity, location hints, and uncertainty, but
are not executable planning objects.

`l3_aggregate` deterministically adapts claims to non-authoritative
`ProgramProposal` candidates and calls `domain/program/assembler.py` exactly
once. Demand, suitability, allocation, classification, geometry, and BSM
decisions remain downstream domain responsibilities.

Legacy Markdown/`INSTRUCTION` extraction is removed from this boundary.
