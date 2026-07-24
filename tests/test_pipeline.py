from __future__ import annotations

from datetime import date
from importlib.resources import files
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import codex_istm.model_workflow as model_workflow
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
    apply_memory_forest_result,
    default_result_path,
    prepare_daily_packet,
    prepare_memory_forest_packet,
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
        self.memory_forest = self.root / "memory-forest"
        self.memory_forest.mkdir()
        self.memory_forest.chmod(0o700)
        self.forest_id = "f" * 32
        memory_forest_state = self.memory_forest / ".memory-forest"
        memory_forest_state.mkdir(mode=0o700)
        memory_forest_config = memory_forest_state / "forest.json"
        memory_forest_config.write_text(
            json.dumps(
                {
                    "forest_id": self.forest_id,
                    "layout": "layer/domain/branch/leaf",
                    "layers": [
                        "00 life_archive",
                        "01 xltm",
                        "02 ltm",
                        "03 mtm",
                        "04 stm",
                        "05 daily",
                        "06 istm",
                    ],
                    "schema_version": 1,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        memory_forest_config.chmod(0o600)
        self.memory_forest_trace = self.root / "memory-forest-trace.jsonl"
        self.memory_forest_bin = self.root / "fake-memory-forest"
        self.memory_forest_bin.write_text(
            "#!/usr/bin/env python3\n"
            "import hashlib, json, pathlib, sys\n"
            f"trace = pathlib.Path({str(self.memory_forest_trace)!r})\n"
            "assert sys.argv[1] == '--json'\n"
            "operation, root_raw, plan_raw = sys.argv[2:5]\n"
            "root = pathlib.Path(root_raw)\n"
            "assert pathlib.Path(plan_raw) == pathlib.Path(plan_raw).resolve()\n"
            "plan = json.loads(pathlib.Path(plan_raw).read_text(encoding='utf-8'))\n"
            "transaction_id = plan['transaction_id']\n"
            "receipt = root / '.memory-forest' / 'receipts' / f'{transaction_id}.json'\n"
            "already_applied = receipt.exists()\n"
            "touched = []\n"
            "if not already_applied:\n"
            " receipt.parent.mkdir(parents=True, exist_ok=True)\n"
            " if operation == 'apply-daily':\n"
            "  target = root / '05 daily' / f\"{plan['date']}.md\"\n"
            "  target.parent.mkdir(parents=True, exist_ok=True)\n"
            "  target.write_text(json.dumps(plan, sort_keys=True) + '\\n', encoding='utf-8')\n"
            "  touched = [target.relative_to(root).as_posix()]\n"
            " else:\n"
            "  for item in plan['promotions']:\n"
            "   route = item['route']\n"
            "   target = root / '04 stm' / route['domain'] / route['branch'] / f\"{route['leaf']}.md\"\n"
            "   target.parent.mkdir(parents=True, exist_ok=True)\n"
            "   target.write_text(json.dumps(item, sort_keys=True) + '\\n', encoding='utf-8')\n"
            "   touched.append(target.relative_to(root).as_posix())\n"
            " plan_bytes = (json.dumps(plan, ensure_ascii=True, allow_nan=False, "
            "sort_keys=True, separators=(',', ':')) + '\\n').encode('utf-8')\n"
            " receipt_value = {'schema_version':'memory-forest-write-receipt-v1',"
            "'forest_id':plan['forest_id'],'ok':True,'operation':operation,"
            "'transaction_id':transaction_id,"
            "'plan_sha256':hashlib.sha256(plan_bytes).hexdigest(),'date':plan['date'],"
            "'touched':sorted(touched),"
            "'validation':{'ok':True,'documents':1,'errors':0,'warnings':0},"
            "'audit':{'ok':True,'documents':1,'errors':0,'warnings':0,'links':0},"
            "'index':{'bytes_indexed':1,'documents':1,"
            "'index':'.memory-forest/index.sqlite3'}}\n"
            " receipt.write_text(json.dumps(receipt_value, sort_keys=True, separators=(',', ':')) + '\\n', encoding='utf-8')\n"
            "with trace.open('a', encoding='utf-8') as handle:\n"
            " handle.write(json.dumps({'operation':operation,'plan':plan}, sort_keys=True) + '\\n')\n"
            "raw = receipt.read_bytes()\n"
            "response = {'schema_version':1,'ok':True,'operation':operation,"
            "'forest_id':plan['forest_id'],"
            "'transaction_id':transaction_id,'already_applied':already_applied,"
            "'receipt':f'.memory-forest/receipts/{transaction_id}.json',"
            "'receipt_sha256':hashlib.sha256(raw).hexdigest(),'touched':sorted(touched)}\n"
            "print(json.dumps(response, sort_keys=True, separators=(',', ':')))\n",
            encoding="utf-8",
        )
        self.memory_forest_bin.chmod(0o700)
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

    def apply_daily(self, packet_path: Path, result_path: Path, *_unused):
        return apply_daily_result(
            packet_path,
            result_path,
            self.istm,
            self.model_state,
            self.model_daily,
            self.memory_forest,
            str(self.memory_forest_bin),
        )

    def apply_memory_forest_result(self, packet_path: Path, result_path: Path):
        return apply_memory_forest_result(
            packet_path,
            result_path,
            self.model_daily,
            self.model_state,
            self.memory_forest,
            str(self.memory_forest_bin),
        )

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
        applied = self.apply_daily(
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
        self.assertTrue((self.memory_forest / "05 daily" / "2026-07-24.md").is_file())
        marker = json.loads(applied.paths[2].read_text(encoding="utf-8"))
        self.assertEqual(
            set(marker["memory_forest"]),
            {
                "operation",
                "forest_id",
                "transaction_id",
                "receipt",
                "receipt_sha256",
                "plan_sha256",
            },
        )
        first_trace = json.loads(
            self.memory_forest_trace.read_text(encoding="utf-8").splitlines()[0]
        )
        self.assertEqual(first_trace["operation"], "apply-daily")
        self.assertEqual(
            set(first_trace["plan"]),
            {
                "schema_version",
                "forest_id",
                "transaction_id",
                "date",
                "entries",
                "provenance",
            },
        )
        self.assertEqual(
            set(first_trace["plan"]["provenance"]),
            {"packet_sha256", "result_sha256", "batch_id"},
        )
        self.assertEqual(
            set(first_trace["plan"]["entries"][0]),
            {"entry_id", "source_record_ids", "summary"},
        )
        self.assertTrue(
            self.apply_daily(
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
            self.apply_daily(
                packet_path,
                self.root / "incomplete-result.json",
                self.istm,
                self.model_state,
                self.model_daily,
            )
        self.assertEqual(daily_json_path.read_bytes(), before)

    def test_structured_candidate_promotes_through_memory_forest_cli_only(self) -> None:
        packet_path, packet = self.daily_packet()
        daily_result_path = default_result_path(packet_path)
        self.write_json(daily_result_path, self.valid_daily_result(packet))
        self.apply_daily(
            packet_path,
            daily_result_path,
            self.istm,
            self.model_state,
            self.model_daily,
        )
        structured_packet = prepare_memory_forest_packet(
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
            "schema_version": "codex-istm-model-result-v2",
            "stage": "daily_to_memory_forest",
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
                    "route": {
                        "domain": "memory-systems",
                        "domain_title": "Memory systems",
                        "branch": "deterministic-apply",
                        "branch_title": "Deterministic apply",
                        "leaf": "model-output-gate",
                    },
                    "title": "Keep model output behind a deterministic apply gate",
                    "content": "Freeze bounded source packets and validate exact result bindings before applying memory.",
                    "confidence": "high",
                }
            ],
            "omitted": [],
        }
        result_path = default_result_path(structured_packet.path)
        self.write_json(result_path, result)
        applied = self.apply_memory_forest_result(
            structured_packet.path,
            result_path,
        )
        self.assertFalse(applied.already_applied)
        self.assertEqual(len(applied.paths), 1)
        self.assertTrue(applied.paths[0].is_file())
        self.assertFalse((self.root / "structured").exists())
        self.assertTrue(
            (
                self.memory_forest
                / "04 stm"
                / "memory-systems"
                / "deterministic-apply"
                / "model-output-gate.md"
            ).is_file()
        )
        traces = [
            json.loads(line)
            for line in self.memory_forest_trace.read_text(encoding="utf-8").splitlines()
        ]
        promotion_plan = traces[-1]["plan"]
        self.assertEqual(traces[-1]["operation"], "promote")
        self.assertEqual(
            set(promotion_plan),
            {
                "schema_version",
                "forest_id",
                "transaction_id",
                "date",
                "promotions",
                "provenance",
            },
        )
        self.assertEqual(
            set(promotion_plan["provenance"]),
            {"packet_sha256", "result_sha256", "daily_commit_sha256s"},
        )
        self.assertEqual(
            set(promotion_plan["promotions"][0]),
            {"source_daily_entry_ids", "route", "title", "content", "confidence"},
        )
        self.assertEqual(
            set(promotion_plan["promotions"][0]["route"]),
            {"domain", "domain_title", "branch", "branch_title", "leaf"},
        )
        self.assertEqual(
            promotion_plan["provenance"]["daily_commit_sha256s"],
            [structured_value["items"][0]["daily_result_sha256"]],
        )
        self.assertNotEqual(
            promotion_plan["provenance"]["daily_commit_sha256s"],
            structured_value["source"]["commits"],
        )
        self.assertTrue(
            self.apply_memory_forest_result(
                structured_packet.path,
                result_path,
            ).already_applied
        )

        result["promotions"][0]["path"] = "../escape"
        self.write_json(self.root / "unsafe-structured.json", result)
        with self.assertRaises(ISTMError):
            self.apply_memory_forest_result(
                structured_packet.path,
                self.root / "unsafe-structured.json",
            )

    def test_structured_validation_matches_memory_forest_parent_title_contract(self) -> None:
        packet_path, packet = self.daily_packet()
        items = packet["items"]
        assert isinstance(items, list) and len(items) >= 2
        daily_result = self.valid_daily_result(packet)
        daily_result["entries"] = [
            {
                "source_record_ids": [item["record_id"]],
                "summary": f"Synthetic bounded summary {index}.",
            }
            for index, item in enumerate(items[:2], start=1)
        ]
        daily_result["omitted"] = [
            {"record_id": item["record_id"], "reason": "low_signal"}
            for item in items[2:]
        ]
        daily_result_path = default_result_path(packet_path)
        self.write_json(daily_result_path, daily_result)
        self.apply_daily(packet_path, daily_result_path)
        prepared = prepare_memory_forest_packet(
            date(2026, 7, 24),
            self.model_daily,
            self.packets,
            self.model_state,
        )
        prepared_value = json.loads(prepared.path.read_text(encoding="utf-8"))
        daily_entries = prepared_value["items"]
        assert isinstance(daily_entries, list) and len(daily_entries) == 2
        result = {
            "schema_version": "codex-istm-model-result-v2",
            "stage": "daily_to_memory_forest",
            "packet_sha256": prepared_value["packet_sha256"],
            "producer": {
                "kind": "codex_cli",
                "codex_cli_version": "codex-cli test",
                "model": "example-model",
                "reasoning_effort": "xhigh",
                "isolation_profile": "codex-cli-no-tools-v1",
            },
            "promotions": [
                {
                    "source_daily_entry_ids": [item["daily_entry_id"]],
                    "route": {
                        "domain": "memory-systems",
                        "domain_title": domain_title,
                        "branch": f"branch-{index}",
                        "branch_title": f"Branch {index}",
                        "leaf": f"leaf-{index}",
                    },
                    "title": f"Synthetic promotion {index}",
                    "content": "A bounded synthetic promotion.",
                    "confidence": "high",
                }
                for index, (item, domain_title) in enumerate(
                    zip(daily_entries, ("Memory systems", "Conflicting title")),
                    start=1,
                )
            ],
            "omitted": [],
        }
        result_path = default_result_path(prepared.path)
        self.write_json(result_path, result)
        with self.assertRaisesRegex(ISTMError, "conflicting titles"):
            validate_result(prepared.path, result_path)
        result["promotions"][1]["route"]["domain_title"] = "Memory systems"
        result["promotions"][1]["route"]["branch_title"] = "Bad\tTitle"
        self.write_json(result_path, result)
        with self.assertRaisesRegex(ISTMError, "unsafe target"):
            validate_result(prepared.path, result_path)

    def test_daily_crash_after_receipt_recovers_without_reapplying_content(self) -> None:
        packet_path, packet = self.daily_packet()
        result_path = default_result_path(packet_path)
        self.write_json(result_path, self.valid_daily_result(packet))
        original_save = model_workflow._save_model_state
        save_calls = 0

        def crash_on_cursor_save(path, state):
            nonlocal save_calls
            save_calls += 1
            if save_calls == 2:
                raise OSError("synthetic crash")
            original_save(path, state)

        with patch.object(
            model_workflow,
            "_save_model_state",
            side_effect=crash_on_cursor_save,
        ):
            with self.assertRaises(OSError):
                self.apply_daily(packet_path, result_path)
        state = json.loads(self.model_state.read_text(encoding="utf-8"))
        self.assertRegex(state["memory_forest_root_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(state["memory_forest_id"], self.forest_id)
        self.assertEqual(state["daily"], {})
        self.assertTrue((self.memory_forest / "05 daily" / "2026-07-24.md").is_file())
        marker_paths = list((self.model_daily / "2026-07-24" / "commits").glob("*.json"))
        self.assertEqual(len(marker_paths), 1)
        other_forest = self.root / "other-memory-forest"
        other_forest.mkdir()
        with self.assertRaises(ISTMError):
            apply_daily_result(
                packet_path,
                result_path,
                self.istm,
                self.model_state,
                self.model_daily,
                other_forest,
                str(self.memory_forest_bin),
            )
        self.assertFalse((other_forest / "05 daily" / "2026-07-24.md").exists())
        recovered = self.apply_daily(packet_path, result_path)
        self.assertTrue(recovered.already_applied)
        state = json.loads(self.model_state.read_text(encoding="utf-8"))
        self.assertEqual(state["schema_version"], "codex-istm-model-state-v2")
        self.assertEqual(len(state["daily"]["2026-07-24"]["applied_batches"]), 1)

    def test_same_path_replacement_with_new_forest_identity_is_rejected(self) -> None:
        packet_path, packet = self.daily_packet()
        result_path = default_result_path(packet_path)
        self.write_json(result_path, self.valid_daily_result(packet))
        self.apply_daily(packet_path, result_path)
        config_path = self.memory_forest / ".memory-forest" / "forest.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["forest_id"] = "e" * 32
        config_path.write_text(
            json.dumps(config, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        config_path.chmod(0o600)
        with self.assertRaisesRegex(ISTMError, "different Memory Forest identity"):
            self.apply_daily(packet_path, result_path)
        state = json.loads(self.model_state.read_text(encoding="utf-8"))
        self.assertEqual(state["memory_forest_id"], self.forest_id)

    def test_stdout_leakage_fails_before_marker_and_recovers_idempotently(self) -> None:
        packet_path, packet = self.daily_packet()
        result_path = default_result_path(packet_path)
        self.write_json(result_path, self.valid_daily_result(packet))
        leaking = self.root / "leaking-memory-forest"
        leaking.write_text(
            "#!/usr/bin/env python3\n"
            "import subprocess, sys\n"
            f"completed = subprocess.run([{str(self.memory_forest_bin)!r}, *sys.argv[1:]], "
            "capture_output=True, check=False)\n"
            "sys.stdout.buffer.write(b'leaked-log\\n' + completed.stdout)\n"
            "raise SystemExit(completed.returncode)\n",
            encoding="utf-8",
        )
        leaking.chmod(0o700)
        with self.assertRaises(ISTMError):
            apply_daily_result(
                packet_path,
                result_path,
                self.istm,
                self.model_state,
                self.model_daily,
                self.memory_forest,
                str(leaking),
            )
        state = json.loads(self.model_state.read_text(encoding="utf-8"))
        self.assertRegex(state["memory_forest_root_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(state["memory_forest_id"], self.forest_id)
        self.assertEqual(state["daily"], {})
        self.assertEqual(
            list((self.model_daily / "2026-07-24" / "commits").glob("*.json")),
            [],
        )
        self.assertTrue(self.apply_daily(packet_path, result_path).already_applied)

    def test_memory_forest_exec_oserror_fails_closed(self) -> None:
        packet_path, packet = self.daily_packet()
        result_path = default_result_path(packet_path)
        self.write_json(result_path, self.valid_daily_result(packet))
        with patch.object(
            model_workflow.subprocess,
            "run",
            side_effect=OSError("synthetic exec failure"),
        ):
            with self.assertRaisesRegex(ISTMError, "could not be started"):
                self.apply_daily(packet_path, result_path)
        state = json.loads(self.model_state.read_text(encoding="utf-8"))
        self.assertRegex(state["memory_forest_root_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(state["memory_forest_id"], self.forest_id)
        self.assertEqual(state["daily"], {})
        self.assertEqual(
            list((self.model_daily / "2026-07-24" / "commits").glob("*.json")),
            [],
        )

    def test_memory_forest_stdout_and_receipt_boundaries_fail_closed(self) -> None:
        stdout_path = self.root / "stdout.json"
        stdout_path.write_bytes(b'{"ok":true,"ok":true}\n')
        with self.assertRaises(ISTMError):
            model_workflow._read_memory_forest_stdout(stdout_path)
        stdout_path.write_bytes(b'{"ok":true}\n{"ok":true}\n')
        with self.assertRaises(ISTMError):
            model_workflow._read_memory_forest_stdout(stdout_path)
        stdout_path.write_bytes(
            b"x" * (model_workflow.MAX_MEMORY_FOREST_RECEIPT_BYTES + 1)
        )
        with self.assertRaises(ISTMError):
            model_workflow._read_memory_forest_stdout(stdout_path)

        transaction_id = "a" * 64
        response = {
            "schema_version": 1,
            "forest_id": self.forest_id,
            "ok": True,
            "operation": "apply-daily",
            "transaction_id": transaction_id,
            "already_applied": False,
            "receipt": f".memory-forest/receipts/{transaction_id}.json",
            "receipt_sha256": "b" * 64,
            "touched": [],
        }
        with self.assertRaises(ISTMError):
            model_workflow._validate_memory_forest_response(
                {**response, "extra": True},
                "apply-daily",
                transaction_id,
                self.forest_id,
            )
        receipt_path = (
            self.memory_forest
            / ".memory-forest"
            / "receipts"
            / f"{transaction_id}.json"
        )
        receipt_path.parent.mkdir(parents=True)
        target = self.root / "outside-receipt.json"
        target.write_text(
            json.dumps(
                {
                    "ok": True,
                    "operation": "apply-daily",
                    "transaction_id": transaction_id,
                }
            ),
            encoding="utf-8",
        )
        receipt_path.symlink_to(target)
        with self.assertRaises(ISTMError):
            model_workflow._verify_memory_forest_receipt_file(
                self.memory_forest,
                response,
                "apply-daily",
                transaction_id,
                "c" * 64,
                "2026-07-24",
                self.forest_id,
            )
        receipt_path.unlink()
        receipt_path.write_bytes(target.read_bytes())
        with self.assertRaises(ISTMError):
            model_workflow._verify_memory_forest_receipt_file(
                self.memory_forest,
                response,
                "apply-daily",
                transaction_id,
                "c" * 64,
                "2026-07-24",
                self.forest_id,
            )

        valid_receipt = {
            "audit": {
                "documents": 0,
                "errors": False,
                "links": 0,
                "ok": True,
                "warnings": 0,
            },
            "date": "2026-07-24",
            "forest_id": self.forest_id,
            "index": {
                "bytes_indexed": 0,
                "documents": 0,
                "index": ".memory-forest/index.sqlite3",
            },
            "ok": True,
            "operation": "apply-daily",
            "plan_sha256": "c" * 64,
            "schema_version": "memory-forest-write-receipt-v1",
            "touched": [],
            "transaction_id": transaction_id,
            "validation": {
                "documents": 0,
                "errors": 0,
                "ok": True,
                "warnings": 0,
            },
        }
        receipt_path.write_bytes(model_workflow._memory_forest_plan_bytes(valid_receipt))
        response["receipt_sha256"] = sha256_bytes(receipt_path.read_bytes())
        with self.assertRaises(ISTMError):
            model_workflow._verify_memory_forest_receipt_file(
                self.memory_forest,
                response,
                "apply-daily",
                transaction_id,
                "c" * 64,
                "2026-07-24",
                self.forest_id,
            )

    def test_all_omitted_daily_closes_with_verified_noop_receipt(self) -> None:
        packet_path, packet = self.daily_packet()
        result = self.valid_daily_result(packet)
        items = packet["items"]
        assert isinstance(items, list)
        result["entries"] = []
        result["omitted"] = [
            {"record_id": item["record_id"], "reason": "low_signal"}
            for item in items
        ]
        result_path = default_result_path(packet_path)
        self.write_json(result_path, result)
        first = self.apply_daily(packet_path, result_path)
        self.assertFalse(first.already_applied)
        traces = [
            json.loads(line)
            for line in self.memory_forest_trace.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(traces[-1]["operation"], "apply-daily")
        self.assertEqual(traces[-1]["plan"]["entries"], [])
        self.assertTrue(self.apply_daily(packet_path, result_path).already_applied)
        with self.assertRaises(NoWorkError):
            prepare_daily_packet(
                date(2026, 7, 24),
                self.istm,
                self.packets,
                self.model_state,
            )

    def test_all_omitted_promotion_closes_with_verified_noop_receipt(self) -> None:
        packet_path, packet = self.daily_packet()
        daily_result_path = default_result_path(packet_path)
        self.write_json(daily_result_path, self.valid_daily_result(packet))
        self.apply_daily(packet_path, daily_result_path)
        prepared = prepare_memory_forest_packet(
            date(2026, 7, 24),
            self.model_daily,
            self.packets,
            self.model_state,
        )
        value = json.loads(prepared.path.read_text(encoding="utf-8"))
        entry_ids = [item["daily_entry_id"] for item in value["items"]]
        result = {
            "schema_version": "codex-istm-model-result-v2",
            "stage": "daily_to_memory_forest",
            "packet_sha256": value["packet_sha256"],
            "producer": {
                "kind": "codex_cli",
                "codex_cli_version": "codex-cli test",
                "model": "example-model",
                "reasoning_effort": "xhigh",
                "isolation_profile": "codex-cli-no-tools-v1",
            },
            "promotions": [],
            "omitted": [
                {"daily_entry_id": entry_id, "reason": "not_durable"}
                for entry_id in entry_ids
            ],
        }
        result_path = default_result_path(prepared.path)
        self.write_json(result_path, result)
        first = self.apply_memory_forest_result(prepared.path, result_path)
        self.assertFalse(first.already_applied)
        self.assertTrue(first.paths[0].is_file())
        self.assertTrue(
            self.apply_memory_forest_result(prepared.path, result_path).already_applied
        )
        with self.assertRaises(NoWorkError):
            prepare_memory_forest_packet(
                date(2026, 7, 24),
                self.model_daily,
                self.packets,
                self.model_state,
            )

    def test_legacy_v1_model_state_and_structured_result_fail_closed(self) -> None:
        self.write_json(
            self.model_state,
            {
                "schema_version": "codex-istm-model-state-v1",
                "daily": {},
                "structured": {},
            },
        )
        ingest(self.sources, self.state, self.istm)
        with self.assertRaises(ISTMError):
            prepare_daily_packet(
                date(2026, 7, 24),
                self.istm,
                self.packets,
                self.model_state,
            )
        self.model_state.unlink()
        daily_packet = prepare_daily_packet(
            date(2026, 7, 24),
            self.istm,
            self.packets,
            self.model_state,
        )
        daily_value = json.loads(daily_packet.path.read_text(encoding="utf-8"))
        daily_result_path = default_result_path(daily_packet.path)
        self.write_json(daily_result_path, self.valid_daily_result(daily_value))
        self.apply_daily(daily_packet.path, daily_result_path)
        memory_packet = prepare_memory_forest_packet(
            date(2026, 7, 24),
            self.model_daily,
            self.packets,
            self.model_state,
        )
        memory_value = json.loads(memory_packet.path.read_text(encoding="utf-8"))
        legacy_result = {
            "schema_version": "codex-istm-model-result-v1",
            "stage": "daily_to_structured",
            "packet_sha256": memory_value["packet_sha256"],
            "producer": {
                "kind": "codex_cli",
                "codex_cli_version": "codex-cli test",
                "model": "example-model",
                "reasoning_effort": "xhigh",
                "isolation_profile": "codex-cli-no-tools-v1",
            },
            "promotions": [],
            "omitted": [],
        }
        legacy_result_path = self.root / "legacy.result.json"
        self.write_json(legacy_result_path, legacy_result)
        with self.assertRaises(ISTMError):
            validate_result(memory_packet.path, legacy_result_path)

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
        self.apply_daily(
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
        self.apply_daily(
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
            self.apply_daily(
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
            self.apply_daily(
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
        applied = self.apply_daily(
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
            "daily-to-memory-forest-result-v2.schema.json",
        ):
            schema = json.loads(schema_root.joinpath(name).read_text(encoding="utf-8"))
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])

    def test_memory_forest_apply_rejects_new_daily_commit_after_prepare(self) -> None:
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
        self.apply_daily(
            first_daily.path,
            first_result,
            self.istm,
            self.model_state,
            self.model_daily,
        )
        structured_packet = prepare_memory_forest_packet(
            date(2026, 7, 24),
            self.model_daily,
            self.packets,
            self.model_state,
        )
        structured_value = json.loads(structured_packet.path.read_text(encoding="utf-8"))
        entry_id = structured_value["items"][0]["daily_entry_id"]
        structured_result = {
            "schema_version": "codex-istm-model-result-v2",
            "stage": "daily_to_memory_forest",
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
        self.apply_daily(
            second_daily.path,
            second_result,
            self.istm,
            self.model_state,
            self.model_daily,
        )
        with self.assertRaises(ISTMError):
            self.apply_memory_forest_result(
                structured_packet.path,
                structured_result_path,
            )
        self.assertFalse((self.root / "structured").exists())
