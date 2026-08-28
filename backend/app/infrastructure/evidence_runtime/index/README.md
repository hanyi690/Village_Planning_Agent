# Evidence indexes

Indexes make current source segments/features addressable by stable IDs and
support deterministic evidence scoring and resolution coverage. Index lookups
must remain scoped to the current source snapshot and preserve source refs;
they are not a semantic fact generator and do not read historical sessions.
