# Public-release audit

Run the mechanical check before every release:

```zsh
python3 scripts/public_release_audit.py
git log --all -p -- .
```

Then perform this human review:

- Confirm no local output, local state, source fixture copied from a real session, logs, archive, virtual environment, or editor history is tracked.
- Inspect the complete reachable Git history and the exact release archive as well as the checked-out files. Reject symlinks and generated local data from a release archive.
- Confirm every example uses generic home-relative paths only; no personal absolute path, account, hostname, session identifier, chat, or secret is present.
- Confirm the package remains macOS-only and scoped to local Codex/GPT session JSONL, with no Mail, Calendar, notification, messaging, browser, or cloud integration.
- Confirm default-local boundaries and the absence of automatic deletion, sending, model calls, and telemetry are still true in code.
- Confirm licenses and dependency metadata are accurate. The intended runtime dependency set is Python’s standard library only.
- Run unit tests on a clean checkout and inspect the generated synthetic test artifacts only.
- Review the diff for newly added sample text. Synthetic fixtures must never be copied from a private conversation.

The audit script searches tracked text for common absolute personal paths, credential-like prefixes, and UUID-shaped identifiers. It cannot reliably detect every secret or sensitive phrase, so it must not be treated as proof of safety.
