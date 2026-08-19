#!/bin/bash
set -euo pipefail

PLUGIN_ID="io.github.josephbriones.clearread"
REAL=false

if [[ ${1:-} == "--real" ]]; then
  REAL=true
elif [[ $# -gt 0 ]]; then
  printf 'Usage: %s [--real]\n' "$0" >&2
  exit 2
fi

if ! command -v omarchy-shell >/dev/null 2>&1; then
  printf 'FAIL: omarchy-shell is required\n' >&2
  exit 1
fi

plugin_call() {
  omarchy-shell "$PLUGIN_ID" "$@"
}

wait_for_ping() {
  local attempt
  for ((attempt = 0; attempt < 100; attempt++)); do
    [[ $(plugin_call ping 2>/dev/null || true) == "ok" ]] && return 0
    sleep 0.1
  done
  return 1
}

wait_for_state() {
  local wanted=$1 attempt state
  for ((attempt = 0; attempt < 100; attempt++)); do
    state=$(plugin_call state 2>/dev/null || true)
    if python3 - "$wanted" "$state" <<'PY'
import json
import sys

wanted, raw = sys.argv[1:]
try:
    state = json.loads(raw)
except (TypeError, ValueError):
    raise SystemExit(1)

if wanted == "demo-reading":
    ok = (
        state.get("open") is True
        and state.get("demo") is True
        and state.get("state") == "reading"
        and state.get("running") is False
        and state.get("characters", 0) > 0
    )
elif wanted == "closed":
    ok = state.get("open") is False and state.get("running") is False and state.get("characters", 0) == 0
elif wanted == "ready":
    ok = (
        state.get("open") is True
        and state.get("state") == "ready"
        and state.get("ready") is True
        and state.get("running") is False
    )
elif wanted == "reading":
    ok = (
        state.get("open") is True
        and state.get("demo") is False
        and state.get("state") == "reading"
        and state.get("running") is False
        and state.get("mode") in {"window", "region", "clipboard"}
        and state.get("characters", 0) > 0
    )
else:
    ok = False
raise SystemExit(0 if ok else 1)
PY
    then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

printf '==> Summoning deterministic demo\n'
omarchy-shell shell summon "$PLUGIN_ID" '{"demo":true}' >/dev/null
wait_for_ping || { printf 'FAIL: plugin IPC did not register\n' >&2; exit 1; }
wait_for_state demo-reading || { printf 'FAIL: demo did not reach reading state\n' >&2; exit 1; }

printf '==> Closing demo and checking content disposal\n'
omarchy-shell shell hide "$PLUGIN_ID" >/dev/null
wait_for_state closed || { printf 'FAIL: demo did not settle closed\n' >&2; exit 1; }

if [[ $REAL == false ]]; then
  printf 'PASS: deterministic demo opened and closed without capture\n'
  exit 0
fi

printf '==> Opening real readiness surface\n'
omarchy-shell shell summon "$PLUGIN_ID" '{}' >/dev/null
wait_for_state ready || { printf 'FAIL: readiness surface did not settle\n' >&2; exit 1; }

printf '\nUse the ClearRead UI now. Complete one capture with generated fixture text.\n'
printf 'Confirm keyboard focus, presentation controls, and explicit Copy, then press Enter here.\n'
read -r

wait_for_state reading || { printf 'FAIL: no non-empty reading result is open\n' >&2; exit 1; }
omarchy-shell shell hide "$PLUGIN_ID" >/dev/null
wait_for_state closed || { printf 'FAIL: real capture did not close and dispose content\n' >&2; exit 1; }

printf 'PASS: interactive capture reached reading state and closed cleanly\n'
