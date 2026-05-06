from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from feishu_builder_agent.cli import (
    annotation_gold_stage,
    build_checks_stage,
    compile_case_phase1,
    gold_validate_stage,
    generate_case_spec_stage,
    replay_runtime_stage,
)


class ReplayRuntimeTests(unittest.TestCase):
    def test_replay_runtime_emits_prediction_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "dataset"
            generated = generate_case_spec_stage(
                dataset_root=root,
                scenario_profile="enterprise_task_memory",
                difficulty="medium",
                seed=91,
                user_hint="优先走 runtime replay 烟测",
            )
            compiled = compile_case_phase1(case_spec_path=generated["case_spec_path"], dataset_root=root, dry_run=True)
            annotation_gold_stage(case_dir_path=compiled["case_dir"])
            build_checks_stage(case_dir_path=compiled["case_dir"])
            gold_validate_stage(case_dir_path=compiled["case_dir"])
            result = replay_runtime_stage(case_dir_path=compiled["case_dir"])
            case_dir = Path(result["case_dir"])
            self.assertTrue((case_dir / "predictions" / "candidate_events.jsonl").exists())
            self.assertTrue((case_dir / "predictions" / "session_events.jsonl").exists())
            self.assertTrue((case_dir / "predictions" / "task_wiki_state.json").exists())


if __name__ == "__main__":
    unittest.main()
