from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from codex_istm.core import ISTMError, SourceMutationError, archive_daily, ingest, render_daily


FIXTURE = Path(__file__).parent / "fixtures" / "rollout.jsonl"


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sessions"
        self.sources.mkdir()
        self.source = self.sources / "rollout.jsonl"
        shutil.copyfile(FIXTURE, self.source)
        self.state = self.root / "state.json"
        self.istm = self.root / "istm.jsonl"
        self.daily = self.root / "daily"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def records(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.istm.read_text(encoding="utf-8").splitlines()]

    def test_initial_ingestion_is_bounded_and_repeatable(self) -> None:
        first = ingest(self.sources, self.state, self.istm, max_message_chars=64)
        self.assertEqual((first.new_records, first.duplicate_records, first.pending_bytes), (2, 0, 0))
        records = self.records()
        self.assertEqual([record["role"] for record in records], ["user", "assistant"])
        self.assertNotIn("rollout.jsonl", json.dumps(records))
        self.assertEqual(ingest(self.sources, self.state, self.istm).new_records, 0)

    def test_append_only_reads_new_complete_lines(self) -> None:
        ingest(self.sources, self.state, self.istm)
        incomplete = '{"timestamp":"2026-07-24T10:00:00Z","type":"response_item","payload":{"type":"message","role":"user","content":"new line"}}'
        with self.source.open("a", encoding="utf-8") as handle:
            handle.write(incomplete)
        pending = ingest(self.sources, self.state, self.istm)
        self.assertEqual((pending.new_records, pending.pending_bytes), (0, len(incomplete.encode("utf-8"))))
        with self.source.open("a", encoding="utf-8") as handle:
            handle.write("\n")
        complete = ingest(self.sources, self.state, self.istm)
        self.assertEqual((complete.new_records, complete.pending_bytes), (1, 0))
        self.assertEqual(self.records()[-1]["text"], "new line")

    def test_processed_prefix_mutation_fails_without_changes(self) -> None:
        ingest(self.sources, self.state, self.istm)
        before_state = self.state.read_bytes()
        before_istm = self.istm.read_bytes()
        self.source.write_text(self.source.read_text(encoding="utf-8").replace("local-only", "local-only".upper()), encoding="utf-8")
        with self.assertRaises(SourceMutationError):
            ingest(self.sources, self.state, self.istm)
        self.assertEqual(self.state.read_bytes(), before_state)
        self.assertEqual(self.istm.read_bytes(), before_istm)

    def test_malformed_complete_line_fails_without_changes(self) -> None:
        ingest(self.sources, self.state, self.istm)
        before_state = self.state.read_bytes()
        before_istm = self.istm.read_bytes()
        with self.source.open("a", encoding="utf-8") as handle:
            handle.write("{not-json}\n")
        with self.assertRaises(ISTMError):
            ingest(self.sources, self.state, self.istm)
        self.assertEqual(self.state.read_bytes(), before_state)
        self.assertEqual(self.istm.read_bytes(), before_istm)

    def test_identical_events_at_distinct_source_positions_survive(self) -> None:
        ingest(self.sources, self.state, self.istm)
        shutil.copyfile(self.source, self.sources / "copied.jsonl")
        result = ingest(self.sources, self.state, self.istm)
        self.assertEqual((result.new_records, result.duplicate_records), (2, 0))
        self.assertEqual(len(self.records()), 4)

    def test_daily_is_deterministic_and_bounded(self) -> None:
        ingest(self.sources, self.state, self.istm)
        first = render_daily(date(2026, 7, 24), self.istm, self.daily, max_records=1, max_bytes=12, excerpt_bytes=40)
        first_bytes = first.path.read_bytes()
        second = render_daily(date(2026, 7, 24), self.istm, self.daily, max_records=1, max_bytes=12, excerpt_bytes=40)
        self.assertEqual(first_bytes, second.path.read_bytes())
        self.assertEqual(first.records, 1)
        self.assertIn(b"selection_sha256=", first_bytes)
        self.assertNotIn(b"rollout.jsonl", first_bytes)

    def test_archive_copies_and_preserves_originals(self) -> None:
        self.daily.mkdir()
        old = self.daily / "2026-06-01.md"
        old.write_text("old\n", encoding="utf-8")
        dry = archive_daily(self.daily, self.root / "archive", date(2026, 7, 24), keep_days=30)
        self.assertTrue(dry.dry_run)
        self.assertEqual(dry.copied, (old,))
        applied = archive_daily(self.daily, self.root / "archive", date(2026, 7, 24), keep_days=30, apply=True)
        self.assertFalse(applied.dry_run)
        self.assertTrue(old.exists())
        self.assertEqual(applied.copied[0].read_text(encoding="utf-8"), "old\n")
