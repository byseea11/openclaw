from __future__ import annotations

from typing import Any

from ..family_catalog import get_family_definition
from ..schemas import validate_memory_capability_brief


def build_memory_capability_brief(*, family_id: str) -> dict[str, Any]:
    definition = get_family_definition(family_id)
    payload = {
        "family_id": definition.family_id,
        "benchmark_requirement_name": definition.benchmark_requirement_name,
        "benchmark_requirement_summary": definition.benchmark_requirement_summary,
        "report_display_name": definition.report_display_name,
        "capability_under_test": definition.capability_under_test,
        "why_memory_systems_may_fail": definition.why_memory_systems_may_fail,
        "generation_rules": definition.generation_rules,
        "required_case_structure": definition.required_case_structure,
        "probe_strategy": definition.probe_strategy,
        "expected_good_system_behavior": definition.expected_good_system_behavior,
    }
    return validate_memory_capability_brief(payload)
