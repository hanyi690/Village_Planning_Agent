# Layer orchestration

Layer nodes dispatch L1/L2/L3 dimensions, fan results into the completion
check, and invoke the corresponding module aggregate. They own phase ordering,
dependency readiness, provider recovery routing, and layer boundaries. They do
not implement evidence retrieval, context construction, or domain extraction.
