from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import plistlib
import re
import subprocess
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = PROJECT_ROOT / "launchd" / "io.github.codex-istm-macos.plist.template"
DEFAULT_LABEL = "io.github.codex-istm-macos"


def default_data_dir() -> Path:
    return Path("~/Library/Application Support/CodexISTMMacOS").expanduser()


def default_source_dir() -> Path:
    return Path("~/.codex/sessions").expanduser()


def require_macos() -> None:
    if platform.system() != "Darwin":
        raise RuntimeError("LaunchAgent management is supported on macOS only")


def safe_label(value: str) -> str:
    prefix = "io.github.codex-istm-macos"
    if value == prefix or value.startswith(prefix + "."):
        return value
    raise ValueError(f"label must be {prefix} or one of its dotted sublabels")


def plist_path(label: str) -> Path:
    return Path("~/Library/LaunchAgents").expanduser() / f"{label}.plist"


def atomic_write(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def render(label: str, source_dir: Path, data_dir: Path) -> bytes:
    substitutions = {
        "@LABEL@": label,
        "@PYTHON@": str(Path(sys.executable).resolve()),
        "@PROJECT_ROOT@": str(PROJECT_ROOT),
        "@SOURCE_DIR@": str(source_dir.expanduser().resolve()),
        "@DATA_DIR@": str(data_dir.expanduser().resolve()),
        "@LOG_DIR@": str((data_dir / "logs").expanduser().resolve()),
    }
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    for token, value in substitutions.items():
        template = template.replace(token, value)
    if re.search(r"@[A-Z_]+@", template):
        raise RuntimeError("LaunchAgent template has an unresolved placeholder")
    rendered = template.encode("utf-8")
    plistlib.loads(rendered)
    return rendered


def launchctl(arguments: list[str], check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *arguments], text=True, capture_output=True, check=check)


def install(label: str, source_dir: Path, data_dir: Path, force: bool) -> Path:
    target = plist_path(label)
    if target.exists() and not force:
        raise RuntimeError(f"{target.name} already exists; use --force only to replace this tool's plist")
    data_dir.expanduser().mkdir(parents=True, exist_ok=True)
    (data_dir.expanduser() / "logs").mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    if target.exists():
        launchctl(["bootout", f"{domain}/{label}"], check=False)
    atomic_write(target, render(label, source_dir, data_dir))
    launchctl(["bootstrap", domain, str(target)], check=True)
    launchctl(["enable", f"{domain}/{label}"], check=True)
    return target


def check(label: str) -> int:
    result = launchctl(["print", f"gui/{os.getuid()}/{label}"], check=False)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return result.returncode


def uninstall(label: str) -> bool:
    target = plist_path(label)
    launchctl(["bootout", f"gui/{os.getuid()}/{label}"], check=False)
    if target.exists():
        target.unlink()
        return True
    return False


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Install, inspect, or remove the local codex-istm-macos LaunchAgent")
    result.add_argument("command", choices=("install", "check", "uninstall"))
    result.add_argument("--label", default=DEFAULT_LABEL)
    result.add_argument("--source-dir", type=Path, default=default_source_dir())
    result.add_argument("--data-dir", type=Path, default=default_data_dir())
    result.add_argument("--force", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        require_macos()
        label = safe_label(args.label)
        if args.command == "install":
            target = install(label, args.source_dir, args.data_dir, args.force)
            print(f"installed={target}")
            return 0
        if args.command == "check":
            return check(label)
        print(f"removed={uninstall(label)}")
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
