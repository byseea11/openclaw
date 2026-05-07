from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from eval_old.office_dataset import (
    EMPLOYEES_CSV,
    EMPLOYEES_JSON,
    OFFICE_EVENTS_JSONL,
    SNAPSHOT_LOCK,
    VALIDATION_MANIFEST_JSON,
    load_snapshot_bundle,
)
from eval_old.office_fixture_dataset import ACME_Q2_OPS_SNAPSHOT_ID, write_acme_q2_ops_snapshot
from eval_old.office_fixture_dataset_zh import (
    YUNHE_Q2_OPS_ZH_SNAPSHOT_ID,
    write_yunhe_q2_ops_zh_snapshot,
)
from eval_old.office_graph import build_snapshot_graph
from eval_old.scripts.inject_office_snapshot_to_feishu import inject_snapshot_to_feishu


class OfficeFixtureDatasetTests(unittest.TestCase):
    def assert_snapshot_has_expected_shape(self, snapshot_id: str) -> None:
        bundle = load_snapshot_bundle("eval/office_dataset", snapshot_id)
        employees = bundle["employees"]
        events = bundle["events"]
        cases = bundle["validation_manifest"]["cases"]
        metadata = bundle["metadata"]

        self.assertEqual(len(employees), 22)
        self.assertGreaterEqual(len(events), 90)
        self.assertLessEqual(len(events), 120)
        self.assertEqual(len(cases), 14)
        self.assertEqual(metadata["stats"]["chat_count"], 7)
        self.assertEqual(metadata["stats"]["thread_count"], 7)
        self.assertEqual(
            set(metadata["coverage"]["message_types"]),
            {"approval", "bot_notice", "card", "comment", "document", "file", "post", "system", "text"},
        )
        self.assertTrue(
            Path("eval/office_dataset/snapshots/acme_q2_ops_v1", SNAPSHOT_LOCK).exists()
        )

        event_ids = {event["event_id"] for event in events}
        employee_open_ids = {employee["open_id"] for employee in employees}
        department_ids = {employee["department_id"] for employee in employees}

        self.assertEqual(len(event_ids), len(events))
        self.assertGreaterEqual(len(department_ids), 9)
        for employee in employees:
            manager_id = employee.get("manager_id")
            if manager_id:
                self.assertIn(manager_id, employee_open_ids)

        for event in events:
            self.assertIn(event["sender_open_id"], employee_open_ids)
            for mention in event.get("mentions", []):
                self.assertIn(mention, employee_open_ids)
            for task in event.get("task_refs", []):
                owner = task.get("owner_open_id")
                if owner:
                    self.assertIn(owner, employee_open_ids)
            for approval in event.get("approval_refs", []):
                approver = approval.get("approved_by")
                if approver:
                    self.assertIn(approver, employee_open_ids)

        for case in cases:
            self.assertEqual(case["snapshot_id"], snapshot_id)
            self.assertTrue(case["evidence_event_ids"])
            for event_id in case["evidence_event_ids"]:
                self.assertIn(event_id, event_ids)

    def assert_employee_json_and_csv_are_consistent(self, snapshot_id: str) -> None:
        snapshot_dir = Path("eval/office_dataset/snapshots", snapshot_id)
        employees_payload = json.loads((snapshot_dir / EMPLOYEES_JSON).read_text(encoding="utf-8"))
        employees = employees_payload["employees"]
        with (snapshot_dir / EMPLOYEES_CSV).open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), len(employees))
        row_by_employee_id = {row["employee_id"]: row for row in rows}
        for employee in employees:
            row = row_by_employee_id[employee["employee_id"]]
            self.assertEqual(row["open_id"], employee["open_id"])
            self.assertEqual(row["name"], employee["name"])
            self.assertEqual(row["department_id"], employee["department_id"])
            self.assertEqual(row["manager_id"], employee["manager_id"])
            self.assertEqual(row["aliases"], "|".join(employee["aliases"]))

    def test_committed_acme_snapshot_has_expected_shape(self) -> None:
        self.assert_snapshot_has_expected_shape(ACME_Q2_OPS_SNAPSHOT_ID)

    def test_committed_yunhe_chinese_snapshot_has_expected_shape(self) -> None:
        self.assert_snapshot_has_expected_shape(YUNHE_Q2_OPS_ZH_SNAPSHOT_ID)

    def test_committed_acme_employee_json_and_csv_are_consistent(self) -> None:
        self.assert_employee_json_and_csv_are_consistent(ACME_Q2_OPS_SNAPSHOT_ID)

    def test_committed_yunhe_employee_json_and_csv_are_consistent(self) -> None:
        self.assert_employee_json_and_csv_are_consistent(YUNHE_Q2_OPS_ZH_SNAPSHOT_ID)

    def test_acme_builder_refuses_to_overwrite_existing_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = write_acme_q2_ops_snapshot(root_dir=tmpdir)
            self.assertTrue((first / OFFICE_EVENTS_JSONL).exists())
            with self.assertRaises(FileExistsError):
                write_acme_q2_ops_snapshot(root_dir=tmpdir)

    def test_yunhe_builder_refuses_to_overwrite_existing_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = write_yunhe_q2_ops_zh_snapshot(root_dir=tmpdir)
            self.assertTrue((first / OFFICE_EVENTS_JSONL).exists())
            with self.assertRaises(FileExistsError):
                write_yunhe_q2_ops_zh_snapshot(root_dir=tmpdir)

    def assert_graph_contains_required_office_relations(self, snapshot_id: str) -> None:
        graph = build_snapshot_graph(root_dir="eval/office_dataset", snapshot_id=snapshot_id)
        node_kinds = {node["kind"] for node in graph["nodes"]}
        edge_types = {edge["type"] for edge in graph["edges"]}

        for kind in ("employee", "department", "chat", "thread", "message", "task", "approval", "doc", "file"):
            self.assertIn(kind, node_kinds)
        for edge_type in (
            "reports_to",
            "belongs_to_department",
            "member_of_chat",
            "reply_to",
            "mentions",
            "owns_task",
            "blocked_by",
            "approved_by",
            "references_doc",
            "attached_file",
            "updates_status_of",
        ):
            self.assertIn(edge_type, edge_types)

    def test_acme_graph_contains_required_office_relations(self) -> None:
        self.assert_graph_contains_required_office_relations(ACME_Q2_OPS_SNAPSHOT_ID)

    def test_yunhe_graph_contains_required_office_relations(self) -> None:
        self.assert_graph_contains_required_office_relations(YUNHE_Q2_OPS_ZH_SNAPSHOT_ID)

    def test_injection_dry_run_does_not_write_capture_or_call_executor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_acme_q2_ops_snapshot(root_dir=tmpdir)

            def fail_executor(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
                raise AssertionError("dry-run must not execute OpenClaw")

            output = inject_snapshot_to_feishu(
                root_dir=tmpdir,
                snapshot_id=ACME_Q2_OPS_SNAPSHOT_ID,
                target_chat_id="oc_real_test_chat",
                capture_id="dry-run",
                dry_run=True,
                event_ids={"evt_acme_q2_0001"},
                executor=fail_executor,
            )
            self.assertEqual(output["summary"]["result_count"], 1)
            self.assertFalse((Path(tmpdir) / "captures" / "dry-run").exists())

    def test_injection_real_mode_writes_delivery_ledger_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_acme_q2_ops_snapshot(root_dir=tmpdir)
            calls: list[list[str]] = []

            def fake_executor(
                command: list[str],
                **_kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                calls.append(command)
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({"sendResult": {"messageId": "om_real_1"}}),
                    stderr="",
                )

            output = inject_snapshot_to_feishu(
                root_dir=tmpdir,
                snapshot_id=ACME_Q2_OPS_SNAPSHOT_ID,
                target_chat_id="oc_real_test_chat",
                capture_id="capture-a",
                event_ids={"evt_acme_q2_0001"},
                executor=fake_executor,
            )
            capture_dir = Path(tmpdir) / "captures" / "capture-a"
            self.assertEqual(output["summary"]["sent_count"], 1)
            self.assertEqual(len(calls), 1)
            self.assertTrue((capture_dir / "capture-metadata.json").exists())
            self.assertTrue((capture_dir / "injection-results.jsonl").exists())
            self.assertTrue((capture_dir / "injection-summary.json").exists())
            self.assertFalse((capture_dir / OFFICE_EVENTS_JSONL).exists())
            self.assertIn("--channel", calls[0])
            self.assertIn("feishu", calls[0])


if __name__ == "__main__":
    unittest.main()
