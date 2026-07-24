# Format and invariants

## ISTM JSONL

Each line is a self-contained JSON object with `schema_version: 1`.

| Field | Meaning |
| --- | --- |
| `transform_version` | Version of this conservative transformation. |
| `record_id` | SHA-256 of the opaque source reference, byte span, and raw-event hash, used for exact replay protection. |
| `captured_at` | The source event timestamp when it is a string; otherwise `null`. |
| `role` | Only `user` or `assistant`. |
| `text` | Locally stored, per-message bounded text. |
| `text_sha256` | SHA-256 of the stored bounded text. |
| `provenance.source_ref` | First 16 hex characters of a SHA-256 source reference; not a path or session ID. |
| `provenance.byte_start`, `provenance.byte_end` | Byte range of the raw event within its local source file. |
| `provenance.event_sha256` | SHA-256 of the raw JSONL event line. |

Known user/assistant text is never coerced from arbitrary objects or tool payloads. Valid but non-conversational or unsupported events are counted in private ingestion state and command results, without copying source metadata or payloads to ISTM.

## Private state

`state.json` has a schema version and a map of local relative source names. Each map entry contains:

- `offset`: the count of source bytes that ended in complete newline-terminated JSONL events;
- `processed_prefix_sha256`: a hash of bytes before that offset;
- `observed_source_sha256`: a hash of the source bytes seen during the most recent run.

The state also retains an ISTM byte checkpoint plus SHA-256. The prefix hash is the ingestion invariant. A later append changes the observed-source hash but leaves the processed-prefix hash valid. A rewrite of processed bytes fails closed. If a process stops after ISTM replacement but before the state checkpoint, the next run accepts only an exact source-derived replay before advancing state.

## Daily Markdown

Daily selection converts offset-bearing ISO timestamps into the requested IANA timezone (default `UTC`). Records are sorted by timestamp then record ID. Unparseable or timezone-naive timestamps do not render. The footer has a SHA-256 over selected record IDs and stored-text hashes, plus an omission count, so the file’s compact provenance can be checked without putting source names in the Markdown. Untrusted text is normalized, HTML-escaped, Markdown-escaped, and stripped of bidirectional controls before it is rendered.

Daily files are deterministic for the same ISTM content and bounds. They are excerpts, not a machine-generated interpretation of a conversation.
