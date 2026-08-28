# VALIDATE contracts

This package owns the typed boundary between EXECUTE, VALIDATE, and the
downstream reconciliation gate. `ValidationReport` and its checks describe
what was inspected and which differences were found; `ValidationCertificate`
binds that inspection to the exact approved input, execution result, planned
state, context version, and input fingerprints.

The package does not run validation, repair a plan, or decide delivery. Those
behaviors remain in `workflow/validation/` and `workflow/stages/validate.py`.
Every certificate is therefore evidence of a deterministic inspection, not a
completion flag. Failed, partial, and blocked states remain representable.
