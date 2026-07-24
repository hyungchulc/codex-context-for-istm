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

The model cannot choose a raw filesystem path, delete, move, arbitrary
operation, or cursor change. Daily results contain only bounded semantic
entries. Before a Structured model call, deterministic code freezes bounded
current XLTM/LTM/MTM/STM documents through `memory-forest
structured-context` and includes the exact versioned layer and split policy.
The Structured result uses schema `codex-istm-model-result-v3`, stage
`daily_to_memory_forest`, and strict changes shaped as:

```json
{
  "action": "create",
  "target": {
    "layer": "stm",
    "tree": "example-tree",
    "branch": "example-branch",
    "leaf": "example-leaf"
  },
  "expected_sha256": null,
  "body": "# Complete validator-ready Markdown\n",
  "source_daily_entry_ids": ["<daily-entry-sha256>"],
  "reason": "Why this exact structured object changes.",
  "confidence": "high"
}
```

The target union accepts only identifiers valid for XLTM, LTM, MTM, or STM.
Creates require a missing target and null preimage. Replacements require the
exact frozen body hash. Every Daily item also receives one exact `promoted`,
`already_covered`, `source_only`, or `promotion_debt` disposition. Memory
Forest owns canonical path mapping, whole-sweep rollback, structural
validation, audit, indexing, and idempotent receipts.

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

After at least one committed Daily batch, freeze an integrated Structured
packet:

```zsh
python3 -m codex_istm prepare-model-structured \
  --date previous-local-day \
  --timezone Europe/Stockholm \
  --memory-forest-root "$MEMORY_FOREST_ROOT" \
  --memory-forest-bin memory-forest
```

Its packet stage remains `daily_to_memory_forest`. Preparation invokes
`memory-forest --json structured-context` for each bounded Daily summary,
deduplicates the returned current documents, verifies their exact hashes, and
binds the resulting Forest snapshot plus the bundled Structured policy into the
packet. This explicit read crosses the canonical body boundary and sends the
selected bodies to the configured model provider when `run-model` is invoked.
The policy's object hierarchy is exactly XLTM Forest, LTM Tree, MTM Branch, and
STM Leaf. Its semantic targets use `tree` for the owning LTM tree; no separate
domain object exists.

`apply-model` infers the stage from the packet. For Daily, it preserves private JSON and Markdown beneath `model-daily/YYYY-MM-DD/` as immutable handoff evidence, creates a temporary `memory-forest-daily-plan-v1` plan, and runs:

```text
memory-forest --json apply-daily ROOT PLAN
```

For Structured memory, it creates a temporary
`memory-forest-structured-sweep-plan-v1` and runs:

