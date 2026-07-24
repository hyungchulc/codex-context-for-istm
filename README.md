# codex-istm-macos

`codex-istm-macos` is a small, standard-library Python pipeline for **macOS only**. It incrementally reads local Codex rollout JSONL session history and writes two local artifacts:

- a bounded ISTM JSONL ledger of user and assistant text records;
- a bounded chronological Daily Markdown digest with deterministic provenance.

It handles only local Codex/GPT conversation session history. It does not read Mail, Calendar, notifications, browsers, messages, or any cloud account.

This is an independent, unofficial utility. It is not affiliated with or endorsed by OpenAI or the Codex product team.

Reference environment (verified 2026-07-24): **GPT-5.6 Sol** with reasoning effort **xhigh**. Model selection is configurable, and ingestion itself is model-independent: it reads recorded JSONL events rather than calling any model.

## Privacy and boundaries

- Local by default: no network client, telemetry, analytics, model call, account access, or sending capability exists in this repository.
- The default source is `~/.codex/sessions`; the default output location is `~/Library/Application Support/CodexISTMMacOS`.
- Session text can contain sensitive data. The tool preserves bounded local excerpts; it does not claim to redact secrets. Keep its data directory private and never commit or publish its output.
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

The template runs `run-daily` once per local day. It never sends a notification.

```zsh
python3 scripts/launchagent.py install
python3 scripts/launchagent.py check
python3 scripts/launchagent.py uninstall
```

`install` writes only the current user’s `~/Library/LaunchAgents` plist and log directory, then uses `launchctl bootstrap`. It refuses to overwrite an existing plist unless `--force` is supplied. `check` is read-only. `uninstall` unloads the label and removes only that generated plist; it leaves local ISTM, Daily, logs, and source history untouched. Use `--help` for an explicit data directory or label.

## Development and release checks

```zsh
python3 -m unittest discover -s tests -v
python3 scripts/public_release_audit.py
```

The release audit checks tracked text for common private absolute-path, credential, and UUID-shaped identifier leaks. It is a guardrail, not a substitute for a human review of generated artifacts, Git history, or release archives. Read [the public-release audit](docs/PUBLIC_RELEASE_AUDIT.md) before publishing.

## Project documents

- [Format and invariants](docs/FORMAT.md)
- [Public-release audit](docs/PUBLIC_RELEASE_AUDIT.md)
- [Changelog](CHANGELOG.md)
- [Roadmap](ROADMAP.md)
- [MIT license](LICENSE)

## Limitations

- This is not an official Codex export API; rollout schemas are unsupported and may change. It supports only conservative message-event shapes covered by synthetic fixtures.
- It retains bounded raw local text, not semantic summaries or memory promotion decisions.
- It does not redact sensitive text, sync across devices, encrypt files, manage backups, or delete data.
- A changed processed prefix requires deliberate operator recovery; the tool will not guess how to merge divergent history.
