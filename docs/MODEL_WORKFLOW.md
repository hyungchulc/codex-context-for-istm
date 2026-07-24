# Model-assisted Daily and Structured workflow

The optional model workflow uses the Codex CLI that is already installed and authenticated on the Mac. It does not require a separately maintained provider API key or SDK. It **does send each prepared packet to the configured model provider**. This is not a local-only transform.

The deterministic ingestion commands remain unchanged and make no model call. Model use starts only when an operator explicitly runs `run-model` or `run-model-workflow`.

## Trust boundary

Each mutating stage has five separate steps:

1. deterministic code freezes an immutable, bounded packet;
2. `codex exec` returns a strict candidate;
3. deterministic code validates schema, bounds, exact source coverage, producer provenance, and packet binding;
4. deterministic code rebinds the current source, preflights fixed targets, writes canonical artifacts, reads them back, and writes a commit marker last;
5. deterministic code advances the admitted-item cursor only after the commit verifies.

The model cannot choose a filesystem path, write canonical memory, mark a cursor, or bypass validation. The deterministic apply step is intentionally mutating: it creates committed Daily batches or generated STM cards after validation. A retrieval operation is different: retrieval is read-only and must never change canonical memory or cursor state. This release does not add a retrieval command.

Packet items are untrusted data in the model prompt. The runner uses an isolated private temporary working directory, `--ephemeral`, `--sandbox read-only`, `--ignore-user-config`, `--ignore-rules`, `--strict-config`, an explicit model and reasoning effort, and an enumerated set of disabled tool features. These flags reduce local side effects; they do not prove provider-side confidentiality or retention behavior, and a future Codex CLI may change feature semantics.

Sensitive-model omission is a semantic decision made **after the provider has received the bounded packet**. It is not redaction before transmission. Review the packet before `run-model` when its contents require special handling.

## Explicit three-command flow

First ingest new local rollout data:

```zsh
python3 -m codex_istm ingest
```

Freeze a Daily batch:

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
  --result "${PACKET_PATH%.packet.json}.result.json"
```

After at least one committed Daily batch, repeat the same flow with:

```zsh
python3 -m codex_istm prepare-model-structured \
  --date previous-local-day \
  --timezone Europe/Stockholm
```

`apply-model` infers the stage from the packet. Daily output is committed beneath `model-daily/YYYY-MM-DD/`. Structured output is this companion utility's generated STM inbox at `structured/stm/YYYY-MM-DD/`; it is not a canonical promotion into Memory Forest or another memory system.

## Bounded one-command flow

The explicit orchestrator still preserves packet, result, commit, and state files:

```zsh
python3 -m codex_istm run-model-workflow daily \
  --date previous-local-day \
  --timezone Europe/Stockholm \
  --model "$MODEL_ID" \
  --reasoning-effort xhigh \
  --max-batches 8

python3 -m codex_istm run-model-workflow structured \
  --date previous-local-day \
  --timezone Europe/Stockholm \
  --model "$MODEL_ID" \
  --reasoning-effort xhigh \
  --max-batches 8
```

`--max-batches` is an explicit cost and work bound. A packet admits at most the configured item and byte limits. Items beyond the current packet are reported as `not_yet_admitted`; they remain eligible for the next batch. Model-omitted items are different: they receive an explicit disposition and advance the cursor after a verified commit.

Use the same installed model for both stages unless there is a deliberate reason not to. Nothing in the format requires a specific model.

## Dated reference profiles

These were observed reference choices on 2026-07-24, not defaults, dependencies, recommendations, or routing branches:

- interactive reference: GPT-5.6 Sol / `xhigh`;
- one production automation reference: Daily GPT-5.6 Luna / `xhigh`, Structured GPT-5.6 Sol / `max`.

Most public users can select one installed Codex/GPT model and one supported reasoning effort for both stages. The exact model and effort are recorded in every stored result and canonical artifact.

## launchd and local scheduling

The existing LaunchAgent installs only deterministic ingestion and excerpt rendering. Model jobs are separate, opt-in, and are never installed by that helper.

Two reviewable templates are provided:

- `launchd/io.github.codex-istm-macos.model-daily.plist.template`
- `launchd/io.github.codex-istm-macos.model-structured.plist.template`

Replace every `@TOKEN@`, validate the rendered plist with `plutil -lint`, and inspect the full command before loading it. The example schedule processes the previous local day: Daily after deterministic ingestion, then Structured later. It caps each run at eight model batches.

```zsh
plutil -lint "$HOME/Library/LaunchAgents/io.github.codex-istm-macos.model-daily.plist"
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/io.github.codex-istm-macos.model-daily.plist"
```

Use a different label and plist for Structured. To process the current day incrementally, change the date argument to `today` and choose an appropriate repeated schedule. The cursor makes later same-day records eligible without replaying already judged records.

Schedule only after reviewing provider privacy, cost, authentication, network, and retention behavior. LaunchAgent environments have a restricted `PATH`, so use absolute Python and Codex executable paths.

## Recovery and retention

- A stored result is immutable. A retry reuses it instead of rerunning the model.
- Files without a matching commit marker are not committed canonical output. A retry adopts exact partial files or fails on any conflict, then writes the marker.
- State advances last. If a crash happens after the marker but before state, a retry verifies and marks the exact batch.
- Source-prefix or Daily-commit drift fails closed. Prepare a fresh packet; do not edit packet or result hashes.
- Handoff packets and results duplicate sensitive text or summaries and are stored with private permissions. Keep them out of Git and backups you do not control.
- The existing `archive` command remains copy-only for deterministic Daily excerpts. It does not delete model packets, committed Daily batches, STM cards, state, or source history.

There is no automatic purge. Back up the complete data directory before any manual retention change. Do not remove committed Daily batches while they remain a source for Structured preparation.
