from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import platform
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .core import (
    DEFAULT_DAILY_EXCERPT_BYTES,
    DEFAULT_DAILY_MAX_BYTES,
    DEFAULT_DAILY_MAX_RECORDS,
    DEFAULT_MAX_MESSAGE_CHARS,
    ISTMError,
    _canonical_json,
    archive_daily,
    ingest,
    render_daily,
    sha256_bytes,
)
from .model_workflow import (
    DAILY_TO_MEMORY_FOREST,
    ISTM_TO_DAILY,
    DEFAULT_PACKET_ITEM_BYTES,
    DEFAULT_PACKET_MAX_ITEMS,
    DEFAULT_PACKET_TOTAL_BYTES,
    NoWorkError,
    apply_model_result,
    default_result_path,
    prepare_daily_packet,
    prepare_memory_forest_packet,
    run_codex_model,
    validate_result,
)


def default_data_dir() -> Path:
    return Path(os.environ.get("CODEX_ISTM_DATA_DIR", "~/Library/Application Support/CodexISTMMacOS")).expanduser()


def default_source_dir() -> Path:
    return Path(os.environ.get("CODEX_ISTM_SOURCE_DIR", "~/.codex/sessions")).expanduser()


def _add_common_locations(parser: argparse.ArgumentParser) -> None:
    data = default_data_dir()
    parser.add_argument("--source-dir", type=Path, default=default_source_dir())
    parser.add_argument("--state", type=Path, default=data / "state.json")
    parser.add_argument("--istm", type=Path, default=data / "istm.jsonl")
    parser.add_argument("--daily-dir", type=Path, default=data / "daily")


