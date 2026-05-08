from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..io import read_json, read_jsonl
from ..schemas import ValidationError


TASK_ID_RE = re.compile(r"\bFEISHU-\d+\b")


def extract_task_ids(value: Any) -> set[str]:
    ids: set[str] = set()
    if isinstance(value, str):
        ids.update(TASK_ID_RE.findall(value))
    elif isinstance(value, dict):
        for item in value.values():
            ids.update(extract_task_ids(item))
    elif isinstance(value, list):
        for item in value:
            ids.update(extract_task_ids(item))
    return ids


def allowed_task_ids_for_story_plan(
    *,
    case_context: dict[str, Any],
    story_plan: dict[str, Any],
) -> set[str]:
    target_task_id = str(case_context["task_id"])
    allowed = {target_task_id}
    family_id = str(case_context.get("family_id") or "")
    if family_id == "evidence_dependency_reasoning":
        return extract_task_ids(story_plan) | allowed
    if family_id != "anti_interference":
        return allowed
    allowed.update(task_id for task_id in extract_task_ids(story_plan) if task_id != target_task_id)
    return allowed


def validate_story_plan_task_ids(
    *,
    story_plan: dict[str, Any],
    case_context: dict[str, Any],
) -> dict[str, Any]:
    target_task_id = str(case_context["task_id"])
    issues: list[str] = []
    task = story_plan.get("task") or {}
    if str(task.get("task_id") or "") != target_task_id:
        issues.append(f"story_plan.task.task_id must be {target_task_id}")
    layout = story_plan.get("task_actor_layout") or {}
    if str(layout.get("target_task_id") or "") != target_task_id:
        issues.append(f"story_plan.task_actor_layout.target_task_id must be {target_task_id}")
    for index, row in enumerate(layout.get("actor_task_roles") or [], start=1):
        if (
            isinstance(row, dict)
            and row.get("task_id") is not None
            and str(row.get("task_id") or "") != target_task_id
        ):
            issues.append(f"story_plan.task_actor_layout.actor_task_roles[{index}].task_id must be {target_task_id}")
    for index, row in enumerate(story_plan.get("state_changes") or [], start=1):
        if isinstance(row, dict) and str(row.get("task_id") or "") != target_task_id:
            issues.append(f"story_plan.state_changes[{index}].task_id must be {target_task_id}")
    allowed_task_ids = allowed_task_ids_for_story_plan(case_context=case_context, story_plan=story_plan)
    for index, probe in enumerate(story_plan.get("planned_probe_queries") or [], start=1):
        if not isinstance(probe, dict):
            continue
        query = str(probe.get("query") or "")
        if target_task_id not in query:
            issues.append(f"story_plan.planned_probe_queries[{index}].query must mention {target_task_id}")
    non_target_ids = sorted(task_id for task_id in extract_task_ids(story_plan) if task_id != target_task_id)
    undeclared_ids = [task_id for task_id in non_target_ids if task_id not in allowed_task_ids]
    if undeclared_ids:
        issues.append(f"story_plan contains undeclared non-target task ids: {undeclared_ids}")
    if issues:
        raise ValidationError("; ".join(issues))
    return story_plan


def validate_conversation_plan_task_ids(
    *,
    artifact: dict[str, Any],
    case_context: dict[str, Any],
    allowed_task_ids: set[str],
) -> dict[str, Any]:
    target_task_id = str(case_context["task_id"])
    issues: list[str] = []
    if str(artifact.get("task_id") or "") != target_task_id:
        issues.append(f"conversation_plan_artifact.task_id must be {target_task_id}")
    observed_ids = extract_task_ids(artifact)
    invalid_ids = sorted(task_id for task_id in observed_ids if task_id not in allowed_task_ids)
    if invalid_ids:
        issues.append(f"conversation_plan_artifact contains undeclared task ids: {invalid_ids}")
    if issues:
        raise ValidationError("; ".join(issues))
    return artifact


