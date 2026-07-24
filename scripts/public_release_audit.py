from __future__ import annotations

from pathlib import Path
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


def tracked_or_present_files() -> list[Path]:
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=False)
    tracked = [ROOT / item for item in result.stdout.decode("utf-8", errors="replace").split("\0") if item]
    candidates = tracked or list(ROOT.rglob("*"))
    return sorted(
        path
        for path in candidates
        if path.is_file() and path.suffix in TEXT_SUFFIXES and not any(part in IGNORED_PARTS for part in path.parts)
    )


def main() -> int:
    findings: list[str] = []
    for path in tracked_or_present_files():
        try:
            contents = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"non-UTF-8 text file: {path.relative_to(ROOT)}")
            continue
        for pattern in PATTERNS:
            if pattern.search(contents):
                findings.append(f"possible private data pattern: {path.relative_to(ROOT)}")
                break
    if findings:
        print("public-release audit failed:", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("public-release audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
