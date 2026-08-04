"""Dependency-inversion ports for planning-contract adapters.

Ports are Protocol-based interfaces. The ports package itself imports only
lightweight schema types; it must not import heavy dependencies (e.g. network,
storage, RDF) to avoid import cycles.
"""