def validate_gold_task_ids(
    *,
    case_context: dict[str, Any],
    query_benchmark: dict[str, Any] | None,
    semantic_gold: dict[str, Any] | None,
    allowed_task_ids: set[str] | None = None,
) -> list[str]:
    target_task_id = str(case_context["task_id"])
    allowed = allowed_task_ids or {target_task_id}
    issues: list[str] = []
    for label, artifact in (
        ("query_benchmark", query_benchmark),
        ("task_wiki_semantic_gold", semantic_gold),
    ):
        if not isinstance(artifact, dict):
            continue
        if artifact.get("task_id") and str(artifact.get("task_id")) != target_task_id:
            issues.append(f"{label}.task_id must be {target_task_id}")
        ids = extract_task_ids(artifact)
        invalid_ids = sorted(task_id for task_id in ids if task_id not in allowed)
        if invalid_ids:
            issues.append(f"{label} contains undeclared task ids: {invalid_ids}")
    return issues


def build_dataset_audit_report(case_path: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    try:
        case_context = read_json(case_path / "input" / "case_context.json")
        target_task_id = str(case_context.get("task_id") or "")
    except Exception as exc:
        return {
            "case_dir": str(case_path),
            "status": "failed",
            "issues": [{"code": "case_context_unreadable", "message": str(exc)}],
        }
    story_plan = read_json(case_path / "input" / "story_plan.json") if (case_path / "input" / "story_plan.json").exists() else None
    allowed_task_ids = {target_task_id}
    if story_plan is not None:
        try:
            validate_story_plan_task_ids(story_plan=story_plan, case_context=case_context)
            allowed_task_ids = allowed_task_ids_for_story_plan(case_context=case_context, story_plan=story_plan)
        except ValidationError as exc:
            issues.append({"code": "story_plan_task_id_mismatch", "message": str(exc)})
    else:
        issues.append({"code": "missing_story_plan", "message": "input/story_plan.json is missing"})

    for relative_path in (
        "input/case_context.json",
        "input/conversation_plan.json",
        "data/openclaw_message_ingress.jsonl",
        "data/collected_messages.jsonl",
        "gold/query_benchmark.json",
        "gold/task_wiki_semantic_gold.json",
        "gold/annotation_gold.jsonl",
    ):
        path = case_path / relative_path
        if not path.exists():
            if relative_path.startswith("gold/"):
                issues.append({"code": "missing_gold_artifact", "path": relative_path})
            continue
        try:
            artifact: Any = read_jsonl(path) if path.suffix == ".jsonl" else read_json(path)
        except Exception as exc:
            issues.append({"code": "artifact_unreadable", "path": relative_path, "message": str(exc)})
            continue
        ids = extract_task_ids(artifact)
        invalid_ids = sorted(task_id for task_id in ids if task_id not in allowed_task_ids)
        if invalid_ids:
            issues.append(
                {
                    "code": "undeclared_task_id",
                    "path": relative_path,
                    "task_ids": invalid_ids,
                    "allowed_task_ids": sorted(allowed_task_ids),
                }
            )

    observed_message_ids: set[str] = set()
    for relative_path in ("data/openclaw_message_ingress.jsonl", "data/collected_messages.jsonl"):
        path = case_path / relative_path
        if not path.exists():
            continue
        try:
            rows = read_jsonl(path)
        except Exception:
            continue
        for row in rows:
            message_id = str(row.get("message_id") or "")
            if message_id:
                observed_message_ids.add(message_id)
            message = row.get("message")
            if isinstance(message, dict) and message.get("message_id"):
                observed_message_ids.add(str(message["message_id"]))

    referenced_message_ids: set[str] = set()
    for relative_path in ("gold/query_benchmark.json", "gold/task_wiki_semantic_gold.json", "gold/annotation_gold.jsonl"):
        path = case_path / relative_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        referenced_message_ids.update(re.findall(r"\bom_[A-Za-z0-9_-]+\b", text))
    missing_message_ids = sorted(message_id for message_id in referenced_message_ids if message_id not in observed_message_ids)
    if missing_message_ids:
        issues.append(
            {
                "code": "missing_observed_message_id",
                "message_ids": missing_message_ids,
            }
        )

    return {
        "case_id": str(case_context.get("case_id") or case_path.name),
        "case_dir": str(case_path),
        "family_id": str(case_context.get("family_id") or ""),
        "task_id": target_task_id,
        "allowed_task_ids": sorted(allowed_task_ids),
        "status": "passed" if not issues else "failed",
        "issues": issues,
    }
