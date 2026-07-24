from __future__ import annotations

from pathlib import Path
import json
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".py", ".toml", ".yml", ".yaml", ".json", ".plist", ".template", ".txt"}
IGNORED_PARTS = {".git", "__pycache__", ".venv", "build", "dist"}
PATTERNS = (
    re.compile("/" + "Users" + "/[A-Za-z0-9_.-]+/"),
    re.compile("/" + "home" + "/[A-Za-z0-9_.-]+/"),
    re.compile("s" + "k" + "-[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)\b[0-9a-f]{8}" + "-" + r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
)
PRIVATE_ARTIFACT_NAMES = {"model-state.json", "state.json", "istm.jsonl"}
PRIVATE_ARTIFACT_SUFFIXES = {".packet.json", ".result.json"}
PRIVATE_OUTPUT_ROOTS = {"handoffs", "model-daily", "structured"}
RESULT_SCHEMAS = (
    "istm-to-daily-result-v1.schema.json",
    "daily-to-memory-forest-result-v2.schema.json",
)


def tracked_or_present_files() -> list[Path]:
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=False)
    tracked = [ROOT / item for item in result.stdout.decode("utf-8", errors="replace").split("\0") if item]
    candidates = set(tracked) | set(ROOT.rglob("*"))
    return sorted(
        path
        for path in candidates
        if path.is_file() and path.suffix in TEXT_SUFFIXES and not any(part in IGNORED_PARTS for part in path.parts)
    )


def main() -> int:
    findings: list[str] = []
    for path in tracked_or_present_files():
        relative = path.relative_to(ROOT)
        if (
            path.name in PRIVATE_ARTIFACT_NAMES
            or any(path.name.endswith(suffix) for suffix in PRIVATE_ARTIFACT_SUFFIXES)
            or (relative.parts and relative.parts[0] in PRIVATE_OUTPUT_ROOTS)
        ):
            findings.append(f"private runtime artifact is tracked: {relative}")
        try:
            contents = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"non-UTF-8 text file: {path.relative_to(ROOT)}")
            continue
        for pattern in PATTERNS:
            if pattern.search(contents):
                findings.append(f"possible private data pattern: {path.relative_to(ROOT)}")
                break
    schema_root = ROOT / "codex_istm" / "schemas"
    for name in RESULT_SCHEMAS:
        path = schema_root / name
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            findings.append(f"missing or invalid packaged result schema: codex_istm/schemas/{name}")
            continue
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            findings.append(f"result schema is not closed at top level: codex_istm/schemas/{name}")
        if name == "daily-to-memory-forest-result-v2.schema.json":
            properties = schema.get("properties", {})
            promotions = properties.get("promotions", {}).get("items", {})
            route = promotions.get("properties", {}).get("route", {})
            if (
                properties.get("schema_version", {}).get("const")
                != "codex-istm-model-result-v2"
                or properties.get("stage", {}).get("const")
                != "daily_to_memory_forest"
                or promotions.get("additionalProperties") is not False
                or route.get("additionalProperties") is not False
                or set(route.get("required", []))
                != {"domain", "domain_title", "branch", "branch_title", "leaf"}
            ):
                findings.append(
                    "Memory Forest result schema does not freeze its v2 semantic route contract"
                )
    if findings:
        print("public-release audit failed:", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("public-release audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