def _add_packet_bounds(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-items", type=int, default=DEFAULT_PACKET_MAX_ITEMS)
    parser.add_argument("--item-bytes", type=int, default=DEFAULT_PACKET_ITEM_BYTES)
    parser.add_argument("--total-text-bytes", type=int, default=DEFAULT_PACKET_TOTAL_BYTES)


def _resolve_day(value: str, timezone_name: str) -> date:
    current = datetime.now(ZoneInfo(timezone_name)).date()
    if value == "today":
        return current
    if value == "previous-local-day":
        return current - timedelta(days=1)
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local macOS Codex session history to bounded ISTM/Daily files")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest_parser = subparsers.add_parser("ingest", help="incrementally ingest complete Codex rollout JSONL lines")
    _add_common_locations(ingest_parser)
    ingest_parser.add_argument("--max-message-chars", type=int, default=DEFAULT_MAX_MESSAGE_CHARS)
    ingest_parser.add_argument("--max-event-bytes", type=int, default=1_000_000)
    digest_parser = subparsers.add_parser("digest", help="render one bounded, local daily Markdown digest")
    _add_common_locations(digest_parser)
    digest_parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    digest_parser.add_argument("--max-records", type=int, default=DEFAULT_DAILY_MAX_RECORDS)
    digest_parser.add_argument("--max-bytes", type=int, default=DEFAULT_DAILY_MAX_BYTES)
    digest_parser.add_argument("--excerpt-bytes", type=int, default=DEFAULT_DAILY_EXCERPT_BYTES)
    digest_parser.add_argument("--timezone", default="UTC")
    daily_parser = subparsers.add_parser("run-daily", help="ingest then deterministically render today's local digest")
    _add_common_locations(daily_parser)
    daily_parser.add_argument("--max-message-chars", type=int, default=DEFAULT_MAX_MESSAGE_CHARS)
    daily_parser.add_argument("--max-event-bytes", type=int, default=1_000_000)
    daily_parser.add_argument("--max-records", type=int, default=DEFAULT_DAILY_MAX_RECORDS)
    daily_parser.add_argument("--max-bytes", type=int, default=DEFAULT_DAILY_MAX_BYTES)
    daily_parser.add_argument("--excerpt-bytes", type=int, default=DEFAULT_DAILY_EXCERPT_BYTES)
    daily_parser.add_argument("--timezone", default="UTC")
    archive_parser = subparsers.add_parser("archive", help="copy old daily digests; originals are never deleted")
    _add_common_locations(archive_parser)
    archive_parser.add_argument("--archive-dir", type=Path, default=default_data_dir() / "archive")
    archive_parser.add_argument("--keep-days", type=int, default=30)
    archive_parser.add_argument("--apply", action="store_true", help="perform verified copies (default is a dry run)")
    prepare_daily = subparsers.add_parser(
        "prepare-model-daily",
        help="freeze a bounded ISTM-to-Daily packet; this does not call a model",
    )
    _add_common_locations(prepare_daily)
    prepare_daily.add_argument("--date", default="today", help="ISO date, today, or previous-local-day")
    prepare_daily.add_argument("--timezone", default="UTC")
    prepare_daily.add_argument("--packet-dir", type=Path, default=default_data_dir() / "handoffs")
    prepare_daily.add_argument("--model-state", type=Path, default=default_data_dir() / "model-state.json")
    _add_packet_bounds(prepare_daily)
    prepare_structured = subparsers.add_parser(
        "prepare-model-structured",
        help="freeze a bounded Daily-to-Memory-Forest packet; this does not call a model",
    )
    prepare_structured.add_argument("--date", default="today", help="ISO date, today, or previous-local-day")
    prepare_structured.add_argument("--timezone", default="UTC")
    prepare_structured.add_argument("--model-daily-dir", type=Path, default=default_data_dir() / "model-daily")
    prepare_structured.add_argument("--packet-dir", type=Path, default=default_data_dir() / "handoffs")
    prepare_structured.add_argument("--model-state", type=Path, default=default_data_dir() / "model-state.json")
    _add_packet_bounds(prepare_structured)
    run_model = subparsers.add_parser(
        "run-model",
        help="ask the installed Codex CLI for a strict candidate; canonical memory is read-only",
    )
    run_model.add_argument("--packet", type=Path, required=True)
    run_model.add_argument("--result", type=Path)
    run_model.add_argument("--codex-bin", default="codex")
    run_model.add_argument("--model", required=True)
    run_model.add_argument("--reasoning-effort", required=True)
    run_model.add_argument("--timeout-seconds", type=int, default=900)
    validate_model = subparsers.add_parser("validate-model", help="strictly validate one packet/result pair")
    validate_model.add_argument("--packet", type=Path, required=True)
    validate_model.add_argument("--result", type=Path, required=True)
    apply_model = subparsers.add_parser(
        "apply-model",
        help="apply a validated candidate through the installed Memory Forest CLI",
    )
    apply_model.add_argument("--packet", type=Path, required=True)
    apply_model.add_argument("--result", type=Path, required=True)
    apply_model.add_argument("--istm", type=Path, default=default_data_dir() / "istm.jsonl")
    apply_model.add_argument("--model-state", type=Path, default=default_data_dir() / "model-state.json")
    apply_model.add_argument("--model-daily-dir", type=Path, default=default_data_dir() / "model-daily")
    apply_model.add_argument("--memory-forest-root", type=Path, required=True)
    apply_model.add_argument("--memory-forest-bin", default="memory-forest")
    workflow = subparsers.add_parser(
        "run-model-workflow",
        help="prepare, run, validate, and apply one explicit model-assisted stage",
    )
    workflow.add_argument("stage", choices=("daily", "structured"))
    workflow.add_argument("--date", default="previous-local-day", help="ISO date, today, or previous-local-day")
    workflow.add_argument("--timezone", default="UTC")
    workflow.add_argument("--istm", type=Path, default=default_data_dir() / "istm.jsonl")
    workflow.add_argument("--packet-dir", type=Path, default=default_data_dir() / "handoffs")
    workflow.add_argument("--model-state", type=Path, default=default_data_dir() / "model-state.json")
    workflow.add_argument("--model-daily-dir", type=Path, default=default_data_dir() / "model-daily")
    workflow.add_argument("--memory-forest-root", type=Path, required=True)
    workflow.add_argument("--memory-forest-bin", default="memory-forest")
    workflow.add_argument("--codex-bin", default="codex")
    workflow.add_argument("--model", required=True)
    workflow.add_argument("--reasoning-effort", required=True)
    workflow.add_argument("--timeout-seconds", type=int, default=900)
    workflow.add_argument("--max-batches", type=int, default=1)
    _add_packet_bounds(workflow)
    return parser


def _require_macos() -> None:
    if platform.system() != "Darwin":
        raise ISTMError("codex-istm-macos is intentionally supported on macOS only")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _require_macos()
        if args.command == "ingest":
            result = ingest(args.source_dir, args.state, args.istm, args.max_message_chars, args.max_event_bytes)
            print(f"ingested={result.new_records} duplicates={result.duplicate_records} sources={result.sources_checked} pending_bytes={result.pending_bytes} unsupported_events={result.unsupported_events}")
        elif args.command == "digest":
            result = render_daily(args.date, args.istm, args.daily_dir, args.max_records, args.max_bytes, args.excerpt_bytes, args.timezone)
            print(f"digest={result.path} records={result.records} omitted={result.omitted_records} selection_sha256={result.selection_sha256}")
        elif args.command == "run-daily":
            ingested = ingest(args.source_dir, args.state, args.istm, args.max_message_chars, args.max_event_bytes)
            current_day = datetime.now(ZoneInfo(args.timezone)).date()
            result = render_daily(current_day, args.istm, args.daily_dir, args.max_records, args.max_bytes, args.excerpt_bytes, args.timezone)
            print(f"ingested={ingested.new_records} digest={result.path} records={result.records} omitted={result.omitted_records} selection_sha256={result.selection_sha256}")
        elif args.command == "archive":
            result = archive_daily(args.daily_dir, args.archive_dir, date.today(), args.keep_days, args.apply)
            mode = "dry_run" if result.dry_run else "copied"
            print(f"archive_{mode}={len(result.copied)}")
            for path in result.copied:
                print(path)
        elif args.command == "prepare-model-daily":
            selected_day = _resolve_day(args.date, args.timezone)
            result = prepare_daily_packet(
                selected_day,
                args.istm,
                args.packet_dir,
                args.model_state,
                args.timezone,
                args.max_items,
                args.item_bytes,
                args.total_text_bytes,
            )
            print(
                f"packet={result.path} stage={ISTM_TO_DAILY} items={result.items} "
                f"not_yet_admitted={result.not_yet_admitted_items} packet_sha256={result.packet_sha256}"
            )
        elif args.command == "prepare-model-structured":
            selected_day = _resolve_day(args.date, args.timezone)
            result = prepare_memory_forest_packet(
                selected_day,
                args.model_daily_dir,
                args.packet_dir,
                args.model_state,
                args.timezone,
                args.max_items,
                args.item_bytes,
                args.total_text_bytes,
            )
            print(
                f"packet={result.path} stage={DAILY_TO_MEMORY_FOREST} items={result.items} "
                f"not_yet_admitted={result.not_yet_admitted_items} packet_sha256={result.packet_sha256}"
            )
        elif args.command == "run-model":
            result_path = args.result or default_result_path(args.packet)
            result = run_codex_model(
                args.packet,
                result_path,
                args.codex_bin,
                args.model,
                args.reasoning_effort,
                args.timeout_seconds,
            )
            print(f"result={result.path} result_sha256={result.result_sha256}")
        elif args.command == "validate-model":
            packet, result = validate_result(args.packet, args.result)
            print(
                f"valid=true stage={packet['stage']} packet_sha256={packet['packet_sha256']} "
                f"result_sha256={sha256_bytes(_canonical_json(result))}"
            )
        elif args.command == "apply-model":
            applied = apply_model_result(
                args.packet,
                args.result,
                args.istm,
                args.model_state,
                args.model_daily_dir,
                args.memory_forest_root,
                args.memory_forest_bin,
            )
            print(f"applied={not applied.already_applied} paths={len(applied.paths)}")
            for path in applied.paths:
                print(path)
        elif args.command == "run-model-workflow":
            selected_day = _resolve_day(args.date, args.timezone)
            if args.max_batches < 1 or args.max_batches > 32:
                raise ValueError("max_batches must be between 1 and 32")
            completed_batches = 0
            last_packet: Path | None = None
            last_result: Path | None = None
            last_applied = False
            for _ in range(args.max_batches):
                try:
                    if args.stage == "daily":
                        packet = prepare_daily_packet(
                            selected_day,
                            args.istm,
                            args.packet_dir,
                            args.model_state,
                            args.timezone,
                            args.max_items,
                            args.item_bytes,
                            args.total_text_bytes,
                        )
                    else:
                        packet = prepare_memory_forest_packet(
                            selected_day,
                            args.model_daily_dir,
                            args.packet_dir,
                            args.model_state,
                            args.timezone,
                            args.max_items,
                            args.item_bytes,
                            args.total_text_bytes,
                        )
                except NoWorkError:
                    if completed_batches:
                        break
                    raise
                result_path = default_result_path(packet.path)
                if result_path.exists():
                    _, prior_result = validate_result(packet.path, result_path)
                    producer = prior_result["producer"]
                    if (
                        producer["model"] != args.model
                        or producer["reasoning_effort"] != args.reasoning_effort
                    ):
                        raise ISTMError("Existing result uses a different explicit model or reasoning effort")
                else:
                    run_codex_model(
                        packet.path,
                        result_path,
                        args.codex_bin,
                        args.model,
                        args.reasoning_effort,
                        args.timeout_seconds,
                    )
                applied = apply_model_result(
                    packet.path,
                    result_path,
                    args.istm,
                    args.model_state,
                    args.model_daily_dir,
                    args.memory_forest_root,
                    args.memory_forest_bin,
                )
                completed_batches += 1
                last_packet = packet.path
                last_result = result_path
                last_applied = not applied.already_applied
            print(
                f"workflow={args.stage} date={selected_day.isoformat()} batches={completed_batches} "
                f"last_packet={last_packet} last_result={last_result} last_applied={last_applied}"
            )
        return 0
    except NoWorkError as error:
        print(f"no_work: {error}")
        return 0
    except (ISTMError, ValueError, ZoneInfoNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
