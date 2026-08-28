# Artifact reference contracts

This package owns the storage-neutral artifact identity and shared metadata
used by every stage. Stage payload schemas live in their business-owner
packages (`l1`, `l2`, `l3`, `evidence`, `execute`, `validation`, and
`delivery`); workflow state stores references rather than duplicating those
payloads.
