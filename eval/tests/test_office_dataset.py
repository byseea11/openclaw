from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eval.office_dataset import (
    CAPTURE_METADATA_JSON,
    EMPLOYEES_JSON,
    OFFICE_EVENTS_JSONL,
    SNAPSHOT_METADATA_JSON,
    VALIDATION_MANIFEST_JSON,
    freeze_capture_to_snapshot,
    load_snapshot_bundle,
)
from eval.office_graph import build_snapshot_graph


class OfficeDatasetTests(unittest.TestCase):
    def test_freeze_snapshot_is_immutable_and_exports_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            capture_dir = root / "captures" / "capture-a"
            capture_dir.mkdir(parents=True)
            (capture_dir / OFFICE_EVENTS_JSONL).write_text(
                json.dumps(
                    {
                        "event_id": "evt-1",
                        "workspace_id": "ws-1",
                        "chat_id": "oc_chat",
                        "message_id": "om_1",
                        "event_time": "2026-04-25T09:00:00Z",
                        "sender_open_id": "ou_alice",
                        "message_type": "text",
                        "content_text": "TASK-1 is blocked by AP-2",
                        "task_refs": [{"id": "TASK-1", "blocked_by": "AP-2"}],
                        "approval_refs": [{"id": "AP-2", "status": "pending"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (capture_dir / CAPTURE_METADATA_JSON).write_text(
                json.dumps({"workspace_id": "ws-1"}),
                encoding="utf-8",
            )
            employees_path = root / EMPLOYEES_JSON
            employees_path.write_text(
                json.dumps(
                    {
                        "employees": [
                            {
                                "employee_id": "emp-1",
                                "open_id": "ou_alice",
                                "name": "Alice",
                                "department_id": "dept-1",
                                "department_name": "Product",
                                "title": "PM",
                                "manager_id": "ou_manager",
                                "employment_status": "active",
                                "aliases": ["alice@pm"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            validation_path = root / VALIDATION_MANIFEST_JSON
            validation_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "case-1",
                                "history_window": {"event_ids": ["evt-1"]},
                                "question": "What blocks TASK-1?",
                                "expected_answer": "AP-2",
                                "evidence_event_ids": ["evt-1"],
                                "ability_tag": "blocked_by",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            metadata = freeze_capture_to_snapshot(
                root_dir=root,
                capture_id="capture-a",
                snapshot_id="snapshot-1",
                employees_path=employees_path,
                validation_manifest_path=validation_path,
            )
            self.assertEqual(metadata["snapshot_id"], "snapshot-1")
            bundle = load_snapshot_bundle(root, "snapshot-1")
            self.assertEqual(bundle["metadata"]["snapshot_id"], "snapshot-1")
            self.assertEqual(len(bundle["employees"]), 1)
            self.assertEqual(len(bundle["events"]), 1)
            self.assertEqual(len(bundle["validation_manifest"]["cases"]), 1)
            self.assertTrue((root / "snapshots" / "snapshot-1" / SNAPSHOT_METADATA_JSON).exists())
            self.assertTrue((root / "snapshots" / "snapshot-1" / "employees.csv").exists())

            with self.assertRaises(FileExistsError):
                freeze_capture_to_snapshot(
                    root_dir=root,
                    capture_id="capture-a",
                    snapshot_id="snapshot-1",
                    employees_path=employees_path,
                )

    def test_graph_build_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot_dir = root / "snapshots" / "snapshot-graph"
            snapshot_dir.mkdir(parents=True)
            (snapshot_dir / EMPLOYEES_JSON).write_text(
                json.dumps(
                    {
                        "employees": [
                            {
                                "employee_id": "emp-1",
                                "open_id": "ou_alice",
                                "name": "Alice",
                                "department_id": "dept-1",
                                "department_name": "Product",
                                "title": "PM",
                                "manager_id": "ou_bob",
                                "employment_status": "active",
                                "aliases": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (snapshot_dir / "employees.csv").write_text("", encoding="utf-8")
            (snapshot_dir / OFFICE_EVENTS_JSONL).write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "event_id": "evt-1",
                                "snapshot_id": "snapshot-graph",
                                "chat_id": "oc_chat",
                                "message_id": "om_1",
                                "event_time": "2026-04-25T09:00:00Z",
                                "sender_open_id": "ou_alice",
                                "message_type": "text",
                                "content_text": "TASK-1 is blocked by AP-2",
                                "task_refs": [{"id": "TASK-1", "blocked_by": "AP-2"}],
                                "approval_refs": [{"id": "AP-2", "approved_by": "ou_bob"}],
                                "mentions": ["ou_bob"],
                            }
                        )
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (snapshot_dir / VALIDATION_MANIFEST_JSON).write_text(
                json.dumps({"snapshot_id": "snapshot-graph", "cases": []}),
                encoding="utf-8",
            )
            (snapshot_dir / SNAPSHOT_METADATA_JSON).write_text(
                json.dumps({"snapshot_id": "snapshot-graph"}),
                encoding="utf-8",
            )

            graph_a = build_snapshot_graph(root_dir=str(root), snapshot_id="snapshot-graph")
            graph_b = build_snapshot_graph(root_dir=str(root), snapshot_id="snapshot-graph")
            self.assertEqual(graph_a, graph_b)
            edge_types = {edge["type"] for edge in graph_a["edges"]}
            self.assertIn("blocked_by", edge_types)
            self.assertIn("approved_by", edge_types)


if __name__ == "__main__":
    unittest.main()
