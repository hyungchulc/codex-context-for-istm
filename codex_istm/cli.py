from __future__ import annotations

import argparse
from datetime import date, datetime
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
    archive_daily,
    ingest,
    render_daily,
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
        return 0
    except (ISTMError, ValueError, ZoneInfoNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
