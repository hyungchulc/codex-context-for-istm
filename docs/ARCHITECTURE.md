# Architecture

## Data flow

```text
local Codex rollout JSONL
  -> deterministic ingest
  -> append-only ISTM JSONL + prefix checkpoint
  -> bounded ISTM-to-Daily packet
  -> Codex/GPT candidate
  -> deterministic validate/rebind/apply
  -> committed model-Daily batches + admitted-item cursor
  -> bounded Daily-to-Structured packet
  -> Codex/GPT candidate
  -> deterministic validate/rebind/apply
  -> committed generated STM cards + admitted-item cursor
```

Ingestion remains deterministic and provider-independent. Both mutating memory transitions require semantic model judgment in the full workflow. The model only returns a candidate; deterministic code owns source admission, path resolution, publication, verification, and cursor mutation.

## Transaction model

Packets are content-addressed immutable JSON. They bind a stage, strict policy and result-schema hashes, ISO date, IANA timezone, source snapshot, per-date admission cursor, item bounds, exact identities, and a count of items left for a later batch.

Results are immutable JSON bound to one packet. Cross-object validation requires every admitted item to appear exactly once: either in an included/promoted group or an explicit omission. JSON Schema alone does not enforce this, so Python validation repeats it before apply.

Apply is marker-last and state-last:

1. lock the workflow state;
2. verify the packet's cursor is current;
3. rebind the ISTM prefix or complete set of committed Daily source markers;
4. compute every deterministic target and preflight all existing paths;
5. create or adopt exact immutable artifact files;
6. read back and hash the files;
7. create the immutable commit/apply marker;
8. advance the admitted-item cursor.

Readers should accept only artifacts named by a valid commit marker. An interrupted run can leave an uncommitted exact file, but cannot advance the cursor. Retry completes the same transaction or fails on conflict.

## Canonical output contracts

Model-Daily is a sequence of committed batches under:

```text
model-daily/YYYY-MM-DD/
  batches/<packet-sha256>.json
  batches/<packet-sha256>.md
  commits/<batch-id>.json
```

The JSON batch is the machine-readable canonical record. Markdown is a deterministic inert rendering. The marker binds both hashes.

Public Structured output is deliberately adjacent and bounded:

```text
structured/
  stm/YYYY-MM-DD/<memory-id>.md
  .applied/<result-sha256>.json
```

This `generated-stm` namespace is the committed generated STM inbox owned by this companion utility. It is not canonical Memory Forest promotion and does not claim ownership of another memory system's STM/MTM/LTM/XLTM tree. The model cannot name a layer or path. This release does not automatically promote to MTM, LTM, or XLTM; integrating those layers requires a separate route contract and parent validation.

Generated summaries and cards are low-trust data. They can be wrong or contain prompt-like text. They are never authority or executable instructions.

## Read-only retrieval boundary

Daily and Structured apply are mutating pipelines after semantic judgment and validation. Retrieval is read-only: a retrieval implementation may inspect committed artifacts but must never create, update, promote, mark, or otherwise mutate canonical memory or workflow state. Retrieval is not implemented in this release.

## Failure boundaries

- Source prefix rewrite, missing tracked source, stale cursor, changed Daily commit set, malformed packet/result, unknown/duplicate/missing disposition, oversized content, unsafe date/timezone, symlink, path conflict, or readback hash mismatch fails closed.
- A later ISTM append does not invalidate a frozen prefix. It remains eligible in the next batch after the current packet commits.
- A later committed Daily batch does invalidate an in-flight Structured packet, because its source commit set is an exact freshness binding.
- No command deletes rollout history, ISTM, Daily, Structured, state, packet, result, marker, or archive data.
