# RECONCILE / DELIVER contracts

This package owns the typed outputs of the final workflow boundary:
reconciliation coverage, final manifest, target deferrals, delivery gates,
deliverables, traceability entries, and spatial delivery references.

`FinalManifest` is produced by RECONCILE and `DeliveryManifest` is produced by
DELIVER. Neither contract promotes missing or failed upstream artifacts to a
successful result. Spatial layer references identify already materialized
artifacts; they do not permit an LLM or a delivery renderer to create geometry.

The package contains contracts only. Reconciliation, delivery checks,
rendering, and export remain owned by `workflow/delivery/` and the
infrastructure export/rendering adapters.
