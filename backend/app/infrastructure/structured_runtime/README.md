# Structured Runtime

The structured runtime is shared by every bounded LLM transaction. `parser.py`
handles provider output and failure classification, `validator.py` performs
schema/item validation, and `assembler.py` creates deterministic artifact
payloads and digests.

Business stages own the semantic schema and acceptance rules. They do not
implement provider retries, unconstrained parsing, token trimming, or artifact
assembly. A failed or partial structured transaction is returned as an
explicit diagnostic and can be retried at the smallest bounded unit.

`consensus.py` owns bounded repeated typed calls and returns per-pass safe
diagnostics. Provider-specific reasoning transport (for example MiniMax
`reasoning_split`) is normalized by the parser/factory boundary. Reasoning is
never promoted to a DATA, World Model, or Evidence fact; only the validated
typed payload crosses into a business stage. Temporal role consensus remains
in DATA because it is a domain admission policy, not a provider protocol.
