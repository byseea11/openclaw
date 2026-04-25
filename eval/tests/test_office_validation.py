from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eval.office_validation import run_validation_variant


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._response_index = 0

    def send(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        self._response_index += 1
        prompt = kwargs["input_items"][0]["content"]
        if kwargs.get("tools"):
            return type(
                "Resp",
                (),
                {
                    "response_id": f"resp-{self._response_index}",
                    "text": "",
                    "tool_calls": [],
                    "tool_outputs": [
                        type(
                            "ToolOutput",
                            (),
                            {
                                "name": "memory_search",
                                "output": {
                                    "results": [
                                        {
                                            "snippet": "[event_id: evt-2] Bob: AP-2 approved",
                                            "corpus": "graph",
                                            "graphMeta": {"node_hits": 1},
                                        }
                                    ]
                                },
                            },
                        )()
                    ],
                    "usage": {"input_tokens": 42},
                    "latency_ms": 12.5,
                },
            )()
        return type(
            "Resp",
            (),
            {
                "response_id": f"resp-{self._response_index}",
                "text": "AP-2 approved it",
                "tool_calls": [],
                "tool_outputs": [],
                "usage": {"input_tokens": 24},
                "latency_ms": 10.0,
            },
        )()


class OfficeValidationTests(unittest.TestCase):
    def test_validation_runner_is_read_only_to_snapshot_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot_dir = root / "snapshots" / "snapshot-1"
            snapshot_dir.mkdir(parents=True)
            events_path = snapshot_dir / "office_events.jsonl"
            manifest_path = snapshot_dir / "validation_manifest.json"
            employees_path = snapshot_dir / "employees.json"
            metadata_path = snapshot_dir / "snapshot-metadata.json"
            employees_path.write_text(json.dumps({"employees": []}), encoding="utf-8")
            (snapshot_dir / "employees.csv").write_text("", encoding="utf-8")
            events_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "event_id": "evt-1",
                                "snapshot_id": "snapshot-1",
                                "chat_id": "oc_chat",
                                "message_id": "om_1",
                                "event_time": "2026-04-25T09:00:00Z",
                                "sender_open_id": "ou_alice",
                                "sender_name": "Alice",
                                "message_type": "text",
                                "content_text": "TASK-1 is blocked by AP-2",
                            }
                        ),
                        json.dumps(
                            {
                                "event_id": "evt-2",
                                "snapshot_id": "snapshot-1",
                                "chat_id": "oc_chat",
                                "message_id": "om_2",
                                "event_time": "2026-04-26T09:00:00Z",
                                "sender_open_id": "ou_bob",
                                "sender_name": "Bob",
                                "message_type": "text",
                                "content_text": "AP-2 approved",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "snapshot_id": "snapshot-1",
                        "cases": [
                            {
                                "case_id": "case-1",
                                "snapshot_id": "snapshot-1",
                                "history_window": {"event_ids": ["evt-1", "evt-2"]},
                                "question": "What happened to AP-2?",
                                "expected_answer": "AP-2 approved it",
                                "evidence_event_ids": ["evt-2"],
                                "ability_tag": "approval",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            metadata_path.write_text(json.dumps({"snapshot_id": "snapshot-1"}), encoding="utf-8")
            before_events = events_path.read_text(encoding="utf-8")
            before_manifest = manifest_path.read_text(encoding="utf-8")

            summary = run_validation_variant(
                client=FakeClient(),
                root_dir=str(root),
                snapshot_id="snapshot-1",
                output_dir=root / "results",
                variant_name="native",
            )

            self.assertEqual(summary["case_count"], 1)
            self.assertEqual(summary["exact_match"], 1.0)
            self.assertEqual(summary["average_graph_hit_rate"], 1.0)
            self.assertEqual(events_path.read_text(encoding="utf-8"), before_events)
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), before_manifest)


if __name__ == "__main__":
    unittest.main()
