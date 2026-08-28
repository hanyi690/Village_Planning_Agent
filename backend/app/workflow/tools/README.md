# Workflow tool bridge

These adapters expose explicitly requested workflow tools to the graph. They
translate tool input into module/runtime calls and preserve typed artifact
references. They are not an alternate business service layer and must not
perform hidden retrieval, context assembly, or synthetic result generation.
