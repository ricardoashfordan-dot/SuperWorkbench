#!/usr/bin/env python3
"""Zero-dependency guard: verify start.py and workbench/**/*.py import only Python stdlib or local modules."""
import argparse
import ast
import sys
from pathlib import Path

LOCAL_MODULES = {
    "config",
    "adapters",
    "runner",
    "presets",
    "skills",
    "threads",
    "mcp_manager",
    "server",
    "workbench",
}


def collect_target_files(root: Path) -> list[Path]:
    files: list[Path] = []
    start_py = root / "start.py"
    if start_py.is_file():
        files.append(start_py)
    wb_dir = root / "workbench"
    if wb_dir.is_dir():
        files.extend(sorted(wb_dir.rglob("*.py")))
    return files


def check_repo(root: Path) -> tuple[list[tuple[str, int, str]], int]:
    allowed = set(sys.stdlib_module_names) | LOCAL_MODULES | {"__future__"}
    offenders: list[tuple[str, int, str]] = []
    targets = collect_target_files(root)

    for path in targets:
        rel = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".", 1)[0]
                    if top and top not in allowed:
                        offenders.append((rel, node.lineno, top))
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue
                if node.module:
                    top = node.module.split(".", 1)[0]
                    if top and top not in allowed:
                        offenders.append((rel, node.lineno, top))

    return offenders, len(targets)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify start.py and workbench/*.py use Python stdlib only.")
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parent.parent),
        help="Repository root to scan (defaults to this repository)",
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()
    offenders, scanned = check_repo(root)

    if offenders:
        for rel, lineno, mod in offenders:
            print(f"{rel}:{lineno} {mod}", file=sys.stderr)
        return 1

    print(f"stdlib-only check passed ({scanned} files scanned, 0 third-party imports).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
