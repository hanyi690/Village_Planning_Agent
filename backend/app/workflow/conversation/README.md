# Conversation routing

Conversation nodes translate an incoming user command into a workflow control
decision. They may select the current phase or an explicit revision target, but
they do not produce business artifacts. `edges.py` routes only from checkpoint
state and typed gate artifacts; it never treats prose/history as authoritative
stage output.
