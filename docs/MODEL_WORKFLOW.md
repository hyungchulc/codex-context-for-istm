# Model-assisted Daily and Memory Forest workflow

The optional model workflow uses the Codex CLI already installed and authenticated on the Mac. It does not require a separately maintained provider API key or SDK. It **does send each prepared packet to the configured model provider**. This is not a local-only transform.

The deterministic ingestion commands remain unchanged and make no model call. Model use starts only when an operator explicitly runs `run-model` or `run-model-workflow`. Applying an already validated result does not call the provider, but it does invoke the separately installed Memory Forest CLI to make canonical writes.

## Trust boundary

Each mutating stage has five separate steps:

1. deterministic code freezes an immutable, bounded packet;
2. `codex exec` returns a strict candidate;
3. deterministic code validates schema, bounds, exact source coverage, producer provenance, and packet binding;
4. deterministic code rebinds the current source and invokes Memory Forest with an exact temporary plan;
5. deterministic code verifies the exact stdout response and on-disk receipt before advancing its root-bound cursor.

The model cannot choose a filesystem path, memory layer, operation, Markdown representation, or cursor change. Daily results contain only bounded semantic entries. Memory Forest promotion results use schema `codex-istm-model-result-v2`, stage `daily_to_memory_forest`, and strict promotions shaped as:

```json
{
  "source_daily_entry_ids": ["<daily-entry-sha256>"],
  "route": {
    "domain": "example-domain",
    "domain_title": "Example Domain",
    "branch": "example-branch",
    "branch_title": "Example Branch",
    "leaf": "example-leaf"
  },
  "title": "Example title",
  "content": "Bounded durable content.",
  "confidence": "high"
}
```

No path, layer, operation, or Markdown field is accepted. Memory Forest owns canonical layout, parent creation, rendering, indexing, and idempotent transaction receipts.

Packet items are untrusted data in the model prompt. The runner uses an isolated private temporary working directory, `--ephemeral`, `--sandbox read-only`, `--ignore-user-config`, `--ignore-rules`, `--strict-config`, an explicit model and reasoning effort, and an enumerated set of disabled tool features. These flags reduce local side effects; they do not prove provider-side confidentiality or retention behavior, and a future Codex CLI may change feature semantics.

Sensitive-model omission is a semantic decision made **after the provider has received the bounded packet**. It is not redaction before transmission. Review the packet before `run-model` when its contents require special handling.

## Explicit prepare, run, validate, and apply flow

First ingest new local rollout data:

```zsh
python3 -m codex_istm ingest
```

Freeze a Daily packet:

```zsh
python3 -m codex_istm prepare-model-daily \
  --date previous-local-day \
  --timezone Europe/Stockholm
```

The command prints the content-addressed packet path. Use that exact path:

```zsh
python3 -m codex_istm run-model \
  --packet "$PACKET_PATH" \
  --model "$MODEL_ID" \
  --reasoning-effort xhigh

python3 -m codex_istm validate-model \
  --packet "$PACKET_PATH" \
  --result "${PACKET_PATH%.packet.json}.result.json"

python3 -m codex_istm apply-model \
  --packet "$PACKET_PATH" \
  --result "${PACKET_PATH%.packet.json}.result.json" \
  --memory-forest-root "$MEMORY_FOREST_ROOT" \
  --memory-forest-bin memory-forest
```

After at least one committed Daily batch, freeze a promotion packet:

```zsh
python3 -m codex_istm prepare-model-structured \
  --date previous-local-day \
  --timezone Europe/Stockholm
```

`prepare-model-structured` is retained as a compatibility command name. Its packet stage is `daily_to_memory_forest`, and its result is applied only through `memory-forest --json promote`.

`apply-model` infers the stage from the packet. For Daily, it preserves private JSON and Markdown beneath `model-daily/YYYY-MM-DD/` as immutable handoff evidence, creates a temporary `memory-forest-daily-plan-v1` plan, and runs:

```text
memory-forest --json apply-daily ROOT PLAN
```

For promotion, it creates a temporary `memory-forest-promotion-plan-v1` plan and runs:

```text
memory-forest --json promote ROOT PLAN
```

This package creates no separate Structured or STM artifact tree.

## Canonical transaction plans

The Daily plan contains exactly:

```json
{
  "schema_version": "memory-forest-daily-plan-v1",
  "transaction_id": "<batch-id>",
  "date": "YYYY-MM-DD",
  "entries": [],
  "provenance": {
    "packet_sha256": "<sha256>",
    "result_sha256": "<sha256>",
    "batch_id": "<batch-id>"
  }
}
```

The promotion plan contains exactly:

```json
{
  "schema_version": "memory-forest-promotion-plan-v1",
  "transaction_id": "<result-sha256>",
  "date": "YYYY-MM-DD",
  "promotions": [],
  "provenance": {
    "packet_sha256": "<sha256>",
    "result_sha256": "<sha256>",
    "daily_commit_sha256s": []
  }
}
```

Each promotion packet item binds its Daily source with `daily_result_sha256`. Promotion provenance contains the sorted unique Daily result hashes for entries actually promoted. The packet’s full local commit-marker hashes are a freshness boundary only.

An all-omitted result still invokes Memory Forest with an empty `entries` or `promotions` list. The transaction closes only after a verified no-op receipt.

