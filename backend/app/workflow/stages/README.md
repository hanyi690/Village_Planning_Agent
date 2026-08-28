# Workflow stage adapters

This directory is intentionally small. `support.py` contains checkpoint,
context adoption, gate persistence, retry, and completion helpers shared by
the workflow. `validate.py`, `reconcile.py`, and `deliver.py` are the terminal
control-plane stages because their contracts close the execution lifecycle.

The production implementations for TARGET_PROJECTION, GROUND, SELECT, and
EXECUTE live in their corresponding `backend/app/modules/*/stage.py` files.
The root graph imports those module stages only to determine order and route
gates; it does not own a second business implementation.
