# Roadmap

## Next

- Add migration tooling for explicitly versioned local state formats.
- Add optional local encryption integration documentation without bundling a key manager.
- Expand synthetic fixtures for additional documented Codex message-content shapes.
- Add an explicit, validated integration contract for promoting generated STM inbox cards into an external structured memory tree; do not infer that tree's routes or parents.
- Add read-only retrieval over committed markers without granting retrieval any mutation capability.
- Track Codex CLI isolation-feature compatibility across supported versions.

## Non-goals

- Cloud sync, telemetry, remote storage, account access, notifications, and automatic deletion.
- Mail, Calendar, browser, messaging, or device-history ingestion.
- Allowing a model to choose filesystem paths, mutate cursor state, or bypass deterministic validation/apply.
- Automatic MTM/LTM/XLTM promotion in this companion utility.
