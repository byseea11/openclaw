"""Unified office dataset schemas and snapshot helpers.

This module treats real-office data as two canonical sources:

- employees.json: organization directory source of truth
- office_events.jsonl: immutable office event stream captured from Feishu

Everything else, including validation manifests and graph artifacts, is derived
from a frozen snapshot and must not mutate snapshot inputs in place.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.scorers.common import dump_json, dump_jsonl

EMPLOYEES_JSON = "employees.json"
EMPLOYEES_CSV = "employees.csv"
OFFICE_EVENTS_JSONL = "office_events.jsonl"
VALIDATION_MANIFEST_JSON = "validation_manifest.json"
VALIDATION_CANDIDATES_JSONL = "validation_candidates.jsonl"
SNAPSHOT_METADATA_JSON = "snapshot-metadata.json"
CAPTURE_METADATA_JSON = "capture-metadata.json"
SNAPSHOT_LOCK = "SNAPSHOT_LOCK"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sorted_unique_strings(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _normalize_refs(values: Any, *, field: str) -> list[dict[str, Any]]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    normalized: list[dict[str, Any]] = []
    for item in values:
        if isinstance(item, str):
            text = item.strip()
            if text:
                normalized.append({"id": text})
            continue
        if isinstance(item, dict):
            copied = {str(key): value for key, value in item.items()}
            identifier = str(copied.get("id") or copied.get("ref") or "").strip()
            if identifier:
                copied["id"] = identifier
                normalized.append(copied)
    normalized.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    return normalized


def _normalize_relations(values: Any) -> list[dict[str, Any]]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    normalized: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        relation_type = str(item.get("type") or "").strip()
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if not relation_type or not source or not target:
            continue
        normalized.append(
            {
                "type": relation_type,
                "source": source,
                "target": target,
                **{
                    str(key): value
                    for key, value in item.items()
                    if key not in {"type", "source", "target"}
                },
            }
        )
    normalized.sort(
        key=lambda item: (
            str(item.get("type") or ""),
            str(item.get("source") or ""),
            str(item.get("target") or ""),
            json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    )
    return normalized


def normalize_employee(row: dict[str, Any]) -> dict[str, Any]:
    employee_id = str(row.get("employee_id") or row.get("open_id") or "").strip()
    open_id = str(row.get("open_id") or employee_id).strip()
    if not employee_id or not open_id:
        raise ValueError("Employee rows require both employee_id and open_id.")
    return {
        "employee_id": employee_id,
        "open_id": open_id,
        "name": str(row.get("name") or "").strip(),
        "department_id": str(row.get("department_id") or "").strip(),
        "department_name": str(row.get("department_name") or "").strip(),
        "title": str(row.get("title") or "").strip(),
        "manager_id": str(row.get("manager_id") or "").strip(),
        "employment_status": str(row.get("employment_status") or "active").strip() or "active",
        "aliases": _sorted_unique_strings(row.get("aliases")),
        **{
            str(key): value
            for key, value in row.items()
            if key
            not in {
                "employee_id",
                "open_id",
                "name",
                "department_id",
                "department_name",
                "title",
                "manager_id",
                "employment_status",
                "aliases",
            }
        },
    }


def normalize_office_event(row: dict[str, Any], *, snapshot_id: str | None = None) -> dict[str, Any]:
    event_id = str(row.get("event_id") or row.get("message_id") or "").strip()
    if not event_id:
        raise ValueError("Office events require event_id or message_id.")
    normalized_snapshot_id = str(snapshot_id or row.get("snapshot_id") or "").strip()
    return {
        "event_id": event_id,
        "snapshot_id": normalized_snapshot_id,
        "workspace_id": str(row.get("workspace_id") or "").strip(),
        "chat_id": str(row.get("chat_id") or "").strip(),
        "thread_id": str(row.get("thread_id") or "").strip(),
        "message_id": str(row.get("message_id") or "").strip(),
        "reply_to_message_id": str(row.get("reply_to_message_id") or "").strip(),
        "event_time": str(row.get("event_time") or row.get("created_at") or "").strip(),
        "sender_open_id": str(row.get("sender_open_id") or "").strip(),
        "sender_name": str(row.get("sender_name") or "").strip(),
        "message_type": str(row.get("message_type") or "text").strip() or "text",
        "content_text": str(row.get("content_text") or "").strip(),
        "mentions": _sorted_unique_strings(row.get("mentions")),
        "attachments": _normalize_refs(row.get("attachments"), field="attachments"),
        "doc_refs": _normalize_refs(row.get("doc_refs"), field="doc_refs"),
        "task_refs": _normalize_refs(row.get("task_refs"), field="task_refs"),
        "approval_refs": _normalize_refs(row.get("approval_refs"), field="approval_refs"),
        "card_payload": row.get("card_payload"),
        "raw_event_ref": deepcopy(row.get("raw_event_ref") or {}),
        "direction": str(row.get("direction") or "").strip(),
        "chat_type": str(row.get("chat_type") or "").strip(),
        "entity_refs": _normalize_refs(row.get("entity_refs"), field="entity_refs"),
        "relations": _normalize_relations(row.get("relations")),
    }


def normalize_history_window(window: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_ids": _sorted_unique_strings(window.get("event_ids")),
        "start_event_id": str(window.get("start_event_id") or "").strip(),
        "end_event_id": str(window.get("end_event_id") or "").strip(),
        "start_time": str(window.get("start_time") or "").strip(),
        "end_time": str(window.get("end_time") or "").strip(),
        "chat_ids": _sorted_unique_strings(window.get("chat_ids")),
        "thread_ids": _sorted_unique_strings(window.get("thread_ids")),
        "max_events": int(window.get("max_events") or 0),
    }


def normalize_validation_case(row: dict[str, Any], *, snapshot_id: str | None = None) -> dict[str, Any]:
    case_id = str(row.get("case_id") or "").strip()
    if not case_id:
        raise ValueError("Validation cases require case_id.")
    normalized_snapshot_id = str(snapshot_id or row.get("snapshot_id") or "").strip()
    return {
        "case_id": case_id,
        "snapshot_id": normalized_snapshot_id,
        "history_window": normalize_history_window(dict(row.get("history_window") or {})),
        "question": str(row.get("question") or "").strip(),
        "expected_answer": str(row.get("expected_answer") or "").strip(),
        "evidence_event_ids": _sorted_unique_strings(row.get("evidence_event_ids")),
        "ability_tag": str(row.get("ability_tag") or "memory_recall").strip() or "memory_recall",
        **{
            str(key): value
            for key, value in row.items()
            if key
            not in {
                "case_id",
                "snapshot_id",
                "history_window",
                "question",
                "expected_answer",
                "evidence_event_ids",
                "ability_tag",
            }
        },
    }


def load_json_file(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl_file(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    file_path = Path(path)
    if not file_path.exists():
        return rows
    for line_no, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError(f"{file_path}:{line_no} must be a JSON object")
        rows.append(value)
    return rows


def load_employees(path: str | Path) -> list[dict[str, Any]]:
    payload = load_json_file(path)
    if isinstance(payload, dict):
        values = payload.get("employees", [])
    else:
        values = payload
    if not isinstance(values, list):
        raise ValueError("employees.json must be a JSON list or object with an employees array.")
    employees = [normalize_employee(dict(item)) for item in values if isinstance(item, dict)]
    employees.sort(key=lambda item: (item["employee_id"], item["open_id"]))
    return employees


def load_office_events(path: str | Path) -> list[dict[str, Any]]:
    events = [normalize_office_event(dict(item)) for item in load_jsonl_file(path)]
    events.sort(
        key=lambda item: (
            str(item.get("event_time") or ""),
            str(item.get("event_id") or ""),
        )
    )
    return events


def load_validation_manifest(path: str | Path) -> dict[str, Any]:
    payload = load_json_file(path)
    if not isinstance(payload, dict):
        raise ValueError("validation manifest must be a JSON object")
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("validation manifest cases must be a JSON array")
    normalized_cases = [
        normalize_validation_case(dict(item), snapshot_id=payload.get("snapshot_id"))
        for item in cases
        if isinstance(item, dict)
    ]
    return {
        "snapshot_id": str(payload.get("snapshot_id") or "").strip(),
        "cases": normalized_cases,
        **{
            str(key): value
            for key, value in payload.items()
            if key not in {"snapshot_id", "cases"}
        },
    }


def export_employees_csv(employees: list[dict[str, Any]], output_path: str | Path) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "employee_id",
        "open_id",
        "name",
        "department_id",
        "department_name",
        "title",
        "manager_id",
        "employment_status",
        "aliases",
    ]
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for employee in employees:
            writer.writerow(
                {
                    **{key: employee.get(key, "") for key in headers},
                    "aliases": "|".join(_sorted_unique_strings(employee.get("aliases"))),
                }
            )
    return target


@dataclass(frozen=True)
class SnapshotPaths:
    root_dir: Path
    snapshot_id: str

    @property
    def snapshot_dir(self) -> Path:
        return self.root_dir / "snapshots" / self.snapshot_id

    @property
    def employees_json(self) -> Path:
        return self.snapshot_dir / EMPLOYEES_JSON

    @property
    def employees_csv(self) -> Path:
        return self.snapshot_dir / EMPLOYEES_CSV

    @property
    def office_events_jsonl(self) -> Path:
        return self.snapshot_dir / OFFICE_EVENTS_JSONL

    @property
    def validation_manifest_json(self) -> Path:
        return self.snapshot_dir / VALIDATION_MANIFEST_JSON

    @property
    def snapshot_metadata_json(self) -> Path:
        return self.snapshot_dir / SNAPSHOT_METADATA_JSON

    @property
    def lock_file(self) -> Path:
        return self.snapshot_dir / SNAPSHOT_LOCK


def capture_dir(root_dir: str | Path, capture_id: str) -> Path:
    return Path(root_dir) / "captures" / capture_id


def snapshot_paths(root_dir: str | Path, snapshot_id: str) -> SnapshotPaths:
    return SnapshotPaths(root_dir=Path(root_dir), snapshot_id=snapshot_id)


def load_snapshot_bundle(root_dir: str | Path, snapshot_id: str) -> dict[str, Any]:
    paths = snapshot_paths(root_dir, snapshot_id)
    metadata = load_json_file(paths.snapshot_metadata_json)
    employees = load_employees(paths.employees_json)
    events = load_office_events(paths.office_events_jsonl)
    manifest = load_validation_manifest(paths.validation_manifest_json)
    return {
        "paths": paths,
        "metadata": metadata,
        "employees": employees,
        "events": events,
        "validation_manifest": manifest,
    }


def _event_stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    event_types = Counter(str(item.get("message_type") or "text") for item in events)
    chats = {str(item.get("chat_id") or "").strip() for item in events if str(item.get("chat_id") or "").strip()}
    threads = {
        str(item.get("thread_id") or "").strip()
        for item in events
        if str(item.get("thread_id") or "").strip()
    }
    return {
        "event_count": len(events),
        "chat_count": len(chats),
        "thread_count": len(threads),
        "message_type_counts": dict(sorted(event_types.items())),
        "time_range": {
            "start": min((str(item.get("event_time") or "") for item in events if item.get("event_time")), default=""),
            "end": max((str(item.get("event_time") or "") for item in events if item.get("event_time")), default=""),
        },
    }


def freeze_capture_to_snapshot(
    *,
    root_dir: str | Path,
    capture_id: str,
    snapshot_id: str,
    employees_path: str | Path,
    validation_manifest_path: str | Path | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    live_dir = capture_dir(root_dir, capture_id)
    events_path = live_dir / OFFICE_EVENTS_JSONL
    if not events_path.exists():
        raise FileNotFoundError(f"Missing live capture events: {events_path}")

    paths = snapshot_paths(root_dir, snapshot_id)
    if paths.snapshot_dir.exists():
        raise FileExistsError(
            f"Snapshot {snapshot_id} already exists at {paths.snapshot_dir}. Snapshots are immutable."
        )
    paths.snapshot_dir.mkdir(parents=True, exist_ok=False)

    employees = load_employees(employees_path)
    export_employees_csv(employees, paths.employees_csv)
    dump_json({"employees": employees}, paths.employees_json)

    events = [
        normalize_office_event(dict(item), snapshot_id=snapshot_id) for item in load_jsonl_file(events_path)
    ]
    if workspace_id:
        for event in events:
            event["workspace_id"] = workspace_id
    dump_jsonl(events, paths.office_events_jsonl)

    manifest_path = Path(validation_manifest_path) if validation_manifest_path else None
    if manifest_path and manifest_path.exists():
        manifest = load_validation_manifest(manifest_path)
    else:
        draft_path = live_dir / VALIDATION_MANIFEST_JSON
        manifest = load_validation_manifest(draft_path) if draft_path.exists() else {"cases": []}
    manifest["snapshot_id"] = snapshot_id
    manifest["cases"] = [
        normalize_validation_case(dict(item), snapshot_id=snapshot_id)
        for item in manifest.get("cases", [])
        if isinstance(item, dict)
    ]
    dump_json(manifest, paths.validation_manifest_json)

    capture_metadata_path = live_dir / CAPTURE_METADATA_JSON
    capture_metadata = load_json_file(capture_metadata_path) if capture_metadata_path.exists() else {}
    if not isinstance(capture_metadata, dict):
        capture_metadata = {}

    metadata = {
        "snapshot_id": snapshot_id,
        "capture_id": capture_id,
        "frozen_at": utc_now_iso(),
        "workspace_id": workspace_id or str(capture_metadata.get("workspace_id") or ""),
        "employees_version": {
            "employee_count": len(employees),
            "source_path": str(Path(employees_path)),
        },
        "validation_case_count": len(manifest.get("cases", [])),
        "capture_metadata": capture_metadata,
        "stats": _event_stats(events),
    }
    dump_json(metadata, paths.snapshot_metadata_json)
    paths.lock_file.write_text(
        f"snapshot_id={snapshot_id}\nfrozen_at={metadata['frozen_at']}\n",
        encoding="utf-8",
    )
    return metadata
