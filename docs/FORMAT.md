# Format and invariants

## ISTM JSONL

Each line is a self-contained JSON object with `schema_version: 1`.

| Field | Meaning |
| --- | --- |
| `transform_version` | Version of this conservative transformation. |
| `record_id` | SHA-256 of the opaque source reference, byte span, and raw-event hash. |
| `captured_at` | Source event timestamp when it is a string; otherwise `null`. |
| `role` | Only `user` or `assistant`. |
| `text` | Locally stored, per-message bounded text. |
| `text_sha256` | SHA-256 of the stored bounded text. |
| `provenance.source_ref` | First 16 hex characters of a hashed source reference. |
| `provenance.byte_start`, `provenance.byte_end` | Raw-event byte range. |
| `provenance.event_sha256` | SHA-256 of the raw JSONL event line. |

Known conversation text is never coerced from arbitrary tool payloads. Valid
unsupported events are counted in private state without copying their payloads
into ISTM.

## Deterministic Daily Markdown

`digest` writes `daily/YYYY-MM-DD.md`. It is a bounded chronological rendering
of ISTM, not a model summary. Its footer binds selection counts and hashes.

## Model packet v1

Packets use `schema_version: codex-istm-model-packet-v1` and one of two stages:

- `istm_to_daily`;
- `daily_to_memory_forest`.

Every packet contains an ISO date, IANA timezone, exact source binding,
admission cursor, policy/schema hashes, explicit bounds, bounded items,
`not_yet_admitted_item_count`, and `packet_sha256`.

Daily items contain exact ISTM record IDs and bounded text. Memory Forest items
contain a Daily entry ID, the canonical Daily result SHA-256 that committed that
entry, and a bounded summary. The packet source retains the complete ordered
local Daily marker-hash list solely for freshness rebinding. Paths are never
included.

## Model results

ISTM-to-Daily remains `codex-istm-model-result-v1`. It contains grouped
`entries` with exact `source_record_ids` and `summary`, plus explicit omissions.

Daily-to-Memory-Forest is `codex-istm-model-result-v2` with stage
`daily_to_memory_forest`. Each promotion contains exactly:

- `source_daily_entry_ids`;
- `route` with `domain`, `domain_title`, `branch`, `branch_title`, and `leaf`;
- `title`;
- `content`;
- `confidence`.

Route slugs are lowercase ASCII kebab-case. Titles are bounded single-line NFC
text. Routes must be unique within a result. The result contains no filesystem
path, layer, operation, Markdown, state change, or commit instruction. Every
admitted input ID appears exactly once across the included/promoted and omitted
lists. Unknown, repeated, or missing IDs fail validation.

Both result versions include exact packet binding and producer provenance:
Codex CLI version, explicit model, explicit reasoning effort, and isolation
profile.

## Memory Forest Daily plan v1

Daily apply writes a private temporary JSON object with fields exactly:

```json
{
  "schema_version": "memory-forest-daily-plan-v1",
  "transaction_id": "<daily-batch-id>",
  "date": "2026-07-24",
  "entries": [
    {
      "entry_id": "<sha256>",
      "source_record_ids": ["<sha256>"],
      "summary": "Bounded semantic summary."
    }
  ],
  "provenance": {
    "packet_sha256": "<sha256>",
    "result_sha256": "<sha256>",
    "batch_id": "<daily-batch-id>"
  }
}
```

Deterministic code passes that file to
`memory-forest --json apply-daily ROOT PLAN`.

## Memory Forest promotion plan v1

Promotion apply writes a private temporary JSON object with fields exactly:

```json
{
  "schema_version": "memory-forest-promotion-plan-v1",
  "transaction_id": "<model-result-sha256>",
  "date": "2026-07-24",
  "promotions": [
    {
      "source_daily_entry_ids": ["<sha256>"],
      "route": {
        "domain": "memory-systems",
        "domain_title": "Memory systems",
        "branch": "deterministic-apply",
        "branch_title": "Deterministic apply",
        "leaf": "model-output-gate"
      },
      "title": "Deterministic apply gate",
      "content": "Validated semantic content.",
      "confidence": "high"
    }
  ],
  "provenance": {
    "packet_sha256": "<sha256>",
    "result_sha256": "<sha256>",
    "daily_commit_sha256s": ["<daily-result-sha256>"]
  }
}
```

`daily_commit_sha256s` is the sorted unique set of committed Daily result hashes
for actually promoted source IDs. The complete local marker list remains in the
packet source and is not substituted into this field.

## Writer response and receipt

Writer stdout must be one bounded JSON object with fields exactly:

- integer `schema_version: 1`;
- `ok: true`;
- `operation`: `apply-daily` or `promote`;
- exact 64-lowerhex `transaction_id`;
- Boolean `already_applied`;
- exact relative receipt path
  `.memory-forest/receipts/<transaction_id>.json`;
- 64-lowerhex `receipt_sha256`;
- sorted unique bounded canonical relative `touched` paths.

Nonzero exit, extra stdout, missing or extra response fields, path mismatch,
symlink, missing receipt, hash mismatch, or mismatched receipt operation and
transaction fails before cursor advance. Empty plans are valid receipt-backed
no-ops. Their first receipt has `already_applied: false`; an exact retry has
`already_applied: true`.

## Local handoff evidence and commit marker

Model-Daily JSON and inert Markdown are immutable handoff evidence under:

```text
model-daily/YYYY-MM-DD/
  batches/<packet-sha256>.json
  batches/<packet-sha256>.md
  commits/<batch-id>.json
```

The v2 Daily commit marker is written only after `apply-daily` receipt
verification. It binds JSON, Markdown, exact plan hash, transaction, receipt
path, and receipt hash. Promotion preparation accepts only fully verified
markers and referenced evidence. This package does not create a second
structured-memory output tree.

## Model workflow state v2

`model-state.json` has:

- `schema_version: codex-istm-model-state-v2`;
- `memory_forest_root_sha256`, binding one real Forest root;
- `memory_forest_id`, binding the stable private identity of that Forest;
- independent `daily` and `memory_forest` maps keyed by ISO date.

Each date stores its timezone, every input ID accounted by verified writer
transactions, and applied transaction IDs. The root and identity binding is durably saved
before the first writer invocation; each per-date cursor advances only after its
receipt verifies. Legacy v1 state fails closed because its old structured cursor
cannot prove canonical promotion.
