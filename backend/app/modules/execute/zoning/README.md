# EXECUTE zoning adapters

This package contains zoning-specific execution/materialization helpers. It is
downstream of SELECT approval and upstream of VALIDATE; it does not own zoning
semantics, evidence retrieval, or human approval. Inputs are typed task and
candidate contracts, and outputs retain target IDs, source feature references,
operation names, and constraint status for validation.
