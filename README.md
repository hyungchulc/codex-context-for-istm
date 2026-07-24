# codex-istm-macos

`codex-istm-macos` is a small, standard-library Python pipeline for **macOS only**. Its deterministic core incrementally reads local Codex rollout JSONL session history and writes:

- a bounded ISTM JSONL ledger of user and assistant text records;
- a bounded chronological Daily Markdown digest with deterministic provenance.

An optional, explicit workflow uses the already installed Codex CLI to make semantic ISTM-to-Daily and Daily-to-Structured decisions. Deterministic code freezes bounded packets, validates strict candidates, applies committed model-Daily batches, and writes canonical generated STM cards. It does not require a separately maintained provider API key or SDK.

It handles only local Codex/GPT conversation session history. It does not read Mail, Calendar, notifications, browsers, messages, or any cloud account.

This is an independent, unofficial utility. It is not affiliated with or endorsed by OpenAI or the Codex product team.

Ingestion is model-independent: it reads recorded JSONL events rather than calling a model. Dated model profile observations are documented as references only in [the model workflow](docs/MODEL_WORKFLOW.md); no model is a dependency or hard-coded default.

## Privacy and boundaries

- Deterministic ingestion, digest, archive, prepare, validate, and apply steps are local and do not call a provider.
- `run-model` and `run-model-workflow` are explicit exceptions: they invoke the installed Codex CLI and send the bounded packet to its configured model provider. No model workflow is enabled by the deterministic LaunchAgent.
- The default source is `~/.codex/sessions`; the default output location is `~/Library/Application Support/CodexISTMMacOS`.
- Session text can contain sensitive data. The tool preserves bounded local excerpts; it does not claim to redact secrets. Keep its data directory private and never commit or publish its output.
- Model packets duplicate bounded session text. A model can choose a `sensitive` disposition only after that text has reached the provider; this is not pre-send redaction.
- ISTM provenance uses a hashed source reference rather than a session path or session identifier. The local resume state necessarily retains relative source names, so it is private operational data too.
- The command-line entrypoint refuses to run on non-macOS systems. Its pure parsing library is tested in CI without accessing a real session directory.

## Requirements

- macOS
- Python 3.11 or newer
- A local Codex rollout JSONL directory

No package installation is required when running from this checkout.

## Quick start

From the repository directory:

```zsh
python3 -m codex_istm ingest
python3 -m codex_istm digest --date 2026-07-24
python3 -m codex_istm run-daily
```

Use an explicit, private output location when preferred:

```zsh
python3 -m codex_istm run-daily \
  --source-dir ~/.codex/sessions \
  --state "$HOME/private-codex-istm/state.json" \
  --istm "$HOME/private-codex-istm/istm.jsonl" \
  --daily-dir "$HOME/private-codex-istm/daily"
```

`run-daily` first ingests complete new source lines and then rewrites that day’s digest deterministically. It is safe to rerun after a successful run. It does not generate a semantic AI summary: Daily files are chronological, bounded excerpts.

## Optional model-assisted memory

Choose one installed Codex/GPT model and use it for both stages:

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

The Daily and Structured apply phases are mutating after model judgment and validation. The model itself cannot choose paths or bypass the deterministic apply gate. Generated Structured output is deliberately limited to this companion's fixed STM inbox at `structured/stm/YYYY-MM-DD/`; it is not Memory Forest canonical promotion, and MTM/LTM/XLTM routing is not performed.

Retrieval is a separate read-only concern and must never mutate canonical memory or workflow state. This release does not add a retrieval command.

For reviewable prepare/run/validate/apply commands, transaction details, provider boundaries, dated reference profiles, recovery, and scheduling, read [the model workflow](docs/MODEL_WORKFLOW.md).

## Integrity behavior

For every discovered source, the pipeline saves a byte offset plus a SHA-256 hash of all consumed bytes. On a later run it verifies that exact source prefix before it reads any new bytes. It stops without changing ISTM or state if it encounters:

- a rewrite, truncation, or replacement of a processed source prefix;
- malformed complete JSONL;
- malformed local state or ISTM output;
- duplicate record IDs already present in ISTM output.

