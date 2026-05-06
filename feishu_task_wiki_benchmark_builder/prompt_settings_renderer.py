from __future__ import annotations

from typing import Any

from .builder_settings import (
    load_builder_settings,
    resolve_default_difficulty,
    resolve_difficulty_settings,
    resolve_family_constraints,
    resolve_topology_defaults,
)
from .config import FORMAL_FAMILY_IDS


def _render_difficulty_section(difficulty: str) -> list[str]:
    profile = resolve_difficulty_settings(difficulty)
    return [
        f"- 当前 difficulty: `{difficulty}`",
        f"- `department_count`: {profile['department_count']}",
        f"- `character_count_min/max`: {profile['character_count_min']} / {profile['character_count_max']}",
        f"- `require_cross_source_revision`: {str(profile['require_cross_source_revision']).lower()}",
        f"- `session_blueprint`: {', '.join(profile['session_blueprint'])}",
    ]


def _render_family_section(family_id: str) -> list[str]:
    constraint = resolve_family_constraints(family_id)
    lines = [f"### Family Constraints: `{family_id}`"]
    if family_id == "anti_interference":
        lines.extend(
            [
                f"- `min_interference_context_blocks`: {constraint['min_interference_context_blocks']}",
                f"- `min_shared_actors`: {constraint['min_shared_actors']}",
                f"- `required_noise_types`: {', '.join(constraint['required_noise_types'])}",
            ]
        )
    elif family_id == "contradiction_update":
        lines.extend(
            [
                f"- `min_state_tracks`: {constraint['min_state_tracks']}",
                f"- `min_stale_states`: {constraint['min_stale_states']}",
                f"- `required_supersession_clues`: {', '.join(constraint['required_supersession_clues'])}",
            ]
        )
    elif family_id == "evidence_dependency_reasoning":
        lines.extend(
            [
                f"- `min_dependency_hops`: {constraint['min_dependency_hops']}",
                f"- `min_cross_source_updates`: {constraint['min_cross_source_updates']}",
                f"- `required_evidence_roles`: {', '.join(constraint['required_evidence_roles'])}",
            ]
        )
    return lines


def render_prompt_settings_summary(*, stage: str, difficulty: str, family_id: str | None = None) -> str:
    if not difficulty:
        difficulty = resolve_default_difficulty()
    load_builder_settings()
    topology_defaults = resolve_topology_defaults()
    sections: list[str] = [
        "## Builder Settings Summary",
        "以下设置来自 `builder_settings.yml`，是当前阶段必须服从的规模与复杂度控制面。",
        "### Difficulty Profile",
        *_render_difficulty_section(difficulty),
        "### Topology Defaults",
        f"- `shared_actor_slot_suggestions`: {', '.join(topology_defaults['shared_actor_slot_suggestions'])}",
        f"- `external_context_types`: {', '.join(topology_defaults['external_context_types'])}",
        f"- `lateral_session_types`: {', '.join(topology_defaults['lateral_session_types'])}",
    ]
    if family_id is not None:
        sections.extend(_render_family_section(family_id))
    elif stage == "case-context":
        sections.append("### Formal Family Constraints")
        for item in FORMAL_FAMILY_IDS:
            sections.extend(_render_family_section(item))
    return "\n".join(sections)
