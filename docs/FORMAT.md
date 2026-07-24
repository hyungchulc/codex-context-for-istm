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

## Model packet v1

A model packet is immutable, content-addressed JSON with
`schema_version: codex-istm-model-packet-v1`. Both stages use a closed
stage-specific shape:

- `stage`: `istm_to_daily` or `daily_to_structured`;
- strict ISO `date` and IANA `timezone`;
- `source`: exact ISTM prefix byte/hash binding or the complete ordered list of
  committed Daily marker hashes;
- `admission_cursor`: timezone, all already accounted item IDs, applied batch
  IDs, and an exact cursor hash;
- `policy`: deterministic policy, prompt, and packaged result-schema bindings;
- `bounds`: maximum admitted items, per-item UTF-8 bytes, and total text bytes;
- `items`: only the bounded text and opaque identities required for judgment;
- `not_yet_admitted_item_count`: eligible items left for a later bounded batch;
- `packet_sha256`: SHA-256 over canonical JSON excluding that field.

The packet contains no source path. `not_yet_admitted_item_count` is not a
model decision. Model omissions appear only in the result and are marked
accounted after verified apply.

## Model result v1

The installed Codex CLI is given one of the packaged JSON Schemas. A stored
result has `schema_version: codex-istm-model-result-v1`, exact `stage` and
`packet_sha256`, and producer provenance:

- Codex CLI version;
- explicit model identifier;
- explicit reasoning effort;
- isolation profile identifier.

Daily results contain grouped `entries` and explicit `omitted` record
dispositions. Structured results contain bounded STM `promotions` and explicit
`omitted` Daily-entry dispositions. Every admitted input ID must appear exactly
once across those lists. Unknown, duplicated, or missing IDs fail validation.

The model returns semantic fields only. It cannot return a filesystem path,
layer, cursor, commit marker, or state mutation.

## Model workflow state v1

`model-state.json` has independent `daily` and `structured` maps keyed by ISO
date. Each date stores:

- the fixed IANA timezone;
- every input ID already accounted by a verified batch;
- every applied batch/result ID.

State advances after artifact readback and commit-marker creation. A crash
before state mutation leaves inputs eligible for an exact retry. A state entry
using another timezone fails closed.

## Committed model-Daily batch

The machine-readable batch JSON has
`schema_version: codex-istm-daily-memory-v1`. It binds the source ISTM prefix,
packet, result, producer, admission cursor, generated entry IDs, explicit model
omissions, and items left for the next batch.

Daily JSON and inert Markdown are immutable files named by packet hash. A
`codex-istm-applied-result-v1` marker binds both relative paths and byte hashes.
Only a pair with a valid marker is committed output.

## Generated STM card

Structured apply renders model title/content into inert Markdown and chooses a
fixed content-addressed path:

```text
structured/stm/YYYY-MM-DD/<memory-id>.md
```

The card records generated-STM namespace, date, confidence, opaque Daily entry
references, memory ID, packet hash, and result hash. An apply marker binds every
card path and hash. Result strings are never used as path components.

These cards are the committed generated STM inbox owned by this companion
utility and remain low-trust generated data. They are not canonical Memory
Forest promotion. This format does not define another system's MTM/LTM/XLTM
hierarchy.