An unfinished trailing JSONL line is not consumed; it remains pending until a newline arrives. Deduplication is exact replay protection: identity derives from an opaque source reference, byte span, and raw-event hash, so identical text at distinct source positions remains distinct. Non-conversational or unsupported valid events are counted in the local command result and state but never copied into ISTM.

The output/state write order is intentional: ISTM is atomically replaced before state. If a crash occurs between them, a retry sees the already-written record IDs, skips them safely, and then advances state. It never advances state first.

See [the format reference](docs/FORMAT.md) for record fields and provenance semantics.

## Bounds

Defaults are deliberately modest and configurable:

- each saved message: 8,000 characters;
- each Daily file: 80 records, 24,000 total excerpt UTF-8 bytes, and 480 UTF-8 bytes per excerpt.

The tool stores a truncation marker when it bounds a message. It does not silently split one source message into several records.

## Retention and archival

Daily rendering replaces only the digest for the selected date; it does not append forever. Daily selection uses an explicit IANA timezone (`UTC` by default), and the footer reports omitted records. This keeps the current Daily artifact bounded and reproducible from ISTM.

The `archive` command is copy-only by design:

```zsh
python3 -m codex_istm archive --keep-days 30
python3 -m codex_istm archive --keep-days 30 --apply
```

Without `--apply`, it lists candidates. With `--apply`, it atomically copies each old digest to a year/month archive path and verifies byte-for-byte equality. It never deletes originals or session history. After independently backing up and verifying archives, an operator may choose a separate, manual retention policy; automatic deletion is intentionally out of scope.

Do not delete source rollout files while relying on a state file that references them. If historical source retention must change, preserve the ISTM/state pair together and start a fresh, separately named pipeline only after backup verification.

## LaunchAgent

The installed template runs deterministic `run-daily` once per local day. It never calls a model or sends a notification.

```zsh
python3 scripts/launchagent.py install
python3 scripts/launchagent.py check
python3 scripts/launchagent.py uninstall
```

`install` writes only the current user’s `~/Library/LaunchAgents` plist and log directory, then uses `launchctl bootstrap`. It refuses to overwrite an existing plist unless `--force` is supplied. `check` is read-only. `uninstall` unloads the label and removes only that generated plist; it leaves local ISTM, Daily, logs, and source history untouched. Use `--help` for an explicit data directory or label.

Separate review-only templates for model-Daily and model-Structured are included under `launchd/`. They are not installed automatically. See [model workflow scheduling](docs/MODEL_WORKFLOW.md#launchd-and-local-scheduling).

## Development and release checks

```zsh
python3 -m unittest discover -s tests -v
python3 scripts/public_release_audit.py
```

The release audit checks tracked text for common private absolute-path, credential, and UUID-shaped identifier leaks. It is a guardrail, not a substitute for a human review of generated artifacts, Git history, or release archives. Read [the public-release audit](docs/PUBLIC_RELEASE_AUDIT.md) before publishing.

## Project documents

- [Format and invariants](docs/FORMAT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Model-assisted workflow](docs/MODEL_WORKFLOW.md)
- [Public-release audit](docs/PUBLIC_RELEASE_AUDIT.md)
- [Changelog](CHANGELOG.md)
- [Roadmap](ROADMAP.md)
- [MIT license](LICENSE)

## Limitations

- This is not an official Codex export API; rollout schemas are unsupported and may change. It supports only conservative message-event shapes covered by synthetic fixtures.
- The deterministic Daily digest retains bounded excerpts. Optional model-Daily and generated STM are model-produced semantic memory and may be wrong.
- It does not redact sensitive text, sync across devices, encrypt files, manage backups, or delete data.
- The no-tools Codex runner reduces local side effects but does not make provider processing local or establish provider retention guarantees.
- Generated Structured output stops at a fixed adjacent STM namespace. Automatic MTM/LTM/XLTM promotion and integration into another memory tree are out of scope.
- A changed processed prefix requires deliberate operator recovery; the tool will not guess how to merge divergent history.
