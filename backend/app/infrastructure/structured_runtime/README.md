# Structured Runtime

The structured runtime is shared by every bounded LLM transaction. `parser.py`
handles provider output and failure classification, `validator.py` performs
schema/item validation, and `assembler.py` creates deterministic artifact
payloads and digests.

Business stages own the semantic schema and acceptance rules. They do not
implement provider retries, unconstrained parsing, token trimming, or artifact
assembly. A failed or partial structured transaction is returned as an
explicit diagnostic and can be retried at the smallest bounded unit.
