# Workflow recovery

This package owns bounded recovery decisions that are common to L1, L2 and
L3. A worker supplies the exact failed dimension and its persisted retry
counter. The recovery policy may return only that dimension while its budget
remains.

Recovery does not reuse historical conversation content, invent a replacement
input, mutate an upstream artifact, or fan out an unrelated dimension. The
caller must carry the producer's current `source_digest`, `source_index_ref`,
`input_digest`, and validation feedback in the checkpoint failure record.

Business gate gaps use the same control surface through a typed
`RecoveryPointer`: `item_id` identifies the concrete gap, `source_artifact_ref`
identifies the current producer artifact, `source_input_refs` identify the
inputs that must be repaired or supplemented, and `return_stage` identifies
where the corrected artifact is re-evaluated. A failed Evidence Runtime call
is retained as HUMAN with this pointer; it is not converted into a provider
retry.
