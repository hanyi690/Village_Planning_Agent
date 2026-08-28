# Workflow plan state

This package owns checkpoint-facing control projections: state construction,
layer completion, terminal diagnostics, and human interrupt preparation. Typed
business results stay in artifact storage and are referenced from workflow
state. A resume must identify the current interrupt and may only retry the
declared stage/dimension/input scope.