## Receipt contract and ordering

Memory Forest must exit zero and write exactly one strict JSON object to stdout, with no logging, duplicate keys, trailing object, or extra text:

```json
{
  "schema_version": 1,
  "ok": true,
  "operation": "apply-daily",
  "transaction_id": "<sha256>",
  "already_applied": false,
  "receipt": ".memory-forest/receipts/<sha256>.json",
  "receipt_sha256": "<sha256>",
  "touched": []
}
```

The response must have exactly those fields. `operation` and `transaction_id` must match the plan; `already_applied` must be Boolean; `receipt` must be the canonical transaction path; `receipt_sha256` must be lowercase SHA-256; and `touched` must be sorted, unique, canonical relative paths.

The companion then opens the exact receipt under the real Memory Forest root, refuses symlinks and non-files, enforces a byte bound, verifies the response hash, parses strict JSON, and verifies the successful operation and transaction binding.

Before the first CLI invocation, the local v2 state is durably bound to the
real Memory Forest root and its stable private `forest_id`. The transaction
receipt is verified before any commit marker or cursor advance. Daily handoff
evidence is written before `apply-daily`, but it is not canonical memory. The
`daily` or `memory_forest` cursor advances last. A crash after Memory Forest
success is recovered by retrying the same transaction against the same forest;
a different root or replacement forest identity is rejected.

Legacy model-state v1 and `daily_to_structured` result v1 cannot prove this completion contract and fail closed. Use a new v2 state file or an explicit migration procedure; do not edit version fields in place.

## Bounded one-command flow

The orchestrator preserves packet, result, handoff evidence, and state files:

```zsh
python3 -m codex_istm run-model-workflow daily \
  --date previous-local-day \
  --timezone Europe/Stockholm \
  --memory-forest-root "$MEMORY_FOREST_ROOT" \
  --memory-forest-bin memory-forest \
  --model "$MODEL_ID" \
  --reasoning-effort xhigh \
  --max-batches 8

python3 -m codex_istm run-model-workflow structured \
  --date previous-local-day \
  --timezone Europe/Stockholm \
  --memory-forest-root "$MEMORY_FOREST_ROOT" \
  --memory-forest-bin memory-forest \
  --model "$MODEL_ID" \
  --reasoning-effort xhigh \
  --max-batches 8
```

The `structured` selector is retained for command compatibility; it executes the `daily_to_memory_forest` promotion stage.

`--max-batches` is an explicit cost and work bound. A packet admits at most the configured item and byte limits. Items beyond the current packet are reported as `not_yet_admitted`; they remain eligible for the next batch. Model-omitted items are different: they receive an explicit disposition and advance the cursor only after a verified Memory Forest transaction.

Use the same installed model for both stages unless there is a deliberate reason not to. Nothing in the format requires a specific model.

## Dated reference profiles

These were observed reference choices on 2026-07-24, not defaults, dependencies, recommendations, or routing branches:

- interactive reference: GPT-5.6 Sol / `xhigh`;
- one production automation reference: Daily GPT-5.6 Luna / `xhigh`, promotion GPT-5.6 Sol / `max`.

Most public users can select one installed Codex/GPT model and one supported reasoning effort for both stages. The exact model and effort are recorded in every stored result and Daily handoff artifact.

## launchd and local scheduling

The existing LaunchAgent installs only deterministic ingestion and excerpt rendering. Model jobs are separate, opt-in, and are never installed by that helper.

Two reviewable templates are provided:

- `launchd/io.github.codex-istm-macos.model-daily.plist.template`
- `launchd/io.github.codex-istm-macos.model-structured.plist.template`

Replace every `@TOKEN@`, including `@MEMORY_FOREST_ROOT@` and `@MEMORY_FOREST_BIN@`, validate the rendered plist with `plutil -lint`, and inspect the full command before loading it. The example schedule processes the previous local day: Daily after deterministic ingestion, then promotion later. It caps each run at eight model batches.

```zsh
plutil -lint "$HOME/Library/LaunchAgents/io.github.codex-istm-macos.model-daily.plist"
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/io.github.codex-istm-macos.model-daily.plist"
```

Use a different label and plist for promotion. To process the current day incrementally, change the date argument to `today` and choose an appropriate repeated schedule. The cursor makes later same-day records eligible without replaying already judged records.

Schedule only after reviewing provider privacy, cost, authentication, network, and retention behavior. LaunchAgent environments have a restricted `PATH`, so use absolute Python, Codex, and Memory Forest executable paths.

## Recovery and retention

- A stored model result is immutable. A retry reuses it instead of rerunning the model.
- The local state is bound to one real Memory Forest root before first invocation.
- A verified Memory Forest receipt makes transaction recovery idempotent. State still advances last.
- Source-prefix or Daily-commit drift fails closed. Prepare a fresh packet; do not edit packet or result hashes.
- Handoff packets, results, and model-Daily evidence duplicate sensitive text or summaries and are stored with private permissions. Keep them out of Git and backups you do not control.
- The existing `archive` command remains copy-only for deterministic Daily excerpts. It does not delete model packets, handoff evidence, state, Memory Forest data, or source history.

There is no automatic purge. Back up both the companion data directory and the Memory Forest root before any manual retention change. Do not remove committed model-Daily evidence while it remains a source for promotion preparation.
