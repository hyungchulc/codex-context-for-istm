# Public-release audit

Run the mechanical check before every release:

```zsh
python3 scripts/public_release_audit.py
git log --all -p -- .
```

Then perform this human review:

- Confirm no local output, local state, source fixture copied from a real session, logs, archive, virtual environment, or editor history is tracked.
- Confirm no model packet, model result, model-state cursor, model-Daily handoff evidence, apply marker, Memory Forest plan, receipt, or canonical Memory Forest output is tracked.
- Inspect the complete reachable Git history and the exact release archive as well as the checked-out files. Reject symlinks and generated local data from a release archive.
- Confirm every example uses generic home-relative paths only; no personal absolute path, account, hostname, session identifier, chat, or secret is present.
- Confirm the package remains macOS-only and scoped to local Codex/GPT session JSONL, with no Mail, Calendar, notification, messaging, browser, or cloud integration.
- Confirm deterministic commands remain provider-free and that only explicit `run-model` / `run-model-workflow` invoke Codex. Review provider-processing language and no-tools runner flags against the supported Codex CLI.
- Confirm `apply-model` and `run-model-workflow` require an explicit Memory Forest root and invoke only the configured `memory-forest` executable for canonical writes.
- Confirm both packaged result schemas are closed, the promotion route object is closed, and the schemas are included in a clean wheel/install.
- Confirm licenses and dependency metadata are accurate. The Python runtime dependency set is standard-library only; the Memory Forest CLI is a separate executable dependency for model apply.
- Run unit tests on a clean checkout and inspect the generated synthetic test artifacts only.
- Run a clean-install integration smoke test with this package and Memory Forest installed separately, covering both `apply-daily` and `promote` receipt verification.
- Review the diff for newly added sample text. Synthetic fixtures must never be copied from a private conversation.

The audit script searches tracked text for common absolute personal paths, credential-like prefixes, UUID-shaped identifiers, private runtime artifact names, and missing or open result schemas. It cannot reliably detect every secret or sensitive phrase, recursively prove every schema closure, validate a separately installed Memory Forest executable, or prove provider behavior, so it must not be treated as proof of safety.
