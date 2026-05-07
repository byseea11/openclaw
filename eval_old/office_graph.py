"""Deterministic graph derivation from a frozen office snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval_old.office_dataset import load_snapshot_bundle


def _entity_node_id(kind: str, value: str) -> str:
    return f"{kind}:{value}"


def _normalize_ref_id(kind: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if ":" in text:
        prefix, rest = text.split(":", 1)
        if prefix and rest:
            return f"{prefix}:{rest}"
    return f"{kind}:{text}"


def _ensure_node(nodes: dict[str, dict[str, Any]], *, node_id: str, kind: str, label: str | None = None, **extra: Any) -> None:
    if not node_id:
        return
    existing = nodes.get(node_id)
    payload = {
        "id": node_id,
        "kind": kind,
        "label": label or node_id,
        **extra,
    }
    if existing is None:
        nodes[node_id] = payload
        return
    for key, value in payload.items():
        current = existing.get(key)
        if key not in existing or current in ("", None) or current == []:
            existing[key] = value


def _ensure_edge(
    edges: dict[str, dict[str, Any]],
    *,
    edge_type: str,
    source: str,
    target: str,
    evidence_event_id: str | None = None,
    **extra: Any,
) -> None:
    if not source or not target:
        return
    edge_id = f"{edge_type}:{source}->{target}"
    existing = edges.get(edge_id)
    payload = {
        "id": edge_id,
        "type": edge_type,
        "source": source,
        "target": target,
        "evidence_event_ids": [evidence_event_id] if evidence_event_id else [],
        **extra,
    }
    if existing is None:
        edges[edge_id] = payload
        return
    evidence_ids = set(existing.get("evidence_event_ids", []))
    if evidence_event_id:
        evidence_ids.add(evidence_event_id)
    existing["evidence_event_ids"] = sorted(evidence_ids)
    for key, value in payload.items():
        if key in {"id", "type", "source", "target", "evidence_event_ids"}:
            continue
        current = existing.get(key)
        if key not in existing or current in ("", None) or current == []:
            existing[key] = value


def build_snapshot_graph(*, root_dir: str, snapshot_id: str) -> dict[str, Any]:
    bundle = load_snapshot_bundle(root_dir, snapshot_id)
    employees = bundle["employees"]
    events = bundle["events"]
    metadata = bundle["metadata"]

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    for employee in employees:
        employee_node = _entity_node_id("employee", employee["open_id"])
        _ensure_node(
            nodes,
            node_id=employee_node,
            kind="employee",
            label=employee.get("name") or employee["open_id"],
            employee_id=employee["employee_id"],
            open_id=employee["open_id"],
            title=employee.get("title") or "",
            employment_status=employee.get("employment_status") or "",
        )
        department_id = str(employee.get("department_id") or "").strip()
        if department_id:
            department_node = _entity_node_id("department", department_id)
            _ensure_node(
                nodes,
                node_id=department_node,
                kind="department",
                label=employee.get("department_name") or department_id,
                department_id=department_id,
                department_name=employee.get("department_name") or "",
            )
            _ensure_edge(
                edges,
                edge_type="belongs_to_department",
                source=employee_node,
                target=department_node,
            )
        manager_id = str(employee.get("manager_id") or "").strip()
        if manager_id:
            manager_node = _entity_node_id("employee", manager_id)
            _ensure_node(nodes, node_id=manager_node, kind="employee", label=manager_id, open_id=manager_id)
            _ensure_edge(edges, edge_type="reports_to", source=employee_node, target=manager_node)

    for event in events:
        event_id = str(event.get("event_id") or "")
        message_id = str(event.get("message_id") or event_id)
        message_node = _entity_node_id("message", message_id or event_id)
        _ensure_node(
            nodes,
            node_id=message_node,
            kind="message",
            label=message_id or event_id,
            event_id=event_id,
            message_type=event.get("message_type") or "",
            event_time=event.get("event_time") or "",
        )

        chat_id = str(event.get("chat_id") or "").strip()
        if chat_id:
            chat_node = _entity_node_id("chat", chat_id)
            _ensure_node(nodes, node_id=chat_node, kind="chat", label=chat_id, chat_id=chat_id)
            _ensure_edge(
                edges,
                edge_type="posted_in_chat",
                source=message_node,
                target=chat_node,
                evidence_event_id=event_id,
            )

        thread_id = str(event.get("thread_id") or "").strip()
        if thread_id:
            thread_node = _entity_node_id("thread", thread_id)
            _ensure_node(nodes, node_id=thread_node, kind="thread", label=thread_id, thread_id=thread_id)
            _ensure_edge(
                edges,
                edge_type="belongs_to_thread",
                source=message_node,
                target=thread_node,
                evidence_event_id=event_id,
            )
            if chat_id:
                _ensure_edge(
                    edges,
                    edge_type="thread_in_chat",
                    source=thread_node,
                    target=_entity_node_id("chat", chat_id),
                    evidence_event_id=event_id,
                )

        reply_to_message_id = str(event.get("reply_to_message_id") or "").strip()
        if reply_to_message_id:
            reply_node = _entity_node_id("message", reply_to_message_id)
            _ensure_node(nodes, node_id=reply_node, kind="message", label=reply_to_message_id)
            _ensure_edge(
                edges,
                edge_type="reply_to",
                source=message_node,
                target=reply_node,
                evidence_event_id=event_id,
            )

        sender_open_id = str(event.get("sender_open_id") or "").strip()
        if sender_open_id:
            sender_node = _entity_node_id("employee", sender_open_id)
            _ensure_node(
                nodes,
                node_id=sender_node,
                kind="employee",
                label=event.get("sender_name") or sender_open_id,
                open_id=sender_open_id,
            )
            _ensure_edge(
                edges,
                edge_type="sent_message",
                source=sender_node,
                target=message_node,
                evidence_event_id=event_id,
            )
            if chat_id:
                _ensure_edge(
                    edges,
                    edge_type="member_of_chat",
                    source=sender_node,
                    target=_entity_node_id("chat", chat_id),
                    evidence_event_id=event_id,
                )

        for mentioned in event.get("mentions", []) or []:
            mentioned_id = str(mentioned).strip()
            if not mentioned_id:
                continue
            mention_node = _entity_node_id("employee", mentioned_id)
            _ensure_node(nodes, node_id=mention_node, kind="employee", label=mentioned_id, open_id=mentioned_id)
            _ensure_edge(
                edges,
                edge_type="mentions",
                source=message_node,
                target=mention_node,
                evidence_event_id=event_id,
            )

        for doc_ref in event.get("doc_refs", []) or []:
            doc_id = str(doc_ref.get("id") or "").strip()
            if not doc_id:
                continue
            doc_node = _normalize_ref_id("doc", doc_id)
            _ensure_node(nodes, node_id=doc_node, kind="doc", label=doc_id)
            _ensure_edge(
                edges,
                edge_type="references_doc",
                source=message_node,
                target=doc_node,
                evidence_event_id=event_id,
            )

        for attachment in event.get("attachments", []) or []:
            attachment_id = str(attachment.get("id") or "").strip()
            if not attachment_id:
                continue
            attachment_node = _normalize_ref_id("file", attachment_id)
            _ensure_node(nodes, node_id=attachment_node, kind="file", label=attachment_id)
            _ensure_edge(
                edges,
                edge_type="attached_file",
                source=message_node,
                target=attachment_node,
                evidence_event_id=event_id,
            )

        for task in event.get("task_refs", []) or []:
            task_id = str(task.get("id") or "").strip()
            if not task_id:
                continue
            task_node = _normalize_ref_id("task", task_id)
            _ensure_node(
                nodes,
                node_id=task_node,
                kind="task",
                label=task_id,
                status=task.get("status") or "",
            )
            _ensure_edge(
                edges,
                edge_type="references_task",
                source=message_node,
                target=task_node,
                evidence_event_id=event_id,
            )
            owner_open_id = str(task.get("owner_open_id") or task.get("owner_id") or "").strip()
            if owner_open_id:
                owner_node = _entity_node_id("employee", owner_open_id)
                _ensure_node(nodes, node_id=owner_node, kind="employee", label=owner_open_id, open_id=owner_open_id)
                _ensure_edge(
                    edges,
                    edge_type="owns_task",
                    source=owner_node,
                    target=task_node,
                    evidence_event_id=event_id,
                )
            blocked_by = str(task.get("blocked_by") or "").strip()
            if blocked_by:
                blocker_node = _normalize_ref_id(
                    "approval" if blocked_by.upper().startswith("AP-") else "task",
                    blocked_by,
                )
                blocker_kind = "approval" if blocker_node.startswith("approval:") else "task"
                _ensure_node(nodes, node_id=blocker_node, kind=blocker_kind, label=blocked_by)
                _ensure_edge(
                    edges,
                    edge_type="blocked_by",
                    source=task_node,
                    target=blocker_node,
                    evidence_event_id=event_id,
                )
            if str(task.get("status") or "").strip():
                _ensure_edge(
                    edges,
                    edge_type="updates_status_of",
                    source=message_node,
                    target=task_node,
                    evidence_event_id=event_id,
                    status=str(task.get("status") or "").strip(),
                )

        for approval in event.get("approval_refs", []) or []:
            approval_id = str(approval.get("id") or "").strip()
            if not approval_id:
                continue
            approval_node = _normalize_ref_id("approval", approval_id)
            _ensure_node(
                nodes,
                node_id=approval_node,
                kind="approval",
                label=approval_id,
                status=approval.get("status") or "",
            )
            _ensure_edge(
                edges,
                edge_type="references_approval",
                source=message_node,
                target=approval_node,
                evidence_event_id=event_id,
            )
            approved_by = str(approval.get("approved_by") or approval.get("approver_open_id") or "").strip()
            if approved_by:
                approver_node = _entity_node_id("employee", approved_by)
                _ensure_node(
                    nodes,
                    node_id=approver_node,
                    kind="employee",
                    label=approved_by,
                    open_id=approved_by,
                )
                _ensure_edge(
                    edges,
                    edge_type="approved_by",
                    source=approval_node,
                    target=approver_node,
                    evidence_event_id=event_id,
                )
            if str(approval.get("status") or "").strip():
                _ensure_edge(
                    edges,
                    edge_type="updates_status_of",
                    source=message_node,
                    target=approval_node,
                    evidence_event_id=event_id,
                    status=str(approval.get("status") or "").strip(),
                )

        for relation in event.get("relations", []) or []:
            relation_type = str(relation.get("type") or "").strip()
            source = str(relation.get("source") or "").strip()
            target = str(relation.get("target") or "").strip()
            if not relation_type or not source or not target:
                continue
            source_kind = source.split(":", 1)[0]
            target_kind = target.split(":", 1)[0]
            _ensure_node(nodes, node_id=source, kind=source_kind, label=source.split(":", 1)[-1])
            _ensure_node(nodes, node_id=target, kind=target_kind, label=target.split(":", 1)[-1])
            _ensure_edge(
                edges,
                edge_type=relation_type,
                source=source,
                target=target,
                evidence_event_id=event_id,
            )

    return {
        "snapshot_id": snapshot_id,
        "metadata": {
            "source_snapshot": metadata,
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": [
            edges[key]
            for key in sorted(
                edges,
                key=lambda item: (
                    str(edges[item].get("type") or ""),
                    str(edges[item].get("source") or ""),
                    str(edges[item].get("target") or ""),
                    item,
                ),
            )
        ],
    }


def dump_snapshot_graph(*, root_dir: str, snapshot_id: str, output_path: str) -> dict[str, Any]:
    graph = build_snapshot_graph(root_dir=root_dir, snapshot_id=snapshot_id)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    return graph
