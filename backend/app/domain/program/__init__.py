"""Program domain package."""

_EXPORTS = {
    'assemble_planning_program': ('.assembler', 'assemble_planning_program'),
    'l3_aggregate': ('.aggregate', 'l3_aggregate'),
    'merge_program_fragments': ('.aggregate', 'merge_program_fragments'),
    'apply_classification_decisions': ('.classification', 'apply_classification_decisions'),
    'revise_program_with_decisions': ('.classification', 'revise_program_with_decisions'),
    'evaluate_l3_gate': ('.gate', 'evaluate_l3_gate'),
    'build_l3_review_package': ('.review', 'build_l3_review_package'),
    'analyze_l3_dimension': ('.worker', 'analyze_l3_dimension'),
    'interventions_from_claims': ('.claim_adapter', 'interventions_from_claims'),
}


def __getattr__(name: str):
    from importlib import import_module

    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute = _EXPORTS[name]
    return getattr(import_module(module_name, __name__), attribute)


__all__ = list(_EXPORTS)
