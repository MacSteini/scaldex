from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tokenmessung.analyzer import analyze_results, paired_deltas, parse_run


def write_run(base: Path, run_id: str, variant: str, tokens: int) -> None:
    run = base / run_id
    run.mkdir()
    task = {
        "id": "login_test_failure",
        "expected_files": ["services/auth/src/login.ts"],
        "expected_terms": ["passwordPolicy"],
    }
    meta = {
        "run_id": run_id,
        "task_id": "login_test_failure",
        "task": task,
        "variant": variant,
        "repeat": 1,
        "run_order": 1 if variant == "control" else 2,
        "model": "test-model",
        "fixture_commit": "abc",
        "agents_file_bytes": 10,
    }
    (run / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    events = [
        {"type": "thread.started", "thread_id": "t"},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "bash -lc 'rg passwordPolicy services/auth/src/login.ts'", "stdout": "services/auth/src/login.ts passwordPolicy"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "bash -lc 'cat logs/app.log'", "stdout": "x" * 21000}},
        {"type": "turn.completed", "usage": {"input_tokens": tokens, "cached_input_tokens": 100, "output_tokens": 20, "reasoning_output_tokens": 5}},
        {"type": "unknown.future", "payload": {"usage": {"input_tokens": 1}}},
    ]
    (run / "codex.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    (run / "final.json").write_text(
        json.dumps(
            {
                "answer": "see services/auth/src/login.ts",
                "relevant_files": ["services/auth/src/login.ts"],
                "root_cause_or_location": "passwordPolicy",
                "confidence": "high",
            }
        ),
        encoding="utf-8",
    )
    (run / "exit_code.txt").write_text("0\n", encoding="utf-8")
    (run / "time.json").write_text(json.dumps({"wall_seconds": 1.5}), encoding="utf-8")


class AnalyzerTests(unittest.TestCase):
    def test_parse_run_extracts_usage_and_context_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_run(base, "r1", "control", 1000)
            row = parse_run(base / "r1")
            self.assertEqual(row["input_tokens"], 1000)
            self.assertEqual(row["cached_input_tokens"], 100)
            self.assertEqual(row["non_cached_input_tokens"], 900)
            self.assertEqual(row["targeted_steps"], 1)
            self.assertEqual(row["risky_full_reads"], 1)
            self.assertEqual(row["large_text_events_over_20kb"], 1)
            self.assertTrue(row["success"])

    def test_analyze_results_writes_summary_and_paired_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_run(base, "control", "control", 1000)
            write_run(base, "agents", "agents", 700)
            paths = analyze_results(base)
            for path in paths.values():
                self.assertTrue(path.exists())
            rows = [parse_run(base / "control"), parse_run(base / "agents")]
            deltas = paired_deltas(rows)
            self.assertEqual(deltas[0]["delta_non_cached_input_tokens_agents_minus_control"], -300)


if __name__ == "__main__":
    unittest.main()
