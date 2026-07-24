# Architecture

## Data flow

```text
local Codex rollout JSONL
  -> deterministic ingest
  -> append-only ISTM JSONL + prefix checkpoint
  -> bounded ISTM-to-Daily packet
  -> Codex/GPT candidate
  -> deterministic validate + ISTM rebind
  -> immutable local JSON/Markdown handoff evidence
  -> memory-forest --json apply-daily ROOT PLAN
  -> verified canonical Daily receipt
  -> Daily commit marker + Daily cursor
  -> bounded daily_to_memory_forest packet
     + bounded current XLTM/LTM/MTM/STM snapshot
     + exact layer/tree/branch/leaf policy
  -> Codex/GPT integrated Structured candidate
  -> deterministic validate + exact Daily commit rebind
  -> memory-forest --json apply-structured ROOT PLAN
  -> verified canonical whole-sweep receipt
  -> memory_forest cursor
```

Ingestion remains deterministic and provider-independent. The model returns a
candidate only. Deterministic code owns source admission, exact provenance,
plan construction, invocation, receipt verification, and cursor mutation.
Memory Forest alone owns canonical paths, hierarchy materialization, validation,
audit, indexing, and idempotent writer receipts.

## Transaction model

Packets are content-addressed immutable JSON. They bind a stage, policy and
result-schema hashes, ISO date, IANA timezone, source snapshot, per-date
admission cursor, item bounds, exact identities, and the count left for a later
batch. Results are immutable JSON bound to one packet. Every admitted ID must
appear exactly once in a Daily group or omission, then exactly once as a
Structured disposition.

Daily apply is evidence-first, receipt-before-commit, and cursor-last:

1. lock the workflow state and verify the root and `forest_id` binding and packet cursor;
2. rebind the exact ISTM prefix;
3. create or adopt immutable local JSON/Markdown handoff evidence;
4. durably establish the root and identity binding if this is the state's first transaction;
5. build the exact `memory-forest-daily-plan-v1` in a private temporary file;
6. invoke `memory-forest --json apply-daily ROOT PLAN`;
7. validate the one-object response, receipt path, receipt bytes, hash,
   operation, and transaction;
8. create the Daily commit marker that binds evidence, plan, and receipt;
9. advance the Daily cursor last.

Structured apply is receipt-before-cursor:

1. lock the shared workflow state;
2. fully reload and verify every committed Daily marker and referenced evidence;
3. require the packet's complete ordered marker-hash set to remain exact;
4. durably establish the root and identity binding if this is the state's first transaction;
5. rebind the frozen current-Forest context used for semantic review;
6. build `memory-forest-structured-sweep-plan-v1` in a private temporary file;
7. invoke `memory-forest --json apply-structured ROOT PLAN`;
8. verify the response and receipt file;
9. advance the `memory_forest` cursor last.

The transaction ID is the Daily batch ID for `apply-daily` and the exact model
result SHA-256 for `apply-structured`. A timeout or nonzero exit never advances local
state. Retrying the same plan is safe because the Memory Forest writer contract
is idempotent and returns the existing matching receipt.

## Output ownership

Local model-Daily handoff evidence remains under:

```text
model-daily/YYYY-MM-DD/
  batches/<packet-sha256>.json
  batches/<packet-sha256>.md
  commits/<batch-id>.json
```

These files preserve the frozen model judgment and exact source bindings for
review and replay. They are not canonical Daily files. Canonical Daily and
Structured memory is written only inside the configured Memory Forest
root by its installed CLI. This package creates no `structured/` output tree.

The `daily_to_memory_forest` result is schema v3. It contains bounded semantic
`changes` and exact source `dispositions`. A change may target any structured
layer with only the identifiers valid for that layer:

```json
{
  "layer": "stm",
  "tree": "memory-systems",
  "branch": "deterministic-apply",
  "leaf": "model-output-gate"
}
```

Creates require a missing target and `expected_sha256: null`. Replacements must
copy the exact frozen body hash. The result carries complete validator-ready
Markdown bodies, but it cannot return a filesystem path, delete, move, commit
marker, or cursor mutation. Target slugs are bounded lowercase kebab-case
identifiers; deterministic code maps the closed semantic target to its
canonical path.

## Layer and structure policy

The packet embeds the versioned public policy used by the model.

- STM stores detailed reconstructable meaning and splits leaves actively for
  named entities, episodes, concrete subtopics, repeated questions, exact
  numbers, deadlines, corrections, administrative state, failures, and
  verification.
- MTM compresses recurring, still-live STM evidence into branches. A new branch
  requires a distinct current center and reread lane with repetition,
  persistence, or expected follow-up.
- LTM stores durable themes, stable concerns, enduring preference clusters, and
  long-lived capability context. New trees are conservative.
- XLTM stores identity-level truths, persistent direction, strong preferences,
  and repeated long-horizon classification axes. Forest-level changes are the
  most conservative structural change.

This is one integrated decision over the current forest. Parent-before-child is
only the internal creation order when the same sweep needs updated XLTM forest
authority, an LTM tree, MTM branch, and STM leaf. `tree` names the LTM owner in
semantic targets. It is not an extra level between Forest and Tree.

## State and migration

`codex-istm-model-state-v2` has `daily` and `memory_forest` cursors, a hash
binding to one real Memory Forest root, and its stable private `forest_id`.
Reusing that state against another root or a replacement forest at the same
path fails closed. The binding is saved before the first writer invocation; per-date
cursors remain receipt-verified and cursor-last. Legacy v1 state and
`daily_to_structured` v1 results are rejected; they are never reinterpreted as
proof of canonical Memory Forest completion.

## Failure boundaries

- Source rewrite, stale cursor, changed Daily commit set, malformed packet or
  result, unknown/duplicate/missing disposition, duplicate target, invalid slug,
  symlink, root mismatch, nonzero writer exit, stdout leakage, malformed receipt,
  receipt hash mismatch, or transaction mismatch fails closed.
- A later ISTM append does not invalidate a frozen prefix. A later committed
  Daily batch does invalidate an in-flight Structured packet.
- All-source-only batches still invoke the writer and require a verified no-op
  receipt before their cursor advances.
- No command deletes rollout history, ISTM, handoffs, canonical memory, state,
  receipts, or archives.
