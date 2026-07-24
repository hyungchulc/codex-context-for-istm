# Changelog

## 0.2.0 — 2026-07-24

- Added opt-in, existing-Codex-CLI ISTM-to-Daily and Daily-to-generated-STM workflows without a separately maintained provider API integration.
- Added bounded content-addressed packets, packaged strict result schemas, explicit model/effort and Codex CLI provenance, exact disposition coverage, source rebinds, immutable result reuse, and fail-closed validation.
- Added per-date admitted-item cursors and bounded multi-batch draining for same-day overflow and later arrivals.
- Added marker-last, state-last Daily batch and generated STM writes with fixed deterministic paths, conflict preflight, private permissions, readback hashes, and idempotent recovery.
- Added no-tools runner hardening, inert Markdown rendering, model scheduling templates, architecture/format/privacy documentation, synthetic workflow tests, and expanded public-release audit coverage.

## 0.1.0 — 2026-07-24

- Initial public release.
- Added macOS-only local Codex rollout JSONL ingestion with offsets, prefix hashes, bounded records, and fail-closed deduplication.
- Added deterministic bounded Daily Markdown, copy-only archival, LaunchAgent tooling, tests, and public-release checks.
