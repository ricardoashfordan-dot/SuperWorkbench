#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if command -v python3 >/dev/null 2>&1; then
  exec python3 start.py "$@"
elif command -v python >/dev/null 2>&1; then
  exec python start.py "$@"
else
  echo "Error: Python 3 is required to run Super Workbench." >&2
  exit 1
fi
