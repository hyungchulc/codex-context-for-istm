# Roadmap

## Next

- Add migration tooling for explicitly versioned local state formats.
- Add optional local encryption integration documentation without bundling a key manager.
- Expand synthetic fixtures for additional documented Codex message-content shapes.
- Add read-only retrieval over committed markers without granting retrieval any mutation capability.
- Track Codex CLI isolation-feature compatibility across supported versions.
- Track the separately installed Memory Forest CLI response contract across supported versions.

## Non-goals

- Cloud sync, telemetry, remote storage, account access, notifications, and automatic deletion.
- Mail, Calendar, browser, messaging, or device-history ingestion.
- Allowing a model to choose filesystem paths, memory layers, operations, Markdown, mutate cursor state, or bypass deterministic validation/apply.
- Reimplementing Memory Forest canonical layout, parent creation, indexing, or receipt ownership in this companion utility.
