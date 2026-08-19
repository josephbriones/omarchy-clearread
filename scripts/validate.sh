#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say() {
  printf '%s\n' "$*"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    say "FAIL: required command not found: $1"
    exit 1
  fi
}

require_command python3
require_command node

say "==> Repository and manifest"
python3 -m json.tool manifest.json >/dev/null
python3 -m unittest tests.test_repository -v

say "==> Python syntax and tests"
python3 -m py_compile lib/clearread.py bin/clearread
python3 -m unittest discover -s tests -p 'test_*.py' -v

say "==> JavaScript model tests"
node tests/test_clearread_model.mjs

say "==> Shell syntax"
while IFS= read -r script; do
  bash -n "$script"
done < <(find scripts -type f -name '*.sh' -print | sort)

if command -v shellcheck >/dev/null 2>&1; then
  say "==> shellcheck"
  while IFS= read -r script; do
    shellcheck "$script"
  done < <(find scripts -type f -name '*.sh' -print | sort)
else
  say "SKIP: shellcheck is not installed"
fi

if command -v qmllint >/dev/null 2>&1; then
  if [[ -n ${OMARCHY_PATH:-} && -d $OMARCHY_PATH/shell ]]; then
    say "==> qmllint"
    qmllint -I "$OMARCHY_PATH/shell" ClearRead.qml
  else
    say "SKIP: qmllint found, but OMARCHY_PATH/shell is unavailable"
  fi
else
  say "SKIP: qmllint is not installed"
fi

if command -v omarchy >/dev/null 2>&1; then
  say "==> Omarchy plugin validation"
  omarchy plugin validate "$ROOT"
elif [[ -n ${OMARCHY_VALIDATOR:-} && -x $OMARCHY_VALIDATOR ]]; then
  say "==> Omarchy plugin validation"
  "$OMARCHY_VALIDATOR" "$ROOT"
else
  say "SKIP: Omarchy plugin validator is unavailable"
fi

say "PASS: portable validation completed"
