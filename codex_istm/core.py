from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCHEMA_VERSION = 1
TRANSFORM_VERSION = 1
STATE_SCHEMA_VERSION = 2
DEFAULT_MAX_MESSAGE_CHARS = 8_000
DEFAULT_MAX_EVENT_BYTES = 1_000_000
DEFAULT_DAILY_MAX_RECORDS = 80
DEFAULT_DAILY_MAX_BYTES = 24_000
DEFAULT_DAILY_EXCERPT_BYTES = 480


class ISTMError(RuntimeError):
    pass


class SourceMutationError(ISTMError):
    pass


@dataclass(frozen=True)
class IngestResult:
    new_records: int
    duplicate_records: int
    sources_checked: int
    pending_bytes: int
    unsupported_events: int


@dataclass(frozen=True)
class DigestResult:
    path: Path
    records: int
    omitted_records: int
    selection_sha256: str


@dataclass(frozen=True)
class ArchiveResult:
    copied: tuple[Path, ...]
    dry_run: bool


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _empty_checkpoint() -> dict[str, Any]:
    return {"offset": 0, "sha256": sha256_bytes(b"")}


def _empty_state() -> dict[str, Any]:
    return {"schema_version": STATE_SCHEMA_VERSION, "sources": {}, "istm": _empty_checkpoint(), "unsupported_events": 0}


