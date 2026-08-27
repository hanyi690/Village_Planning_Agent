"""Assessment domain package."""

_EXPORTS = {
    'analyze_dimension': ('.analysis_node', 'analyze_dimension'),
    'DIMENSION_NAMES': ('.analysis_node', 'DIMENSION_NAMES'),
    'l1_aggregate': ('.aggregate', 'l1_aggregate'),
    'evaluate_l1_gate': ('.gate', 'evaluate_l1_gate'),
    'build_l1_review_package': ('.review', 'build_l1_review_package'),
}


def __getattr__(name: str):
    from importlib import import_module

    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute = _EXPORTS[name]
    return getattr(import_module(module_name, __name__), attribute)


__all__ = list(_EXPORTS)
