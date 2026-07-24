from __future__ import annotations

from datetime import date
from importlib.resources import files
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from codex_istm.core import (
    ISTMError,
    SourceMutationError,
    _canonical_json,
    archive_daily,
    ingest,
    render_daily,
    sha256_bytes,
)
from codex_istm.model_workflow import (
    NoWorkError,
    apply_daily_result,
    apply_structured_result,
    default_result_path,
    prepare_daily_packet,
    prepare_structured_packet,
    run_codex_model,
    validate_result,
)


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
        self.packets = self.root / "handoffs"
        self.model_daily = self.root / "model-daily"
        self.structured = self.root / "structured"
        self.model_state = self.root / "model-state.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def records(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.istm.read_text(encoding="utf-8").splitlines()]

    def write_json(self, path: Path, value: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")

    def daily_packet(self) -> tuple[Path, dict[str, object]]:
        ingest(self.sources, self.state, self.istm)
        prepared = prepare_daily_packet(
            date(2026, 7, 24),
            self.istm,
            self.packets,
            self.model_state,
            max_items=10,
            item_bytes=80,
            total_bytes=160,
        )
        return prepared.path, json.loads(prepared.path.read_text(encoding="utf-8"))

    def valid_daily_result(self, packet: dict[str, object]) -> dict[str, object]:
        items = packet["items"]
        assert isinstance(items, list)
        return {
            "schema_version": "codex-istm-model-result-v1",
            "stage": "istm_to_daily",
            "packet_sha256": packet["packet_sha256"],
            "producer": {
                "kind": "codex_cli",
                "codex_cli_version": "codex-cli test",
                "model": "example-model",
                "reasoning_effort": "xhigh",
                "isolation_profile": "codex-cli-no-tools-v1",
            },
            "entries": [
                {
                    "source_record_ids": [item["record_id"] for item in items],
                    "summary": "The user asked for a local-only memory pipeline and received a bounded answer.",
                }
            ],
            "omitted": [],
        }

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

    def test_daily_model_packet_is_frozen_bounded_and_path_private(self) -> None:
        packet_path, packet = self.daily_packet()
        self.assertEqual(packet["stage"], "istm_to_daily")
        self.assertEqual(len(packet["items"]), 2)
        self.assertNotIn("rollout.jsonl", packet_path.read_text(encoding="utf-8"))
        self.assertLessEqual(
            sum(len(item["text"].encode("utf-8")) for item in packet["items"]),
            160,
        )
        repeated = prepare_daily_packet(
            date(2026, 7, 24),
            self.istm,
            self.packets,
            self.model_state,
            max_items=10,
            item_bytes=80,
            total_bytes=160,
        )
        self.assertEqual(repeated.path, packet_path)
        self.assertEqual(repeated.packet_sha256, packet["packet_sha256"])

    def test_daily_candidate_requires_exact_packet_coverage_before_apply(self) -> None:
        packet_path, packet = self.daily_packet()
        result_path = default_result_path(packet_path)
        candidate = self.valid_daily_result(packet)
        self.write_json(result_path, candidate)
        validated_packet, _ = validate_result(packet_path, result_path)
        self.assertEqual(validated_packet["packet_sha256"], packet["packet_sha256"])
        applied = apply_daily_result(
            packet_path,
            result_path,
            self.istm,
            self.model_state,
            self.model_daily,
        )
        self.assertFalse(applied.already_applied)
        daily_json_path = applied.paths[0]
        daily_json = json.loads(daily_json_path.read_text(encoding="utf-8"))
        self.assertEqual(len(daily_json["entries"]), 1)
        self.assertEqual(len(daily_json["entries"][0]["entry_id"]), 64)
        self.assertNotIn("rollout.jsonl", applied.paths[1].read_text(encoding="utf-8"))
        self.assertTrue(
            apply_daily_result(
                packet_path,
                result_path,
                self.istm,
                self.model_state,
                self.model_daily,
            ).already_applied
        )

        candidate["entries"][0]["source_record_ids"].pop()
        self.write_json(self.root / "incomplete-result.json", candidate)
        before = daily_json_path.read_bytes()
        with self.assertRaises(ISTMError):
            apply_daily_result(
                packet_path,
                self.root / "incomplete-result.json",
                self.istm,
                self.model_state,
                self.model_daily,
            )
        self.assertEqual(daily_json_path.read_bytes(), before)

    def test_structured_candidate_applies_immutable_safe_cards_and_marker(self) -> None:
        packet_path, packet = self.daily_packet()
        daily_result_path = default_result_path(packet_path)
        self.write_json(daily_result_path, self.valid_daily_result(packet))
        apply_daily_result(
            packet_path,
            daily_result_path,
            self.istm,
            self.model_state,
            self.model_daily,
        )
        structured_packet = prepare_structured_packet(
            date(2026, 7, 24),
            self.model_daily,
            self.packets,
            self.model_state,
            max_items=10,
            item_bytes=200,
            total_bytes=400,
        )
        structured_value = json.loads(structured_packet.path.read_text(encoding="utf-8"))
        entry_id = structured_value["items"][0]["daily_entry_id"]
        result = {
            "schema_version": "codex-istm-model-result-v1",
            "stage": "daily_to_structured",
            "packet_sha256": structured_value["packet_sha256"],
            "producer": {
                "kind": "codex_cli",
                "codex_cli_version": "codex-cli test",
                "model": "example-model",
                "reasoning_effort": "xhigh",
                "isolation_profile": "codex-cli-no-tools-v1",
            },
            "promotions": [
                {
                    "source_daily_entry_ids": [entry_id],
                    "title": "Keep model output behind a deterministic apply gate",
                    "content": "Freeze bounded source packets and validate exact result bindings before applying memory.",
                    "confidence": "high",
                }
            ],
            "omitted": [],
        }
        result_path = default_result_path(structured_packet.path)
        self.write_json(result_path, result)
        memory_id = sha256_bytes(
            _canonical_json(
                {
                    "packet_sha256": structured_value["packet_sha256"],
                    "promotion": result["promotions"][0],
                }
            )
        )
        conflicting_card = (
            self.structured
            / "stm"
            / "2026-07-24"
            / f"{memory_id}.md"
        )
        conflicting_card.parent.mkdir(parents=True)
        conflicting_card.write_text("conflict\n", encoding="utf-8")
        with self.assertRaises(ISTMError):
            apply_structured_result(
                structured_packet.path,
                result_path,
                self.model_daily,
                self.model_state,
                self.structured,
            )
        result_sha256 = sha256_bytes(_canonical_json(result))
        self.assertFalse(
            (self.structured / ".applied" / f"{result_sha256}.json").exists()
        )
        conflicting_card.unlink()
        applied = apply_structured_result(
            structured_packet.path,
            result_path,
            self.model_daily,
            self.model_state,
            self.structured,
        )
        self.assertFalse(applied.already_applied)
        card_paths = [path for path in applied.paths if path.suffix == ".md"]
        self.assertEqual(len(card_paths), 1)
        self.assertEqual(
            card_paths[0].relative_to(self.structured).parts[:3],
            ("stm", "2026-07-24", card_paths[0].name),
        )
        self.assertTrue(applied.paths[-1].is_file())
        self.assertTrue(
            apply_structured_result(
                structured_packet.path,
                result_path,
                self.model_daily,
                self.model_state,
                self.structured,
            ).already_applied
        )

        result["promotions"][0]["path"] = "../escape"
        self.write_json(self.root / "unsafe-structured.json", result)
        with self.assertRaises(ISTMError):
            apply_structured_result(
                structured_packet.path,
                self.root / "unsafe-structured.json",
                self.model_daily,
                self.model_state,
                self.structured,
            )

    def test_codex_runner_is_ephemeral_read_only_and_validates_before_persisting(self) -> None:
        packet_path, packet = self.daily_packet()
        trace_path = self.root / "fake-codex-args.json"
        fake = self.root / "fake-codex"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, sys\n"
            "if '--version' in sys.argv:\n"
            " print('codex-cli fake-1.0')\n"
            " raise SystemExit(0)\n"
            f"trace = pathlib.Path({str(trace_path)!r})\n"
            "trace.write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
            "output = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])\n"
            "prompt = sys.stdin.read()\n"
            "raw = prompt.split('BEGIN_UNTRUSTED_PACKET_JSON\\n', 1)[1].split('\\nEND_UNTRUSTED_PACKET_JSON', 1)[0]\n"
            "packet = json.loads(raw)\n"
            "candidate = {'schema_version':'codex-istm-model-result-v1','stage':'istm_to_daily',"
            "'packet_sha256':packet['packet_sha256'],'entries':[],"
            "'omitted':[{'record_id':item['record_id'],'reason':'low_signal'} for item in packet['items']]}\n"
            "output.write_text(json.dumps(candidate), encoding='utf-8')\n",
            encoding="utf-8",
        )
        fake.chmod(0o700)
        result_path = self.root / "runner-result.json"
        run_codex_model(
            packet_path,
            result_path,
            codex_bin=str(fake),
            model="example-model",
            reasoning_effort="xhigh",
            timeout_seconds=30,
        )
        arguments = json.loads(trace_path.read_text(encoding="utf-8"))
        self.assertIn("--ephemeral", arguments)
        self.assertIn("--ignore-user-config", arguments)
        self.assertIn("--ignore-rules", arguments)
        self.assertIn("--strict-config", arguments)
        self.assertIn("shell_tool", arguments)
        self.assertIn("multi_agent", arguments)
        self.assertIn("read-only", arguments)
        self.assertIn("--output-schema", arguments)
        self.assertIn("example-model", arguments)
        self.assertTrue(result_path.is_file())
        validated_packet, _ = validate_result(packet_path, result_path)
        self.assertEqual(validated_packet["packet_sha256"], packet["packet_sha256"])

    def test_model_daily_overflow_advances_across_bounded_batches(self) -> None:
        ingest(self.sources, self.state, self.istm)
        first = prepare_daily_packet(
            date(2026, 7, 24),
            self.istm,
            self.packets,
            self.model_state,
            max_items=1,
            item_bytes=100,
            total_bytes=100,
        )
        first_packet = json.loads(first.path.read_text(encoding="utf-8"))
        self.assertEqual(first.not_yet_admitted_items, 1)
        first_result = default_result_path(first.path)
        self.write_json(first_result, self.valid_daily_result(first_packet))
        apply_daily_result(
            first.path,
            first_result,
            self.istm,
            self.model_state,
            self.model_daily,
        )
        second = prepare_daily_packet(
            date(2026, 7, 24),
            self.istm,
            self.packets,
            self.model_state,
            max_items=1,
            item_bytes=100,
            total_bytes=100,
        )
        second_packet = json.loads(second.path.read_text(encoding="utf-8"))
        self.assertNotEqual(first.packet_sha256, second.packet_sha256)
        self.assertEqual(second.not_yet_admitted_items, 0)
        second_result = default_result_path(second.path)
        self.write_json(second_result, self.valid_daily_result(second_packet))
        apply_daily_result(
            second.path,
            second_result,
            self.istm,
            self.model_state,
            self.model_daily,
        )
        with self.assertRaises(NoWorkError):
            prepare_daily_packet(
                date(2026, 7, 24),
                self.istm,
                self.packets,
                self.model_state,
                max_items=1,
                item_bytes=100,
                total_bytes=100,
            )

    def test_apply_rebinds_source_and_preflights_all_daily_targets(self) -> None:
        packet_path, packet = self.daily_packet()
        result_path = default_result_path(packet_path)
        self.write_json(result_path, self.valid_daily_result(packet))
        raw = self.istm.read_bytes()
        self.istm.write_bytes(raw.replace(b"local-only", b"LOCAL-ONLY", 1))
        with self.assertRaises(ISTMError):
            apply_daily_result(
                packet_path,
                result_path,
                self.istm,
                self.model_state,
                self.model_daily,
            )
        self.istm.write_bytes(raw)
        markdown_target = (
            self.model_daily
            / "2026-07-24"
            / "batches"
            / f"{packet['packet_sha256']}.md"
        )
        markdown_target.parent.mkdir(parents=True)
        markdown_target.write_text("conflict\n", encoding="utf-8")
        with self.assertRaises(ISTMError):
            apply_daily_result(
                packet_path,
                result_path,
                self.istm,
                self.model_state,
                self.model_daily,
            )
        json_target = markdown_target.with_suffix(".json")
        self.assertFalse(json_target.exists())

    def test_packet_rejects_traversal_and_markdown_is_inert(self) -> None:
        packet_path, packet = self.daily_packet()
        candidate = self.valid_daily_result(packet)
        candidate["entries"][0]["summary"] = (
            "<script>alert(1)</script> **bold** [x](javascript:bad)\n"
            "    fenced by indentation\n# injected heading"
        )
        result_path = default_result_path(packet_path)
        self.write_json(result_path, candidate)
        applied = apply_daily_result(
            packet_path,
            result_path,
            self.istm,
            self.model_state,
            self.model_daily,
        )
        rendered = applied.paths[1].read_text(encoding="utf-8")
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("](javascript", rendered)
        self.assertNotIn("\n    fenced", rendered)
        self.assertNotIn("\n# injected", rendered)

        tampered = dict(packet)
        tampered["date"] = "../escape"
        without_digest = dict(tampered)
        without_digest.pop("packet_sha256")
        tampered["packet_sha256"] = sha256_bytes(_canonical_json(without_digest))
        tampered_path = self.root / "tampered.packet.json"
        self.write_json(tampered_path, tampered)
        with self.assertRaises(ISTMError):
            validate_result(tampered_path, result_path)

    def test_result_schemas_are_packaged_resources(self) -> None:
        schema_root = files("codex_istm").joinpath("schemas")
        for name in (
            "istm-to-daily-result-v1.schema.json",
            "daily-to-structured-result-v1.schema.json",
        ):
            schema = json.loads(schema_root.joinpath(name).read_text(encoding="utf-8"))
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])

    def test_structured_apply_rejects_new_daily_commit_after_prepare(self) -> None:
        ingest(self.sources, self.state, self.istm)
        first_daily = prepare_daily_packet(
            date(2026, 7, 24),
            self.istm,
            self.packets,
            self.model_state,
            max_items=1,
        )
        first_packet = json.loads(first_daily.path.read_text(encoding="utf-8"))
        first_result = default_result_path(first_daily.path)
        self.write_json(first_result, self.valid_daily_result(first_packet))
        apply_daily_result(
            first_daily.path,
            first_result,
            self.istm,
            self.model_state,
            self.model_daily,
        )
        structured_packet = prepare_structured_packet(
            date(2026, 7, 24),
            self.model_daily,
            self.packets,
            self.model_state,
        )
        structured_value = json.loads(structured_packet.path.read_text(encoding="utf-8"))
        entry_id = structured_value["items"][0]["daily_entry_id"]
        structured_result = {
            "schema_version": "codex-istm-model-result-v1",
            "stage": "daily_to_structured",
            "packet_sha256": structured_value["packet_sha256"],
            "producer": {
                "kind": "codex_cli",
                "codex_cli_version": "codex-cli test",
                "model": "example-model",
                "reasoning_effort": "xhigh",
                "isolation_profile": "codex-cli-no-tools-v1",
            },
            "promotions": [],
            "omitted": [
                {
                    "daily_entry_id": entry_id,
                    "reason": "not_durable",
                }
            ],
        }
        structured_result_path = default_result_path(structured_packet.path)
        self.write_json(structured_result_path, structured_result)

        second_daily = prepare_daily_packet(
            date(2026, 7, 24),
            self.istm,
            self.packets,
            self.model_state,
            max_items=1,
        )
        second_packet = json.loads(second_daily.path.read_text(encoding="utf-8"))
        second_result = default_result_path(second_daily.path)
        self.write_json(second_result, self.valid_daily_result(second_packet))
        apply_daily_result(
            second_daily.path,
            second_result,
            self.istm,
            self.model_state,
            self.model_daily,
        )
        with self.assertRaises(ISTMError):
            apply_structured_result(
                structured_packet.path,
                structured_result_path,
                self.model_daily,
                self.model_state,
                self.structured,
            )
        self.assertFalse((self.structured / ".applied").exists())