```text
memory-forest --json apply-structured ROOT PLAN
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

The Structured sweep plan contains exactly:

```json
{
  "schema_version": "memory-forest-structured-sweep-plan-v1",
  "transaction_id": "<result-sha256>",
  "date": "YYYY-MM-DD",
  "changes": [],
  "dispositions": [],
  "provenance": {
    "packet_sha256": "<sha256>",
    "result_sha256": "<sha256>",
    "forest_snapshot_sha256": "<sha256>",
    "daily_commit_sha256s": []
  }
}
```

Each Structured packet item binds its Daily source with
`daily_result_sha256`. Structured provenance contains the sorted unique Daily
result hashes for every disposed entry and the exact whole-Structured-Forest
preimage. The packet separately binds the bounded selected bodies and their
source routes. The packet’s full local commit-marker hashes remain an
independent freshness boundary.

An all-source-only Structured result still invokes Memory Forest with empty
`changes` and complete `dispositions`. The transaction closes only after a
verified no-op receipt.

## Layer and structure judgment

The model must apply the bundled
`codex-istm-structured-policy-v1` exactly.

- STM is the detailed reconstructable layer. Meaningful one-off asks, named
  entities, corrections, episodes, exact state, failures, commands, and
  verification are STM candidates. Create a named leaf when a branch-root body
  would mix different reread questions, or when exact numbers, deadlines,
  payments, balances, administrative routes, corrections, or source state
  deserve a precise target. Leaf splitting is active.
- MTM is the recurring live branch layer. Promote an STM flow when it repeats
  or remains active as a project, interest, capability, concern, or follow-up
  lane. Create a branch when its current center and reread questions separate
  from existing branches. Branch splitting is moderate.
- LTM is the durable tree layer. Promote stable concerns, enduring preference
  clusters, long-lived capability context, and durable themes when a distinct
  tree improves later rereading and classification. Tree splitting is
  conservative.
- XLTM is the forest. It owns identity-level truths, persistent direction,
  strong preferences, long-horizon anchors, and forest-wide classification
  authority. Update it only when repeated strong evidence establishes a
  long-horizon rule that the current forest cannot safely express.

This is one model decision over all relevant structured layers. When that
decision requires a missing chain, the result includes the necessary parent and
child bodies in the same sweep. Parent-before-child is only the deterministic
materialization rule inside that transaction.

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

The `structured` selector executes the integrated
`daily_to_memory_forest` Structured stage.

`--max-batches` is an explicit cost and work bound. A packet admits at most the
configured item and byte limits. Items beyond the current packet are reported
as `not_yet_admitted`; they remain eligible for the next batch. Structured
items receive an explicit disposition and advance the cursor only after a
verified Memory Forest transaction.

Use the same installed model for both stages unless there is a deliberate reason not to. Nothing in the format requires a specific model.

## Dated reference profiles

These were observed reference choices on 2026-07-24, not defaults, dependencies, recommendations, or routing branches:

- interactive reference: GPT-5.6 Sol / `xhigh`;
- one production automation reference: Daily GPT-5.6 Luna / `xhigh`,
  Structured GPT-5.6 Sol / `max`.

Most public users can select one installed Codex/GPT model and one supported reasoning effort for both stages. The exact model and effort are recorded in every stored result and Daily handoff artifact.

## launchd and local scheduling

The existing LaunchAgent installs only deterministic ingestion and excerpt rendering. Model jobs are separate, opt-in, and are never installed by that helper.

Two reviewable templates are provided:

- `launchd/io.github.codex-istm-macos.model-daily.plist.template`
- `launchd/io.github.codex-istm-macos.model-structured.plist.template`

Replace every `@TOKEN@`, including `@MEMORY_FOREST_ROOT@` and
`@MEMORY_FOREST_BIN@`, validate the rendered plist with `plutil -lint`, and
inspect the full command before loading it. The example schedule processes the
previous local day: Daily after deterministic ingestion, then one integrated
Structured sweep later. It caps each run at eight model batches.

```zsh
plutil -lint "$HOME/Library/LaunchAgents/io.github.codex-istm-macos.model-daily.plist"
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/io.github.codex-istm-macos.model-daily.plist"
```

Use a different label and plist for Structured memory. To process the current
day incrementally, change the date argument to `today` and choose an
appropriate repeated schedule. The cursor makes later same-day records
eligible without replaying already judged records.

Schedule only after reviewing provider privacy, cost, authentication, network, and retention behavior. LaunchAgent environments have a restricted `PATH`, so use absolute Python, Codex, and Memory Forest executable paths.

## Recovery and retention

- A stored model result is immutable. A retry reuses it instead of rerunning the model.
- The local state is bound to one real Memory Forest root before first invocation.
- A verified Memory Forest receipt makes transaction recovery idempotent. State still advances last.
- Source-prefix or Daily-commit drift fails closed. Prepare a fresh packet; do not edit packet or result hashes.
- Handoff packets, results, and model-Daily evidence duplicate sensitive text or summaries and are stored with private permissions. Keep them out of Git and backups you do not control.
- The existing `archive` command remains copy-only for deterministic Daily excerpts. It does not delete model packets, handoff evidence, state, Memory Forest data, or source history.

There is no automatic purge. Back up both the companion data directory and the
Memory Forest root before any manual retention change. Do not remove committed
model-Daily evidence while it remains a source for Structured preparation.