def _atomic_write_bytes(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


@contextmanager
def _writer_lock(state_path: Path) -> Iterator[None]:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_name(state_path.name + ".lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _load_json_object(path: Path, missing: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return missing
    try:
        parsed = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_object,
            parse_int=_parse_integer,
            parse_float=_parse_decimal,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ISTMError(f"Cannot read local state {path.name}: {error}") from error
    if not isinstance(parsed, dict):
        raise ISTMError(f"Local state {path.name} must be a JSON object")
    return parsed


def _load_state(path: Path) -> dict[str, Any]:
    state = _load_json_object(path, _empty_state())
    checkpoint = state.get("istm")
    if (
        state.get("schema_version") != STATE_SCHEMA_VERSION
        or not isinstance(state.get("sources"), dict)
        or not isinstance(checkpoint, dict)
        or not isinstance(checkpoint.get("offset"), int)
        or not isinstance(checkpoint.get("sha256"), str)
        or not isinstance(state.get("unsupported_events"), int)
        or state["unsupported_events"] < 0
    ):
        raise ISTMError("Unsupported or malformed ingestion state; refusing to guess")
    return state


def _reject_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ISTMError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_integer(value: str) -> int:
    if len(value.lstrip("-")) > 64:
        raise ISTMError("JSON integer exceeds local safety bound")
    return int(value)


def _parse_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ISTMError("Invalid JSON number") from error
    if not parsed.is_finite():
        raise ISTMError("Non-finite JSON number is not allowed")
    return parsed


def _reject_nonfinite(value: str) -> None:
    raise ISTMError(f"Non-finite JSON constant is not allowed: {value}")


def _contains_lone_surrogate(value: Any) -> bool:
    if isinstance(value, str):
        return any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    if isinstance(value, list):
        return any(_contains_lone_surrogate(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_lone_surrogate(key) or _contains_lone_surrogate(item) for key, item in value.items())
    return False


def _parse_event(raw_line: bytes, relative_source: str, start: int, max_event_bytes: int) -> dict[str, Any]:
    if len(raw_line) > max_event_bytes:
        raise ISTMError(f"Complete JSONL event exceeds local byte bound in {relative_source} at byte {start}")
    try:
        decoded = raw_line.decode("utf-8")
        event = json.loads(
            decoded,
            object_pairs_hook=_reject_duplicate_object,
            parse_int=_parse_integer,
            parse_float=_parse_decimal,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ISTMError) as error:
        raise ISTMError(f"Malformed complete JSONL line in {relative_source} at byte {start}") from error
    if not isinstance(event, dict) or _contains_lone_surrogate(event):
        raise ISTMError(f"Unsafe JSONL event in {relative_source} at byte {start}")
    return event


def _validated_istm_record(record: Any, number: int) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != {"schema_version", "transform_version", "record_id", "captured_at", "role", "text", "text_sha256", "provenance"}:
        raise ISTMError(f"ISTM output has an unsupported record at line {number}")
    provenance = record["provenance"]
    if (
        record["schema_version"] != SCHEMA_VERSION
        or record["transform_version"] != TRANSFORM_VERSION
        or not isinstance(record["record_id"], str)
        or len(record["record_id"]) != 64
        or not (isinstance(record["captured_at"], str) or record["captured_at"] is None)
        or record["role"] not in {"user", "assistant"}
        or not isinstance(record["text"], str)
        or not isinstance(record["text_sha256"], str)
        or len(record["text_sha256"]) != 64
        or not isinstance(provenance, dict)
        or set(provenance) != {"source_ref", "byte_start", "byte_end", "event_sha256"}
        or not isinstance(provenance["source_ref"], str)
        or len(provenance["source_ref"]) != 16
        or not isinstance(provenance["byte_start"], int)
        or not isinstance(provenance["byte_end"], int)
        or provenance["byte_start"] < 0
        or provenance["byte_end"] < provenance["byte_start"]
        or not isinstance(provenance["event_sha256"], str)
        or len(provenance["event_sha256"]) != 64
    ):
        raise ISTMError(f"ISTM output has an invalid record at line {number}")
    return record


def _read_istm(path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], bytes]:
    if not path.exists():
        return [], {}, b""
    try:
        raw = path.read_bytes()
        decoded = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ISTMError(f"Cannot read ISTM output {path.name}: {error}") from error
    if raw and not raw.endswith(b"\n"):
        raise ISTMError("ISTM output has an incomplete trailing line; refusing ambiguous recovery")
    records: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for number, line in enumerate(decoded.splitlines(), start=1):
        if not line.strip():
            raise ISTMError(f"ISTM output has a blank line at {number}; refusing ambiguous deduplication")
        try:
            record = json.loads(
                line,
                object_pairs_hook=_reject_duplicate_object,
                parse_int=_parse_integer,
                parse_float=_parse_decimal,
                parse_constant=_reject_nonfinite,
            )
        except (json.JSONDecodeError, ISTMError) as error:
            raise ISTMError(f"ISTM output has invalid JSON at line {number}") from error
        record = _validated_istm_record(record, number)
        record_id = record["record_id"]
        if record_id in by_id:
            raise ISTMError("ISTM output already contains duplicate record_ids; refusing to add to it")
        by_id[record_id] = record
        records.append(record)
    return records, by_id, raw


def _complete_lines(data: bytes) -> Iterable[tuple[int, int, bytes]]:
    start = 0
    while True:
        newline = data.find(b"\n", start)
        if newline < 0:
            return
        end = newline + 1
        yield start, end, data[start:end]
        start = end


def _extract_text(payload: dict[str, Any]) -> str | None:
    if payload.get("type") != "message" or payload.get("role") not in {"user", "assistant"}:
        return None
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return content["text"]
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") in {"input_text", "output_text", "text"} and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(parts) if parts else None


def _bounded_text(text: str, maximum: int) -> str:
    if maximum < 64:
        raise ValueError("max_message_chars must be at least 64")
    cleaned = text.replace("\x00", "").strip()
    if len(cleaned) <= maximum:
        return cleaned
    marker = "\n[truncated locally]"
    return cleaned[: maximum - len(marker)] + marker


def _source_ref(relative_source: str) -> str:
    return sha256_bytes(("codex-session-v1\0" + relative_source).encode("utf-8"))[:16]


def _make_record(event: dict[str, Any], raw_line: bytes, relative_source: str, start: int, end: int, maximum: int) -> dict[str, Any] | None:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    text = _extract_text(payload)
    if text is None:
        return None
    text = _bounded_text(text, maximum)
    if not text:
        return None
    source_ref = _source_ref(relative_source)
    event_sha256 = sha256_bytes(raw_line)
    identity = f"codex-istm-v1\0{source_ref}\0{start}\0{end}\0{event_sha256}".encode("ascii")
    return {
        "schema_version": SCHEMA_VERSION,
        "transform_version": TRANSFORM_VERSION,
        "record_id": sha256_bytes(identity),
        "captured_at": event["timestamp"] if isinstance(event.get("timestamp"), str) else None,
        "role": payload["role"],
        "text": text,
        "text_sha256": sha256_bytes(text.encode("utf-8")),
        "provenance": {
            "source_ref": source_ref,
            "byte_start": start,
            "byte_end": end,
            "event_sha256": event_sha256,
        },
    }


def _validate_saved_source(relative_source: str, saved: Any, data: bytes) -> int:
    if not isinstance(saved, dict):
        raise ISTMError(f"Malformed saved state for {relative_source}")
    offset = saved.get("offset")
    expected_prefix = saved.get("processed_prefix_sha256")
    if (
        not isinstance(offset, int)
        or offset < 0
        or offset > len(data)
        or not isinstance(expected_prefix, str)
        or saved.get("source_ref") != _source_ref(relative_source)
    ):
        raise ISTMError(f"Malformed offset or hash for {relative_source}")
    if sha256_bytes(data[:offset]) != expected_prefix:
        raise SourceMutationError(f"Previously processed bytes changed in {relative_source}; state and ISTM output were left untouched")
    return offset


def _source_files(source_dir: Path) -> list[Path]:
    if not source_dir.is_dir():
        raise ISTMError("Codex session directory is unavailable; no output was changed")
    files: list[Path] = []
    for path in source_dir.rglob("*.jsonl"):
        if path.is_symlink():
            raise ISTMError("Symlinked session sources are refused")
        if path.is_file():
            files.append(path)
    return sorted(files)


def _validate_checkpoint(state: dict[str, Any], raw_istm: bytes) -> int:
    checkpoint = state["istm"]
    offset = checkpoint["offset"]
    if offset < 0 or offset > len(raw_istm) or sha256_bytes(raw_istm[:offset]) != checkpoint["sha256"]:
        raise ISTMError("ISTM checkpoint does not match output; refusing checkpoint-ahead or corrupted state")
    return offset


def _state_source(relative_source: str, data: bytes, consumed: int) -> dict[str, Any]:
    return {
        "source_ref": _source_ref(relative_source),
        "offset": consumed,
        "processed_prefix_sha256": sha256_bytes(data[:consumed]),
        "observed_length": len(data),
        "observed_source_sha256": sha256_bytes(data),
    }


def ingest(
    source_dir: Path,
    state_path: Path,
    istm_path: Path,
    max_message_chars: int = DEFAULT_MAX_MESSAGE_CHARS,
    max_event_bytes: int = DEFAULT_MAX_EVENT_BYTES,
) -> IngestResult:
    if max_event_bytes < 1:
        raise ValueError("max_event_bytes must be positive")
    source_dir = source_dir.expanduser().resolve()
    state_path = state_path.expanduser()
    istm_path = istm_path.expanduser()
    with _writer_lock(state_path):
        state = _load_state(state_path)
        existing, records_by_id, raw_istm = _read_istm(istm_path)
        checkpoint_offset = _validate_checkpoint(state, raw_istm)
        files = _source_files(source_dir)
        relative_sources = {path.relative_to(source_dir).as_posix() for path in files}
        missing_sources = sorted(set(state["sources"]) - relative_sources)
        if missing_sources:
            raise ISTMError("A previously tracked source is unavailable; preserve or restore it before continuing")
        candidates: list[dict[str, Any]] = []
        staged_sources: dict[str, dict[str, Any]] = {}
        pending_bytes = 0
        unsupported_events = 0
        for path in files:
            relative_source = path.relative_to(source_dir).as_posix()
            try:
                data = path.read_bytes()
            except OSError as error:
                raise ISTMError(f"Cannot read session source {relative_source}: {error}") from error
            saved = state["sources"].get(relative_source)
            offset = 0 if saved is None else _validate_saved_source(relative_source, saved, data)
            consumed = offset
            for local_start, local_end, raw_line in _complete_lines(data[offset:]):
                start, end = offset + local_start, offset + local_end
                consumed = end
                if not raw_line.strip():
                    continue
                event = _parse_event(raw_line, relative_source, start, max_event_bytes)
                record = _make_record(event, raw_line, relative_source, start, end, max_message_chars)
                if record is None:
                    unsupported_events += 1
                else:
                    candidates.append(record)
            pending_bytes += len(data) - consumed
            staged_sources[relative_source] = _state_source(relative_source, data, consumed)
        try:
            tail_text = raw_istm[checkpoint_offset:].decode("utf-8")
            tail_records = [
                _validated_istm_record(
                    json.loads(
                        line,
                        object_pairs_hook=_reject_duplicate_object,
                        parse_int=_parse_integer,
                        parse_float=_parse_decimal,
                        parse_constant=_reject_nonfinite,
                    ),
                    index,
                )
                for index, line in enumerate(tail_text.splitlines(), start=1)
            ]
        except (UnicodeDecodeError, json.JSONDecodeError, ISTMError) as error:
            raise ISTMError("ISTM output after its checkpoint is invalid") from error
        candidate_by_id = {record["record_id"]: record for record in candidates}
        if len(candidate_by_id) != len(candidates):
            raise ISTMError("Source produced duplicate provenance identities; refusing ambiguous replay")
        expected_tail = [candidate_by_id[record["record_id"]] for record in tail_records if isinstance(record, dict) and record.get("record_id") in candidate_by_id]
        if tail_records != expected_tail:
            raise ISTMError("ISTM output has records beyond checkpoint that cannot be proven as exact replays")
        staged_records: list[dict[str, Any]] = []
        duplicate_records = 0
        for record in candidates:
            previous = records_by_id.get(record["record_id"])
            if previous is None:
                staged_records.append(record)
                records_by_id[record["record_id"]] = record
                continue
            if _canonical_json(previous) != _canonical_json(record):
                raise ISTMError("Record identity collision or conflicting provenance; refusing to deduplicate")
            duplicate_records += 1
        serialized = raw_istm + b"".join(_canonical_json(record) + b"\n" for record in staged_records)
        if staged_records:
            _atomic_write_bytes(istm_path, serialized)
        next_state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "sources": {**state["sources"], **staged_sources},
            "istm": {"offset": len(serialized), "sha256": sha256_bytes(serialized)},
            "unsupported_events": state["unsupported_events"] + unsupported_events,
        }
        if staged_sources or staged_records:
            _atomic_write_bytes(state_path, json.dumps(next_state, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n")
        return IngestResult(len(staged_records), duplicate_records, len(files), pending_bytes, unsupported_events)


def _daily_date(record: dict[str, Any], zone: ZoneInfo) -> date | None:
    captured_at = record.get("captured_at")
    if not isinstance(captured_at, str):
        return None
    try:
        parsed = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(zone).date()


def _daily_records(records: Iterable[dict[str, Any]], day: date, zone: ZoneInfo) -> list[dict[str, Any]]:
    return sorted(
        (record for record in records if _daily_date(record, zone) == day),
        key=lambda record: (record.get("captured_at") or "", record["record_id"]),
    )


def _truncate_utf8(text: str, maximum: int) -> str:
    if len(text.encode("utf-8")) <= maximum:
        return text
    marker = "…"
    available = maximum - len(marker.encode("utf-8"))
    if available < 0:
        return ""
    selected: list[str] = []
    used = 0
    for character in text:
        size = len(character.encode("utf-8"))
        if used + size > available:
            break
        selected.append(character)
        used += size
    return "".join(selected).rstrip() + marker


def _daily_excerpt(text: str, maximum: int) -> str:
    without_bidi = re.sub("[\u200b-\u200f\u202a-\u202e\u2066-\u2069]", "", text)
    normalized = re.sub(r"\s+", " ", without_bidi).strip()
    escaped = html.escape(normalized, quote=False)
    escaped = re.sub(r"([\\`*_{}\[\]<>()#+\-.!|])", r"\\\1", escaped)
    return _truncate_utf8(escaped, maximum)


def render_daily(
    day: date,
    istm_path: Path,
    daily_dir: Path,
    max_records: int = DEFAULT_DAILY_MAX_RECORDS,
    max_bytes: int = DEFAULT_DAILY_MAX_BYTES,
    excerpt_bytes: int = DEFAULT_DAILY_EXCERPT_BYTES,
    timezone_name: str = "UTC",
) -> DigestResult:
    if min(max_records, max_bytes, excerpt_bytes) < 1:
        raise ValueError("daily bounds must be positive")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"Unknown timezone: {timezone_name}") from error
    records, _, _ = _read_istm(istm_path.expanduser())
    available = _daily_records(records, day, zone)
    selected: list[dict[str, Any]] = []
    used = 0
    for record in available:
        if len(selected) >= max_records:
            break
        excerpt = _daily_excerpt(str(record["text"]), excerpt_bytes)
        excerpt_size = len(excerpt.encode("utf-8"))
        if selected and used + excerpt_size > max_bytes:
            break
        if not selected and excerpt_size > max_bytes:
            excerpt = _truncate_utf8(excerpt, max_bytes)
            excerpt_size = len(excerpt.encode("utf-8"))
        copy = dict(record)
        copy["_excerpt"] = excerpt
        selected.append(copy)
        used += excerpt_size
    selection_sha256 = sha256_bytes(_canonical_json([{key: record[key] for key in ("record_id", "text_sha256")} for record in selected]))
    omitted = len(available) - len(selected)
    lines = [
        f"# Codex local daily digest — {day.isoformat()} ({timezone_name})",
        "",
        "Local chronological excerpts only. This file is not an AI summary and is never sent by this tool.",
        "",
    ]
    for index, record in enumerate(selected, start=1):
        provenance = record["provenance"]
        lines.extend(
            [
                f"## {index}. {record['role'].title()}",
                "",
                f"- `record={record['record_id'][:12]} source={provenance['source_ref']} bytes={provenance['byte_start']}-{provenance['byte_end']} text={record['text_sha256'][:12]}`",
                f"- {record['_excerpt']}",
                "",
            ]
        )
    lines.append(f"<!-- codex-istm provenance=v1 records={len(selected)} omitted={omitted} selection_sha256={selection_sha256} -->")
    path = daily_dir.expanduser() / f"{day.isoformat()}.md"
    _atomic_write_bytes(path, ("\n".join(lines) + "\n").encode("utf-8"))
    return DigestResult(path, len(selected), omitted, selection_sha256)


def archive_daily(daily_dir: Path, archive_dir: Path, today: date, keep_days: int, apply: bool = False) -> ArchiveResult:
    if keep_days < 0:
        raise ValueError("keep_days must not be negative")
    cutoff = today - timedelta(days=keep_days)
    candidates: list[Path] = []
    if not daily_dir.exists():
        return ArchiveResult((), not apply)
    for path in sorted(daily_dir.glob("????-??-??.md")):
        if path.is_symlink():
            raise ISTMError("Symlinked Daily files are refused")
        try:
            file_day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if file_day < cutoff:
            candidates.append(path)
    if not apply:
        return ArchiveResult(tuple(candidates), True)
    copied: list[Path] = []
    for source in candidates:
        destination = archive_dir / source.stem[:4] / source.stem[5:7] / source.name
        contents = source.read_bytes()
        if destination.exists():
            if destination.is_symlink() or sha256_bytes(destination.read_bytes()) != sha256_bytes(contents):
                raise ISTMError(f"Archive destination differs for {source.name}; refusing overwrite")
        else:
            _atomic_write_bytes(destination, contents)
        if sha256_bytes(destination.read_bytes()) != sha256_bytes(contents):
            raise ISTMError(f"Archive verification failed for {source.name}")
        copied.append(destination)
    return ArchiveResult(tuple(copied), False)
