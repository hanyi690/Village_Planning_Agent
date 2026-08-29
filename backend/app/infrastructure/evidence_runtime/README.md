# Evidence Runtime

This is the single retrieval execution platform. It receives a compiled
`EvidenceRequirement`/`ExplorationRequest` from the business Evidence facade
and performs query planning, provider routing, Bundle/KG/Report/GIS/RAG/
external retrieval, normalization, fusion, provenance recording, coverage,
sufficiency, caching, budget enforcement, and provider degradation.

`modules/evidence/` owns the meaning of evidence and the conditions under
which a gap blocks a stage. This directory owns only how a request is
executed. L1, L2, L3, TARGET_PROJECTION, GROUND, and SELECT must not import a
retriever implementation directly.

The runtime returns typed evidence packets with query fingerprints, source
locators, provenance, coverage, sufficiency, and unresolved gaps. The packet
is bounded and can be persisted/reloaded through the common artifact runtime.
GROUND may pass a typed spatial specification and candidate-page cursor through
the Evidence facade; those values constrain one runtime request and do not
expose retriever/provider selection to the business module.

## Current-source retrieval boundary

``dimension_key`` identifies the business owner of a request. It is not a hard
source partition. The local-text retriever first hydrates the current session's
canonical ``PlanningContext`` when the process cache is cold, then performs a
bounded grep-like search over the complete current input documents. A dimension
request can therefore find supporting text written under another dimension,
and a gap-resolution request can search the project-wide source corpus. No
history session is consulted.

Lexical matching is candidate recall only. The retriever returns the exact
bounded source span, source key, content digest, and locator as ``needs_review``
evidence. It does not use regular expressions to extract numbers, does not
normalize business meaning, and does not create missing values. The owning
business module may send these source spans to a bounded LLM extraction call
and must validate the resulting typed item against the returned provenance
before assembling an artifact.

L1 typed facts follow the same boundary: spatial facts are cross-dimension
identity evidence, while project-wide or gap-resolution requests may also
select matching non-spatial facts from another dimension. A strict dimension
view remains available only to an explicit caller that needs it.

An entity scope such as ``facilities`` or ``roads`` is a retrieval hint and
does not by itself authorize geometry/Bundle/KG retrieval. Those spatial
retrievers are selected only by an explicit ``spatial_lookup`` or typed
spatial requirement; demographic, industrial, policy, and other factual gaps
remain text/evidence requests even when a caller supplies a business scope.

Snapshot-scoped source-semantic classification, its bounded classifier, and
the semantic snapshot store also belong to this runtime. TARGET_PROJECTION
consumes their typed result through the current source-semantic path.

The source-semantic classifier consumes the same Context Runtime table wire
format as the other LLM boundaries. GIS ``properties``/raw fields and KG RDF
predicate/value pairs are projected into the common attribute column after
source identity, geometry, and layer metadata are removed. Field names are
not a village-specific whitelist: arbitrary business attributes are retained
for model reasoning, while rows with no interpretable semantic value remain
explicitly unresolved and do not consume provider calls.
